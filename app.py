import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ------------- Settings -------------
APP_TITLE = "Die Casting Production App"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # local display

# ------------- Google Sheets Auth -------------
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
    name = st.secrets["gsheet"]["spreadsheet_name"]
    return client.open(name)

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
        ws_history.update("A1", [["EntryID", "Timestamp", "Product", "Comments"]])
        ws_history.freeze(rows=1)

    return ws_config, ws_history

# ------------- Config helpers -------------
def read_config(ws_config) -> dict:
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

# ------------- History helpers -------------
FIXED_COLS = ["EntryID", "Timestamp", "Product", "Comments"]

def get_headers(ws_history):
    headers = ws_history.row_values(1)
    return headers if headers else FIXED_COLS[:]

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

# ------------- Flowchart preview (Admin) -------------
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

# ------------- Admin UI -------------
def admin_ui(cfg: dict, ws_config):
    st.subheader("Admin • Manage Products & Subtopics")

    # Create Product
    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in cfg:
                st.warning("Product already exists.")
            else:
                cfg[new_product] = []
                write_config(ws_config, cfg)
                st.success(f"Product '{new_product}' created.")

    # Edit Product
    if cfg:
        with st.expander("Edit Existing Product"):
            prod = st.selectbox("Select Product", sorted(cfg.keys()))
            st.caption("Current subtopics:")
            st.write(cfg[prod] if cfg[prod] else "— none —")

            col1, col2 = st.columns(2)
            with col1:
                new_sub = st.text_input("Add Subtopic")
                if st.button("Add Subtopic"):
                    if new_sub.strip():
                        cfg[prod].append(new_sub.strip())
                        write_config(ws_config, cfg)
                        st.success(f"Added '{new_sub}' to {prod}.")
                    else:
                        st.warning("Enter a valid subtopic.")

            with col2:
                subs_to_remove = st.multiselect("Remove subtopics", cfg[prod])
                if st.button("Remove Selected"):
                    if subs_to_remove:
                        cfg[prod] = [s for s in cfg[prod] if s not in subs_to_remove]
                        write_config(ws_config, cfg)
                        st.warning(f"Removed: {', '.join(subs_to_remove)}")
                    else:
                        st.info("Select items to remove.")

        with st.expander("Delete Product"):
            prod_del = st.selectbox("Choose product to delete", sorted(cfg.keys()))
            if st.button("Delete Product Permanently"):
                del cfg[prod_del]
                write_config(ws_config, cfg)
                st.error(f"Deleted product '{prod_del}'.")

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

# ------------- User UI -------------
def user_ui(cfg: dict, ws_history):
    st.subheader("User • Enter Data")
    if not cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Main Product", sorted(cfg.keys()))
    if not product:
        return

    st.write("Fill **all subtopics** below:")
    values = {}
    for sub in cfg[product]:
        values[sub] = st.text_input(sub)

    comments = st.text_area("Comments")

    if st.button("Submit"):
        entry_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime(TIME_FORMAT)

        record = {
            "EntryID": entry_id,
            "Timestamp": timestamp,
            "Product": product,
            "Comments": comments,
            **values
        }

        append_history(ws_history, record)
        st.success(f"Saved! EntryID: {entry_id}")

    st.divider()
    st.subheader("Recent Entries (for this product)")
    df = get_recent_entries(ws_history, product, limit=30)
    if df.empty:
        st.caption("No entries yet.")
        return

    st.dataframe(df, use_container_width=True, hide_index=True)

    ids = df["EntryID"].tolist() if "EntryID" in df.columns else []
    if ids:
        del_id = st.selectbox("Select EntryID to delete", ids)
        if st.button("Delete Selected Entry"):
            ok = delete_by_entry_id(ws_history, del_id)
            if ok:
                st.warning(f"Deleted entry {del_id}. Refresh to see changes.")
            else:
                st.error("Could not delete — please try again.")

# ------------- Main -------------
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
            st.info("Enter the correct admin password to manage templates.")
    else:
        user_ui(cfg, ws_history)

if __name__ == "__main__":
    main()

