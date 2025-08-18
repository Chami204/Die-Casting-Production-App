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

# ------------------ Google Sheets ------------------
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
    except gspread.SpreadsheetNotFound:
        st.error(f"Spreadsheet '{name}' not found. Please check the name in your secrets.")
        st.stop()
    except gspread.APIError as e:
        st.error(f"Google Sheets API error: {str(e)}")
        st.stop()
    except Exception as e:
        st.error(f"Error opening spreadsheet: {str(e)}")
        st.stop()


# ------------------ Config helpers ------------------
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

# ------------------ History helpers ------------------
FIXED_COLS = ["EntryID", "Timestamp", "Product", "Comments"]

def get_headers(ws_history):
    headers = ws_history.row_values(1)
    return headers if headers else FIXED_COLS + DEFAULT_SUBTOPICS

def ensure_headers(ws_history, needed_headers):
    headers = get_headers(ws_history)
    changed = False
    for h in needed_headers:
        if h not in headers:
            headers.append(h)
            changed = True
    if changed:
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)
    return headers

def append_history(ws_history, record: dict):
    headers = ensure_headers(ws_history, list(record.keys()))
    row = [record.get(h, "") for h in headers]
    ws_history.append_row(row, value_input_option="USER_ENTERED")

def get_recent_entries(ws_history, product: str, limit: int = 50) -> pd.DataFrame:
    values = ws_history.get_all_records()
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    if "Product" in df.columns:
        df = df[df["Product"] == product]
    df = df.sort_values(by="Timestamp", ascending=False).head(limit)
    return df

def delete_by_entry_id(ws_history, entry_id: str) -> bool:
    try:
        cell = ws_history.find(entry_id)
        ws_history.delete_rows(cell.row)
        return True
    except Exception:
        return False

# ------------------ Flowchart preview ------------------
def flowchart_dot(cfg: dict) -> str:
    lines = ['digraph G {', 'rankdir=LR;', 'node [shape=box, style=rounded];']
    for product, subs in cfg.items():
        p_id = product.replace(" ", "_")
        lines.append(f'"{p_id}" [label="{product}", shape=folder];')
        for s in subs:
            s_id = f'{p_id}_{s.replace(" ", "_")}'
            lines.append(f'"{s_id}" [label="{s}"];')
            lines.append(f'"{p_id}" -> "{s_id}";')
    lines.append("}")
    return "\n".join(lines)

# ------------------ Admin UI ------------------
def admin_ui(cfg: dict, ws_config):
    st.subheader("Manage Products & Subtopics")
    cfg = read_config(_ws_config)

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
                write_config(_ws_config, cfg)
                st.success(f"Product '{new_product}' created with default subtopics.")
                st.experimental_rerun()  # Force refresh

    # Edit existing product
    if cfg:
        with st.expander("Edit Product"):
            prod = st.selectbox("Select Product", sorted(cfg.keys()))
            st.caption("Current subtopics:")
            st.write(cfg[prod] if cfg[prod] else "— none —")

            # Add new subtopic
            new_sub = st.text_input("Add Subtopic")
            if st.button("Add Subtopic to Product"):
                if new_sub.strip():
                    cfg[prod].append(new_sub.strip())
                    write_config(_ws_config, cfg)
                    st.success(f"Added '{new_sub}' to {prod}.")
                    st.experimental_rerun()  # Force refresh

            # Remove subtopics
            subs_to_remove = st.multiselect("Remove subtopics", cfg[prod])
            if st.button("Remove Selected Subtopics"):
                if subs_to_remove:
                    cfg[prod] = [s for s in cfg[prod] if s not in subs_to_remove]
                    write_config(_ws_config, cfg)
                    st.warning(f"Removed: {', '.join(subs_to_remove)}")
                    st.experimental_rerun()  # Force refresh

        # Delete product
        with st.expander("Delete Product"):
            prod_del = st.selectbox("Choose product to delete", sorted(cfg.keys()))
            if st.button("Delete Product Permanently"):
                del cfg[prod_del]
                write_config(_ws_config, cfg)
                st.error(f"Deleted product '{prod_del}' and its subtopics.")
                st.experimental_rerun()  # Force refresh

    st.divider()
    st.subheader("Current Flowchart Templates")
    if cfg:
        st.json(cfg)
        try:
            st.graphviz_chart(flowchart_dot(cfg))
        except Exception:
            pass
    else:
        st.info("No products yet. Create one above.")

# ------------------ User UI ------------------
def user_ui(_ws_config, _ws_history):  # Changed parameter names to avoid confusion
    st.subheader("User • Enter Data")
    cfg = read_config(_ws_config)  # Read fresh config
    
    if not cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Main Product", sorted(cfg.keys()))
    if not product:
        return

    # Get current subtopics for the selected product
    current_subtopics = cfg.get(product, DEFAULT_SUBTOPICS)
    
    st.write("Fill **all fields** below:")
    values = {}
    comments = ""

    # Dynamic form based on current subtopics
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
        append_history(_ws_history, record)  # Use _ws_history parameter
        st.success(f"Saved! EntryID: {entry_id}")

    # Display recent entries - FIXED: using _ws_history instead of ws_history
    df = get_recent_entries(_ws_history, product)
    if not df.empty:
        st.subheader("Recent Entries (for this product)")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No entries yet.")

# ------------------ Main ------------------
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
            else:
                if pw:  # Only show message if password was entered
                    st.info("Enter the correct admin password to manage templates.")
        else:
            user_ui(ws_config, ws_history)

    except Exception as e:
        st.error(f"Application error: {str(e)}")
        st.stop()

if __name__ == "__main__":
    main()


