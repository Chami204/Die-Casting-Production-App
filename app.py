import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ----------------- Settings -----------------
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

# ----------------- Google Sheets Auth -----------------
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
    name = st.secrets["gsheet"]["FlowApp_Data"]
    return client.open(name)

def ensure_worksheets(sh):
    try:
        ws_config = sh.worksheet("Config")
    except gspread.WorksheetNotFound:
        ws_config = sh.add_worksheet(title="Config", rows=100, cols=2)
        ws_config.update("A1", [["Product", "Subtopic"]])
        ws_config.freeze(rows=1)

    try:
        ws_history = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title="History", rows=2000, cols=50)
        ws_history.update("A1", [["EntryID", "Timestamp", "Product", "Comments"] + FIXED_SUBTOPICS])
        ws_history.freeze(rows=1)

    return ws_config, ws_history

# ----------------- Config helpers -----------------
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

def write_config(ws_config, cfg):
    rows = [["Product", "Subtopic"]]
    for product, subs in cfg.items():
        for s in subs:
            rows.append([product, s])
    ws_config.clear()
    ws_config.update("A1", rows)
    ws_config.freeze(rows=1)

# ----------------- History helpers -----------------
def ensure_headers(ws_history, needed_headers):
    headers = ws_history.row_values(1)
    changed = False
    for h in needed_headers:
        if h not in headers:
            headers.append(h)
            changed = True
    if changed:
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)
    return headers

def append_history(ws_history, record):
    headers = ensure_headers(ws_history, list(record.keys()))
    row = [record.get(h, "") for h in headers]
    ws_history.append_row(row, value_input_option="USER_ENTERED")

def get_recent_entries(ws_history, product, limit=50):
    values = ws_history.get_all_records()
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    if "Product" in df.columns:
        df = df[df["Product"] == product]
    df = df.sort_values(by="Timestamp", ascending=False).head(limit)
    return df

def delete_by_entry_id(ws_history, entry_id):
    try:
        cell = ws_history.find(entry_id)
        ws_history.delete_rows(cell.row)
        return True
    except Exception:
        return False

# ----------------- Admin UI -----------------
def admin_ui(cfg, ws_config):
    st.subheader("Admin • Manage Products")

    # Create new product
    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in cfg:
                st.warning("Product already exists.")
            else:
                # Add product with fixed subtopics
                cfg[new_product] = FIXED_SUBTOPICS.copy()
                write_config(ws_config, cfg)
                st.success(f"Product '{new_product}' created with default subtopics.")

    # Edit subtopics for existing product
    if cfg:
        with st.expander("Edit Existing Product Subtopics"):
            prod = st.selectbox("Select Product", sorted(cfg.keys()))
            st.caption("Current subtopics:")
            st.write(cfg[prod])

            # Add new subtopic
            new_sub = st.text_input("Add a Subtopic")
            if st.button("Add Subtopic"):
                if new_sub.strip() and new_sub not in cfg[prod]:
                    cfg[prod].append(new_sub.strip())
                    write_config(ws_config, cfg)
                    st.success(f"Added subtopic '{new_sub}' to {prod}")
                else:
                    st.warning("Enter a valid subtopic that is not already in the list.")

            # Remove subtopics
            subs_to_remove = st.multiselect("Remove Subtopics", cfg[prod])
            if st.button("Remove Selected"):
                if subs_to_remove:
                    cfg[prod] = [s for s in cfg[prod] if s not in subs_to_remove]
                    write_config(ws_config, cfg)
                    st.warning(f"Removed subtopics: {', '.join(subs_to_remove)}")

# ----------------- User UI -----------------
def user_ui(cfg, ws_history):
    st.subheader("User • Enter Data")
    if not cfg:
        st.info("No products available. Admin needs to create one first.")
        return

    product = st.selectbox("Select Main Product", sorted(cfg.keys()))
    if not product:
        return

    st.write("Fill values for all subtopics:")
    values = {}
    for sub in cfg[product]:
        values[sub] = st.text_input(sub)

    comments = st.text_area("Comments")

    if st.button("Submit"):
        entry_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime(TIME_FORMAT)
        record = {"EntryID": entry_id, "Timestamp": timestamp, "Product": product, "Comments": comments, **values}
        append_history(ws_history, record)
        st.success(f"Saved! EntryID: {entry_id}")

    st.divider()
    st.subheader("Recent Entries")
    df = get_recent_entries(ws_history, product, limit=30)
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
        ids = df["EntryID"].tolist()
        del_id = st.selectbox("Select EntryID to delete", ids)
        if st.button("Delete Selected Entry"):
            ok = delete_by_entry_id(ws_history, del_id)
            if ok:
                st.warning(f"Deleted entry {del_id}. Refresh to see changes.")

# ----------------- Main -----------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    client = get_gs_client()
    sh = open_spreadsheet(client)
    ws_config, ws_history = ensure_worksheets(sh)

    cfg = read_config(ws_config)

    st.sidebar.header("Navigation")
    mode = st.sidebar.radio("Mode", ["User", "Admin"])

    if mode == "Admin":
        pw = st.text_input("Admin Password", type="password")
        if pw == st.secrets["security"]["admin_password"]:
            admin_ui(cfg, ws_config)
        else:
            st.info("admin_password")
    else:
        user_ui(cfg, ws_history)

if __name__ == "__main__":
    main()

