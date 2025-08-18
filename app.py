import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production App"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
FIXED_SUBTOPICS = [
    "Input number of pcs",
    "Input time",
    "Output number of pcs",
    "Output time",
    "Num of pcs to rework",
    "Number of rejects"
]

# ------------------ Google Sheets ------------------
def get_gs_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    return gspread.authorize(creds)

def open_spreadsheet(client):
    return client.open("FlowApp_Data")

def ensure_worksheets(sh):
    # Config sheet
    try:
        ws_config = sh.worksheet("Config")
    except gspread.WorksheetNotFound:
        ws_config = sh.add_worksheet(title="Config", rows=100, cols=2)
        ws_config.update("A1", [["Product", "Subtopic"]])
        ws_config.freeze(rows=1)
    # History sheet
    try:
        ws_history = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title="History", rows=2000, cols=50)
        ws_history.update("A1", [["EntryID","Timestamp","Product"]+FIXED_SUBTOPICS+["Comments"]])
        ws_history.freeze(rows=1)
    return ws_config, ws_history

# ------------------ Config helpers ------------------
def read_config(ws_config) -> dict:
    values = ws_config.get_all_records()
    cfg = {}
    for row in values:
        p = str(row.get("Product","")).strip()
        s = str(row.get("Subtopic","")).strip()
        if not p: continue
        cfg.setdefault(p, FIXED_SUBTOPICS.copy())
    return cfg

def write_config(ws_config, cfg: dict):
    rows = [["Product","Subtopic"]]
    for product in cfg:
        for s in FIXED_SUBTOPICS:
            rows.append([product,s])
    ws_config.clear()
    ws_config.update("A1", rows)
    ws_config.freeze(rows=1)

# ------------------ History helpers ------------------
def get_headers(ws_history):
    headers = ws_history.row_values(1)
    return headers if headers else ["EntryID","Timestamp","Product"]+FIXED_SUBTOPICS+["Comments"]

def ensure_headers(ws_history, needed_headers):
    headers = get_headers(ws_history)
    changed = False
    for h in needed_headers:
        if h not in headers:
            headers.append(h)
            changed = True
    if changed:
        ws_history.update("A1",[headers])
        ws_history.freeze(rows=1)
    return headers

def append_history(ws_history, record: dict):
    headers = ensure_headers(ws_history, list(record.keys()))
    row = [record.get(h,"") for h in headers]
    ws_history.append_row(row, value_input_option="USER_ENTERED")

def get_recent_entries(ws_history, product: str, limit:int=50):
    try:
        values = ws_history.get_all_records()
    except:
        return pd.DataFrame()
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    if "Product" in df.columns:
        df = df[df["Product"]==product]
    return df.sort_values(by="Timestamp", ascending=False).head(limit)

def delete_by_entry_id(ws_history, entry_id:str):
    try:
        cell = ws_history.find(entry_id)
        ws_history.delete_rows(cell.row)
        return True
    except:
        return False

# ------------------ Admin UI ------------------
def admin_ui(cfg, ws_config, ws_history):
    st.subheader("Admin • Manage Products & Subtopics")

    # Create new product
    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in cfg:
                st.warning("Product already exists.")
            else:
                cfg[new_product] = FIXED_SUBTOPICS.copy()
                write_config(ws_config, cfg)
                st.success(f"Product '{new_product}' created.")

    # Delete product
    if cfg:
        with st.expander("Delete Product"):
            prod_del = st.selectbox("Choose product to delete", sorted(cfg.keys()))
            if st.button("Delete Permanently"):
                del cfg[prod_del]
                write_config(ws_config, cfg)
                st.warning(f"Deleted product '{prod_del}'")

    # Reorder subtopics
    st.subheader("Reorder Subtopics")
    for product in cfg:
        st.write(f"Product: {product}")
        current_order = cfg[product]
        reordered = st.multiselect("Drag to reorder", options=current_order, default=current_order, key=product)
        if st.button(f"Save New Order for {product}", key=f"save_{product}"):
            if set(reordered)!=set(FIXED_SUBTOPICS):
                st.error("Include all subtopics in new order!")
            else:
                # Update headers in history
                headers = ["EntryID","Timestamp","Product"] + reordered + ["Comments"]
                ws_history.update("A1",[headers])
                ws_history.freeze(rows=1)
                st.success(f"Updated order for {product}")

    st.divider()
    st.subheader("Current Flowchart Templates")
    st.json(cfg)

# ------------------ User UI ------------------
def user_ui(cfg, ws_history):
    st.subheader("User • Enter Data")
    if not cfg:
        st.info("No products available. Admin must create products.")
        return

    product = st.selectbox("Select Main Product", sorted(cfg.keys()))
    if not product: return

    values = {}
    for sub in cfg[product]:
        # Automatically track time for Input/Output
        if "Input time" in sub or "Output time" in sub:
            values[sub] = datetime.now().strftime(TIME_FORMAT)
            st.text(f"{sub}: {values[sub]}")
        else:
            values[sub] = st.text_input(sub)

    comments = st.text_area("Comments")

    if st.button("Submit"):
        entry_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime(TIME_FORMAT)
        record = {"EntryID": entry_id, "Timestamp": timestamp, "Product": product, "Comments": comments}
        record.update(values)
        append_history(ws_history, record)
        st.success(f"Saved! EntryID: {entry_id}")

    st.divider()
    st.subheader("Recent Entries")
    df = get_recent_entries(ws_history, product)
    if df.empty:
        st.caption("No entries yet.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        ids = df["EntryID"].tolist()
        del_id = st.selectbox("Select EntryID to delete", ids)
        if st.button("Delete Selected Entry"):
            if delete_by_entry_id(ws_history, del_id):
                st.warning(f"Deleted entry {del_id}")
            else:
                st.error("Could not delete entry")

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    client = get_gs_client()
    sh = open_spreadsheet(client)
    ws_config, ws_history = ensure_worksheets(sh)

    cfg = read_config(ws_config)

    st.sidebar.header("Navigation")
    mode = st.sidebar.radio("Mode", ["User","Admin"])
    if mode=="Admin":
        pw = st.text_input("Admin Password", type="password")
        if pw=="admin123":
            admin_ui(cfg, ws_config, ws_history)
        else:
            st.info("Enter correct admin password")
    else:
        user_ui(cfg, ws_history)

if __name__=="__main__":
    main()
