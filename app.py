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
if 'editing_entry' not in st.session_state:
    st.session_state.editing_entry = None
if 'current_section' not in st.session_state:
    st.session_state.current_section = "Production Records"
if 'quality_password_entered' not in st.session_state:
    st.session_state.quality_password_entered = False

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

    # Production & Quality sheet
    try:
        ws_production = sh.worksheet("Production_Quality_Records")
    except gspread.WorksheetNotFound:
        ws_production = sh.add_worksheet(title="Production_Quality_Records", rows=2000, cols=50)
        headers = ["RecordType", "EntryID", "Timestamp", "Shift", "Team", "Product", "Comments"] + DEFAULT_SUBTOPICS
        ws_production.update("A1", [headers])
        ws_production.freeze(rows=1)

    # Downtime sheet
    try:
        ws_downtime = sh.worksheet("Machine_Downtime_Records")
    except gspread.WorksheetNotFound:
        ws_downtime = sh.add_worksheet(title="Machine_Downtime_Records", rows=2000, cols=20)
        headers = ["EntryID", "Timestamp", "Shift", "Team", "Planned_Item", "Downtime_Reason", "Other_Comments", "Duration_Min"]
        ws_downtime.update("A1", [headers])
        ws_downtime.freeze(rows=1)

    return ws_config, ws_production, ws_downtime

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
def ensure_production_headers(ws_production, product):
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS.copy())
    headers = ws_production.row_values(1)
    needed_headers = ["RecordType", "EntryID", "Timestamp", "Shift", "Team", "Product", "Comments"] + current_subtopics
    
    if set(headers) != set(needed_headers):
        ws_production.update("A1", [needed_headers])
        ws_production.freeze(rows=1)
    return needed_headers

def append_production_record(ws_production, record: dict):
    headers = ensure_production_headers(ws_production, record["Product"])
    row = [record.get(h, "") for h in headers]
    ws_production.append_row(row, value_input_option="USER_ENTERED")

def append_downtime_record(ws_downtime, record: dict):
    headers = ws_downtime.row_values(1)
    row = [record.get(h, "") for h in headers]
    ws_downtime.append_row(row, value_input_option="USER_ENTERED")

def get_recent_production_entries(ws_production, product: str, limit: int = 50) -> pd.DataFrame:
    try:
        values = ws_production.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        if "Product" in df.columns:
            df = df[df["Product"] == product]
        return df.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        return pd.DataFrame()

def get_recent_downtime_entries(ws_downtime, limit: int = 50) -> pd.DataFrame:
    try:
        values = ws_downtime.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        return df.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading downtime history: {str(e)}")
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

# ------------------ Production Records UI ------------------
def production_records_ui(ws_config, ws_production):
    st.subheader("Production Records")
    
    # Auto-refresh config to get latest changes from admin
    refresh_config_if_needed(ws_config)
    
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    col1, col2 = st.columns(2)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="production_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="production_team")
    
    product = st.selectbox("Select Product", sorted(st.session_state.cfg.keys()), key="production_product")
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
    
    comments = st.text_area("Comments", key="production_comments")

    if st.button("Submit Production Record", key="submit_production_btn"):
        # Validate required numeric fields
        required_fields = [st for st in current_subtopics if "number" in st.lower() or "num" in st.lower()]
        missing_fields = [f for f in required_fields if not values.get(f, 0)]
        
        if missing_fields:
            st.error(f"Please fill in all required fields: {', '.join(missing_fields)}")
        else:
            try:
                entry_id = uuid.uuid4().hex
                record = {
                    "RecordType": "Production",
                    "EntryID": entry_id,
                    "Timestamp": get_sri_lanka_time(),
                    "Shift": shift,
                    "Team": team,
                    "Product": product,
                    **values,
                    "Comments": comments
                }
                append_production_record(ws_production, record)
                st.success(f"Production Record Saved! EntryID: {entry_id}")
            except Exception as e:
                st.error(f"Error saving data: {str(e)}")

    # Display recent production entries
    df = get_recent_production_entries(ws_production, product)
    if not df.empty:
        st.subheader("Recent Production Entries")
        st.dataframe(df)
    else:
        st.caption("No production entries yet for this product.")

# ------------------ Quality Records UI ------------------
def quality_records_ui(ws_config, ws_production):
    st.subheader("Quality Team Records")
    
    # Password protection
    if not st.session_state.quality_password_entered:
        pw = st.text_input("Quality Team Password", type="password", key="quality_pw")
        if st.button("Authenticate", key="quality_auth_btn"):
            if pw == "quality123":  # Default password, should be changed in production
                st.session_state.quality_password_entered = True
                st.rerun()
            else:
                st.error("Incorrect password")
        return
    
    st.success("Authenticated as Quality Team")
    if st.button("Logout", key="quality_logout_btn"):
        st.session_state.quality_password_entered = False
        st.rerun()
    
    # Auto-refresh config to get latest changes from admin
    refresh_config_if_needed(ws_config)
    
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Item", sorted(st.session_state.cfg.keys()), key="quality_product")
    
    col1, col2 = st.columns(2)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="quality_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="quality_team")
    
    reject_count = st.number_input(
        "Reject Point 02 – QC inspection after production by casting machines", 
        min_value=0, 
        step=1,
        key="reject_count"
    )
    
    comments = st.text_area("Comments", key="quality_comments")

    if st.button("Submit Quality Record", key="submit_quality_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "RecordType": "Quality",
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "Shift": shift,
                "Team": team,
                "Product": product,
                "Number of rejects": reject_count,
                "Comments": comments
            }
            append_production_record(ws_production, record)
            st.success(f"Quality Record Saved! EntryID: {entry_id}")
        except Exception as e:
            st.error(f"Error saving data: {str(e)}")

    # Display recent quality entries
    df = get_recent_production_entries(ws_production, product)
    if not df.empty:
        df = df[df["RecordType"] == "Quality"]
        st.subheader("Recent Quality Entries")
        st.dataframe(df)
    else:
        st.caption("No quality entries yet for this product.")

# ------------------ Downtime Records UI ------------------
def downtime_records_ui(ws_downtime):
    st.subheader("Machine Downtime Records")
    
    col1, col2 = st.columns(2)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="downtime_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="downtime_team")
    
    planned_item = st.text_input("Planned Item", key="planned_item")
    downtime_reason = st.selectbox(
        "Downtime Reason", 
        ["Mechanical Failure", "Electrical Issue", "Maintenance", "Material Shortage", "Other"],
        key="downtime_reason"
    )
    other_comments = st.text_area("Other Comments", key="downtime_comments")
    duration_min = st.number_input("Duration (Min)", min_value=1, step=1, key="duration_min")

    if st.button("Submit Downtime Record", key="submit_downtime_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "Shift": shift,
                "Team": team,
                "Planned_Item": planned_item,
                "Downtime_Reason": downtime_reason,
                "Other_Comments": other_comments,
                "Duration_Min": duration_min
            }
            append_downtime_record(ws_downtime, record)
            st.success(f"Downtime Record Saved! EntryID: {entry_id}")
        except Exception as e:
            st.error(f"Error saving data: {str(e)}")

    # Display recent downtime entries
    df = get_recent_downtime_entries(ws_downtime)
    if not df.empty:
        st.subheader("Recent Downtime Entries")
        st.dataframe(df)
    else:
        st.caption("No downtime entries yet.")

# ------------------ Main UI ------------------
def main_ui(ws_config, ws_production, ws_downtime):
    st.title(APP_TITLE)
    
    # Section selection
    st.sidebar.header("Navigation")
    section = st.sidebar.radio(
    "Select Section",
    ["Production Records", "Machine Downtime Records", "Quality Team Records"]
)
    elif section == "Machine Downtime Records":
        downtime_records_ui(ws_downtime)
    elif section == "Quality Team Records":
        quality_records_ui(ws_config, ws_production)


# ------------------ Run App ------------------
def run_app():
    try:
        ws_config, ws_production, ws_downtime = load_sheets()
        main_ui(ws_config, ws_production, ws_downtime)
    except Exception as e:
        st.error(f"An error occurred: {e}")


if __name__ == "__main__":
    run_app()
