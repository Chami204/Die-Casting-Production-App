import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production App"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
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
        rows = [["Product", "Subtopic"]]
        ws_config.update("A1", rows)
        ws_config.freeze(rows=1)

    # History sheet
    try:
        ws_history = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title="History", rows=2000, cols=50)
        ws_history.update("A1", [FIXED_COLS + DEFAULT_SUBTOPICS])
        ws_history.freeze(rows=1)

    return ws_config, ws_history

# ------------------ Config & History Functions ------------------
def read_config(ws_config):
    values = ws_config.get_all_records()
    cfg = {}
    for row in values:
        p = str(row.get("Product", "")).strip()
        s = str(row.get("Subtopic", "")).strip()
        if not p or not s:
            continue
        cfg.setdefault(p, []).append(s)
    return cfg

def write_config(ws_config, cfg: dict):
    rows = [["Product", "Subtopic"]]
    for product, subs in cfg.items():
        for s in subs:
            rows.append([product, s])
    ws_config.clear()
    ws_config.update("A1", rows)
    ws_config.freeze(rows=1)

def get_recent_entries(ws_history, product: str, limit: int = 50) -> pd.DataFrame:
    values = ws_history.get_all_records()
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    if "Product" in df.columns:
        df = df[df["Product"] == product]
    df = df.sort_values(by="Timestamp", ascending=False).head(limit)
    return df

# ------------------ UI Functions ------------------
def admin_ui(ws_config):
    st.subheader("Admin • Manage Products & Subtopics")
    cfg = read_config(ws_config)

    # Create new product
    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in cfg:
                st.warning("That product already exists.")
            else:
                cfg[new_product] = DEFAULT_SUBTOPICS.copy()
                write_config(ws_config, cfg)
                st.success(f"Product '{new_product}' created with default subtopics.")
                st.experimental_rerun()

    # Edit existing product
    if cfg:
        with st.expander("Edit Product"):
            prod = st.selectbox("Select Product", sorted(cfg.keys()))
            st.caption("Current subtopics:")
            st.write(cfg[prod] if cfg[prod] else "— none —")

            new_sub = st.text_input("Add Subtopic")
            if st.button("Add Subtopic to Product"):
                if new_sub.strip():
                    cfg[prod].append(new_sub.strip())
                    write_config(ws_config, cfg)
                    st.success(f"Added '{new_sub}' to {prod}.")
                    st.experimental_rerun()

            subs_to_remove = st.multiselect("Remove subtopics", cfg[prod])
            if st.button("Remove Selected Subtopics"):
                if subs_to_remove:
                    cfg[prod] = [s for s in cfg[prod] if s not in subs_to_remove]
                    write_config(ws_config, cfg)
                    st.warning(f"Removed: {', '.join(subs_to_remove)}")
                    st.experimental_rerun()

        # Delete product
        with st.expander("Delete Product"):
            prod_del = st.selectbox("Choose product to delete", sorted(cfg.keys()))
            if st.button("Delete Product Permanently"):
                del cfg[prod_del]
                write_config(ws_config, cfg)
                st.error(f"Deleted product '{prod_del}' and its subtopics.")
                st.experimental_rerun()

def user_ui(ws_config, ws_history):
    st.subheader("User • Enter Data")
    cfg = read_config(ws_config)
    
    if not cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Main Product", sorted(cfg.keys()))
    current_subtopics = cfg.get(product, DEFAULT_SUBTOPICS)
    
    values = {}
    for subtopic in current_subtopics:
        if "number of pcs" in subtopic.lower() or "num of pcs" in subtopic.lower():
            values[subtopic] = st.number_input(subtopic, min_value=0, step=1)
        elif "time" in subtopic.lower():
            values[subtopic] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    comments = st.text_area("Comments")

    if st.button("Submit"):
        entry_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "EntryID": entry_id,
            "Timestamp": timestamp,
            "Product": product,
            **values,
            "Comments": comments
        }
        ws_history.append_row(list(record.values()))
        st.success(f"Saved! EntryID: {entry_id}")
        st.rerun()

    df = get_recent_entries(ws_history, product)
    if not df.empty:
        st.subheader("Recent Entries")
        st.dataframe(df, use_container_width=True, hide_index=True)

# ------------------ Main App ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    try:
        client = get_gs_client()
        sh = open_spreadsheet(client)
        ws_config, ws_history = ensure_worksheets(sh)
        
        st.sidebar.header("Navigation")
        mode = st.sidebar.radio("Mode", ["User", "Admin"])

        if mode == "Admin":
            pw = st.text_input("Admin Password", type="password")
            if pw == "admin123":
                admin_ui(ws_config)
            elif pw:
                st.info("Incorrect admin password")
        else:
            user_ui(ws_config, ws_history)

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()

