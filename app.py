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

# ------------------ Initialize Session State ------------------
if 'cfg' not in st.session_state:
    st.session_state.cfg = {}

# ------------------ Google Sheets ------------------
def get_gs_client():
    try:
        # Verify secrets exist
        if 'gcp_service_account' not in st.secrets:
            st.error("Google Service Account credentials not found in secrets.")
            st.stop()
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
        # Create credentials from secrets
        creds_dict = {
            "type": st.secrets["gcp_service_account"]["type"],
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"].replace('\\n', '\n'),
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
            "token_uri": st.secrets["gcp_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"]
        }
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
        
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {str(e)}")
        st.stop()

def open_spreadsheet(client):
    name = st.secrets["gsheet"]["spreadsheet_name"]
    return client.open(name)

def ensure_worksheets(sh):
    # History sheet only (removed config sheet)
    try:
        ws_history = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title="History", rows=2000, cols=50)
        headers = ["EntryID", "Timestamp", "Product", "Comments"] + DEFAULT_SUBTOPICS
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)
    return ws_history

# ------------------ History helpers ------------------
def ensure_history_headers(ws_history, product):
    # Get current subtopics for the product
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS)
    headers = ws_history.row_values(1)
    needed_headers = ["EntryID", "Timestamp", "Product", "Comments"] + current_subtopics
    
    # Update headers if needed
    if set(headers) != set(needed_headers):
        ws_history.update("A1", [needed_headers])
        ws_history.freeze(rows=1)
    return needed_headers

def append_history(ws_history, record: dict):
    headers = ensure_history_headers(ws_history, record["Product"])
    row = [record.get(h, "") for h in headers]
    ws_history.append_row(row, value_input_option="USER_ENTERED")

def get_recent_entries(ws_history, product: str, limit: int = 50) -> pd.DataFrame:
    values = ws_history.get_all_records()
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    if "Product" in df.columns:
        df = df[df["Product"] == product]
    return df.sort_values(by="Timestamp", ascending=False).head(limit)

# ------------------ Admin UI ------------------
def admin_ui():
    st.subheader("Admin • Manage Products & Subtopics")

    # Create new product
    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in st.session_state.cfg:
                st.warning("That product already exists.")
            else:
                st.session_state.cfg[new_product] = DEFAULT_SUBTOPICS.copy()
                st.success(f"Product '{new_product}' created with default subtopics.")
                st.rerun()

    # Edit existing product
    if st.session_state.cfg:
        with st.expander("Edit Product"):
            prod = st.selectbox("Select Product", sorted(st.session_state.cfg.keys()))
            st.caption("Current subtopics:")
            st.write(st.session_state.cfg[prod])

            # Add new subtopic
            new_sub = st.text_input("Add Subtopic")
            if st.button("Add Subtopic to Product"):
                if new_sub.strip():
                    st.session_state.cfg[prod].append(new_sub.strip())
                    st.success(f"Added '{new_sub}' to {prod}.")
                    st.rerun()

            # Remove subtopics
            subs_to_remove = st.multiselect("Remove subtopics", st.session_state.cfg[prod])
            if st.button("Remove Selected Subtopics"):
                if subs_to_remove:
                    st.session_state.cfg[prod] = [s for s in st.session_state.cfg[prod] if s not in subs_to_remove]
                    st.warning(f"Removed: {', '.join(subs_to_remove)}")
                    st.rerun()

        # Delete product
        with st.expander("Delete Product"):
            prod_del = st.selectbox("Choose product to delete", sorted(st.session_state.cfg.keys()))
            if st.button("Delete Product Permanently"):
                del st.session_state.cfg[prod_del]
                st.error(f"Deleted product '{prod_del}' and its subtopics.")
                st.rerun()

    st.divider()
    st.subheader("Current Products Configuration")
    st.json(st.session_state.cfg)

# ------------------ User UI ------------------
def user_ui(ws_history):
    st.subheader("User • Enter Data")
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Main Product", sorted(st.session_state.cfg.keys()))
    if not product:
        return

    # Get current subtopics for the selected product
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS)
    
    st.write("Fill **all fields** below:")
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
        append_history(ws_history, record)
        st.success(f"Saved! EntryID: {entry_id}")
        st.rerun()

    # Display recent entries
    df = get_recent_entries(ws_history, product)
    if not df.empty:
        st.subheader("Recent Entries (for this product)")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No entries yet.")

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    client = get_gs_client()
    sh = open_spreadsheet(client)
    ws_history = ensure_worksheets(sh)

    st.sidebar.header("Navigation")
    mode = st.sidebar.radio("Mode", ["User", "Admin"])

    if mode == "Admin":
        pw = st.text_input("Admin Password", type="password")
        if pw == "admin123":
            admin_ui()
        else:
            st.info("Enter the correct admin password to manage templates.")
    else:
        user_ui(ws_history)

if __name__ == "__main__":
    main()

