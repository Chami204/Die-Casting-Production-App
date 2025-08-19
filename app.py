import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')
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
if 'last_config_update' not in st.session_state:
    st.session_state.last_config_update = None

# ------------------ Helper Functions ------------------
def get_sri_lanka_time():
    """Get current time in Sri Lanka timezone"""
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    """Check if config should be refreshed (every 5 seconds)"""
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 5

# ------------------ Google Sheets ------------------
def get_gs_client():
    try:
        if 'gcp_service_account' not in st.secrets:
            st.error("Google Service Account credentials not found in secrets.")
            st.stop()
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
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
        headers = ["EntryID", "Timestamp", "Product", "Comments"] + DEFAULT_SUBTOPICS
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)

    return ws_config, ws_history

# ------------------ Config helpers ------------------
def read_config(ws_config):
    try:
        values = ws_config.get_all_records()
        cfg = {}
        for row in values:
            p = str(row.get("Product", "")).strip()
            s = str(row.get("Subtopic", "")).strip()
            if not p or not s:
                continue
            cfg.setdefault(p, []).append(s)
        return cfg
    except Exception as e:
        st.error(f"Error reading config: {str(e)}")
        return {}

def write_config(ws_config, cfg: dict):
    try:
        rows = [["Product", "Subtopic"]]
        for product, subs in cfg.items():
            for s in subs:
                rows.append([product, s])
        ws_config.clear()
        ws_config.update("A1", rows)
        ws_config.freeze(rows=1)
        return True
    except Exception as e:
        st.error(f"Error writing config: {str(e)}")
        return False

def refresh_config_if_needed(ws_config):
    """Refresh config from Google Sheets if needed"""
    if should_refresh_config():
        new_cfg = read_config(ws_config)
        if new_cfg != st.session_state.cfg:
            st.session_state.cfg = new_cfg
        st.session_state.last_config_update = datetime.now()

# ------------------ History helpers ------------------
def ensure_history_headers(ws_history, product):
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS.copy())
    headers = ws_history.row_values(1)
    needed_headers = ["EntryID", "Timestamp", "Product", "Comments"] + current_subtopics
    
    if set(headers) != set(needed_headers):
        ws_history.update("A1", [needed_headers])
        ws_history.freeze(rows=1)
    return needed_headers

def append_history(ws_history, record: dict):
    headers = ensure_history_headers(ws_history, record["Product"])
    row = [record.get(h, "") for h in headers]
    ws_history.append_row(row, value_input_option="USER_ENTERED")

def get_recent_entries(ws_history, product: str, limit: int = 50) -> pd.DataFrame:
    try:
        values = ws_history.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        if "Product" in df.columns:
            df = df[df["Product"] == product]
        return df.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        return pd.DataFrame()

# ------------------ Admin UI ------------------
def admin_ui(ws_config):
    st.subheader("Manage Products & Subtopics")
    
    # Auto-refresh config to see changes from other devices
    refresh_config_if_needed(ws_config)

    # Create new product
    with st.expander("Create New Product"):
        new_product = st.text_input("New Product Name", key="new_product")
        if st.button("Create Product"):
            if not new_product.strip():
                st.warning("Enter a valid product name.")
            elif new_product in st.session_state.cfg:
                st.warning("That product already exists.")
            else:
                st.session_state.cfg[new_product] = DEFAULT_SUBTOPICS.copy()
                if write_config(ws_config, st.session_state.cfg):
                    st.success(f"Product '{new_product}' created with default subtopics.")
                    st.rerun()

    # Edit existing product
    if st.session_state.cfg:
        with st.expander("Edit Product"):
            prod = st.selectbox("Select Product", sorted(st.session_state.cfg.keys()), key="edit_product")
            st.caption("Current subtopics:")
            st.write(st.session_state.cfg[prod])

            # Add new subtopic
            new_sub = st.text_input("Add Subtopic", key="new_subtopic")
            if st.button("Add Subtopic to Product"):
                if new_sub.strip():
                    st.session_state.cfg[prod].append(new_sub.strip())
                    if write_config(ws_config, st.session_state.cfg):
                        st.success(f"Added '{new_sub}' to {prod}.")
                        st.rerun()

            # Remove subtopics
            subs_to_remove = st.multiselect("Remove subtopics", st.session_state.cfg[prod], key="remove_subtopics")
            if st.button("Remove Selected Subtopics"):
                if subs_to_remove:
                    st.session_state.cfg[prod] = [s for s in st.session_state.cfg[prod] if s not in subs_to_remove]
                    if write_config(ws_config, st.session_state.cfg):
                        st.warning(f"Removed: {', '.join(subs_to_remove)}")
                        st.rerun()

        # Delete product
        with st.expander("Delete Product"):
            prod_del = st.selectbox("Choose product to delete", sorted(st.session_state.cfg.keys()), key="delete_product")
            if st.button("Delete Product Permanently"):
                del st.session_state.cfg[prod_del]
                if write_config(ws_config, st.session_state.cfg):
                    st.error(f"Deleted product '{prod_del}' and its subtopics.")
                    st.rerun()

    st.divider()
    st.subheader("Current Products Configuration")
    st.json(st.session_state.cfg)
    
    # Manual refresh button
    if st.button("🔄 Refresh Configuration"):
        st.session_state.last_config_update = None
        st.rerun()

# ------------------ User UI ------------------
def user_ui(ws_config, ws_history):
    st.subheader("Enter Data")
    
    # Manual refresh button
    if st.button("🔄 Refresh Data"):
        st.rerun()

    # Auto-refresh config to get latest changes from admin
    refresh_config_if_needed(ws_config)
    
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Main Product", sorted(st.session_state.cfg.keys()), key="user_product")
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS.copy())
    
    st.write("Fill **all fields** below:")
    values = {}
    
    # Generate dynamic form fields
    for subtopic in current_subtopics:
        if "number" in subtopic.lower() or "num" in subtopic.lower() or "rejects" in subtopic.lower():
            values[subtopic] = st.number_input(subtopic, min_value=0, step=1, key=f"num_{subtopic}")
        elif "time" in subtopic.lower():
            values[subtopic] = st.text_input(subtopic, value=get_sri_lanka_time(), key=f"time_{subtopic}")
        else:
            values[subtopic] = st.text_input(subtopic, key=f"text_{subtopic}")
    
    comments = st.text_area("Comments", key="comments")

    if st.button("Submit", key="submit_btn"):
        # Validate required numeric fields
        required_fields = [st for st in current_subtopics if "number" in st.lower() or "num" in st.lower()]
        missing_fields = [f for f in required_fields if not values.get(f, 0)]
        
        if missing_fields:
            st.error(f"Please fill in all required fields: {', '.join(missing_fields)}")
        else:
            try:
                entry_id = uuid.uuid4().hex
                record = {
                    "EntryID": entry_id,
                    "Timestamp": get_sri_lanka_time(),
                    "Product": product,
                    **values,
                    "Comments": comments
                }
                append_history(ws_history, record)
                st.success(f"Saved! EntryID: {entry_id}")
            except Exception as e:
                st.error(f"Error saving data: {str(e)}")

    # Display recent entries
    df = get_recent_entries(ws_history, product)
    if not df.empty:
        st.subheader("Recent Entries (for this product)")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No entries yet for this product.")
    

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    try:
        client = get_gs_client()
        sh = open_spreadsheet(client)
        ws_config, ws_history = ensure_worksheets(sh)
        
        # Read config from Google Sheets at startup
        if not st.session_state.cfg:
            st.session_state.cfg = read_config(ws_config)
            st.session_state.last_config_update = datetime.now()

        st.sidebar.header("Navigation")
        mode = st.sidebar.radio("Mode", ["User", "Admin"], key="mode_selector")

        if mode == "Admin":
            pw = st.text_input("Admin Password", type="password", key="admin_pw")
            if pw == "admin123":
                admin_ui(ws_config)
            elif pw:
                st.warning("Incorrect admin password")
        else:
            user_ui(ws_config, ws_history)

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()

