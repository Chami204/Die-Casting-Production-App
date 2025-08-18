import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production App"
DEFAULT_SUBTOPICS = [
    "Input number of pcs",
    "Input time",
    "Output number of pcs",
    "Output time",
    "Num of pcs to rework",
    "Number of rejects"
]
FIXED_COLS = ["EntryID", "Timestamp", "Product", "Comments"]

# ------------------ Google Sheets Functions ------------------
def get_gs_client():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=scopes
        )
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {str(e)}")
        st.stop()

def open_spreadsheet(client):
    try:
        name = st.secrets["gsheet"]["spreadsheet_name"]
        return client.open(name)
    except Exception as e:
        st.error(f"Error opening spreadsheet: {str(e)}")
        st.stop()

def ensure_worksheets(sh):
    # Config sheet
    try:
        ws_config = sh.worksheet("Config")
    except gspread.WorksheetNotFound:
        ws_config = sh.add_worksheet(title="Config", rows=1000, cols=2)
        ws_config.update("A1", [["Product", "Subtopic"]])
        ws_config.freeze(rows=1)

    # History sheet
    try:
        ws_history = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title="History", rows=2000, cols=50)
        headers = FIXED_COLS + DEFAULT_SUBTOPICS
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)

    return ws_config, ws_history

# ------------------ Config & History Functions ------------------
def read_config(ws_config):
    try:
        values = ws_config.get_all_records()
        cfg = {}
        for row in values:
            p = str(row.get("Product", "")).strip()
            s = str(row.get("Subtopic", "")).strip()
            if p and s:
                cfg.setdefault(p, []).append(s)
        return cfg
    except Exception as e:
        st.error(f"Error reading config: {str(e)}")
        return {}

def write_config(ws_config, cfg):
    try:
        rows = [["Product", "Subtopic"]]
        for product, subs in cfg.items():
            for s in subs:
                rows.append([product, s])
        ws_config.update("A1", rows)
        return True
    except Exception as e:
        st.error(f"Error writing config: {str(e)}")
        return False

def append_history(ws_history, record):
    try:
        headers = ws_history.row_values(1)
        row = [record.get(h, "") for h in headers]
        ws_history.append_row(row)
        return True
    except Exception as e:
        st.error(f"Error saving history: {str(e)}")
        return False

def get_recent_entries(ws_history, product, limit=50):
    try:
        values = ws_history.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        if "Product" in df.columns:
            df = df[df["Product"] == product]
        return df.sort_values("Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error reading history: {str(e)}")
        return pd.DataFrame()

# ------------------ UI Functions ------------------
def admin_ui(ws_config):
    st.subheader("Admin • Manage Products & Subtopics")
    cfg = read_config(ws_config)

    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in cfg:
                st.warning("Product already exists.")
            else:
                cfg[new_product] = DEFAULT_SUBTOPICS.copy()
                if write_config(ws_config, cfg):
                    st.success(f"Created product '{new_product}'")
                    st.experimental_rerun()

    if cfg:
        with st.expander("Edit Product"):
            product = st.selectbox("Select Product", sorted(cfg.keys()))
            st.write("Current subtopics:", cfg[product])

            new_sub = st.text_input("Add New Subtopic")
            if st.button("Add Subtopic"):
                if new_sub.strip():
                    cfg[product].append(new_sub.strip())
                    if write_config(ws_config, cfg):
                        st.success(f"Added subtopic '{new_sub}'")
                        st.experimental_rerun()

            to_remove = st.multiselect("Select subtopics to remove", cfg[product])
            if st.button("Remove Selected"):
                cfg[product] = [s for s in cfg[product] if s not in to_remove]
                if write_config(ws_config, cfg):
                    st.success("Subtopic(s) removed")
                    st.experimental_rerun()

        with st.expander("Delete Product"):
            to_delete = st.selectbox("Product to delete", sorted(cfg.keys()))
            if st.button("Delete Permanently"):
                del cfg[to_delete]
                if write_config(ws_config, cfg):
                    st.error(f"Deleted product '{to_delete}'")
                    st.experimental_rerun()

def user_ui(ws_config, ws_history):
    st.subheader("Production Data Entry")
    cfg = read_config(ws_config)
    
    if not cfg:
        st.info("No products configured. Please contact admin.")
        return

    product = st.selectbox("Select Product", sorted(cfg.keys()))
    subtopics = cfg.get(product, DEFAULT_SUBTOPICS)

    values = {}
    for subtopic in subtopics:
        if "number" in subtopic.lower() or "num" in subtopic.lower():
            values[subtopic] = st.number_input(subtopic, min_value=0, step=1)
        elif "time" in subtopic.lower():
            values[subtopic] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    comments = st.text_area("Comments")

    if st.button("Submit Entry"):
        record = {
            "EntryID": uuid.uuid4().hex,
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Product": product,
            **values,
            "Comments": comments
        }
        if append_history(ws_history, record):
            st.success("Entry saved successfully!")
            st.experimental_rerun()

    st.subheader("Recent Entries")
    df = get_recent_entries(ws_history, product)
    st.dataframe(df if not df.empty else pd.DataFrame(), use_container_width=True)

# ------------------ Main App ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)

    try:
        client = get_gs_client()
        sh = open_spreadsheet(client)
        ws_config, ws_history = ensure_worksheets(sh)
        
        mode = st.sidebar.radio(
            "Application Mode",
            ["Data Entry", "Admin"],
            index=0
        )

        if mode == "Admin":
            if st.text_input("Admin Password", type="password") == "admin123":
                admin_ui(ws_config)
            else:
                st.warning("Please enter the correct admin password")
        else:
            user_ui(ws_config, ws_history)

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()
