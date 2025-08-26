import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz
import time
import cachetools

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')
DEFAULT_SUBTOPICS = [
    "Target Quantity(Planned Shot Count - per Shift and Machine )",
    "Input time",
    "Actual Qty(Actual Shot Count - per shift and Machine)",
    "Slow shot Count (Trial shots during production)",
    "Reject Qty(Reject Point 01 - During production )",
    "Approved Qty",
    "Output time"
]

# ------------------ Cache Setup ------------------
# Use TTLCache to cache data for 30 seconds
cache = cachetools.TTLCache(maxsize=100, ttl=30)

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
if 'gs_client' not in st.session_state:
    st.session_state.gs_client = None
if 'spreadsheet' not in st.session_state:
    st.session_state.spreadsheet = None
if 'worksheets' not in st.session_state:
    st.session_state.worksheets = {}

# ------------------ Helper Functions ------------------
def get_sri_lanka_time():
    """Get current time in Sri Lanka timezone"""
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    """Check if config should be refreshed (every 30 seconds)"""
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 30

# ------------------ Cached Google Sheets Functions ------------------
@st.cache_resource(show_spinner=False)
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

@st.cache_resource(show_spinner=False)
def open_spreadsheet(_client):
    try:
        name = st.secrets["gsheet"]["spreadsheet_name"]
        return _client.open(name)
    except Exception as e:
        st.error(f"Error opening spreadsheet: {str(e)}")
        st.stop()

def get_worksheet(sheet_name):
    """Get worksheet with caching"""
    cache_key = f"worksheet_{sheet_name}"
    if cache_key in cache:
        return cache[cache_key]
    
    try:
        worksheet = st.session_state.spreadsheet.worksheet(sheet_name)
        cache[cache_key] = worksheet
        return worksheet
    except gspread.WorksheetNotFound:
        # Create worksheet if it doesn't exist
        if sheet_name == "Config":
            worksheet = st.session_state.spreadsheet.add_worksheet(title="Config", rows=1000, cols=2)
            rows = [["Product", "Subtopic"]]
            worksheet.update("A1", rows)
            worksheet.freeze(rows=1)
        elif sheet_name == "Production_Quality_Records":
            worksheet = st.session_state.spreadsheet.add_worksheet(title="Production_Quality_Records", rows=2000, cols=50)
            headers = ["RecordType", "EntryID", "Timestamp", "Shift", "Team", "Machine", "Product", "Comments"] + DEFAULT_SUBTOPICS
            worksheet.update("A1", [headers])
            worksheet.freeze(rows=1)
        elif sheet_name == "Machine_Downtime_Records":
            worksheet = st.session_state.spreadsheet.add_worksheet(title="Machine_Downtime_Records", rows=2000, cols=20)
            headers = ["EntryID", "Timestamp", "Shift", "Team", "Machine", "Planned_Item", "Downtime_Reason", "Other_Comments", "Duration_Min"]
            worksheet.update("A1", [headers])
            worksheet.freeze(rows=1)
        
        cache[cache_key] = worksheet
        return worksheet

# ------------------ Optimized Config helpers ------------------
@st.cache_data(ttl=30, show_spinner=False)
def read_config_cached(_ws_config):
    try:
        values = _ws_config.get_all_records()
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

def read_config(ws_config):
    return read_config_cached(ws_config)

def write_config(ws_config, cfg: dict):
    try:
        rows = [["Product", "Subtopic"]]
        for product, subs in cfg.items():
            for s in subs:
                rows.append([product, s])
        ws_config.clear()
        ws_config.update("A1", rows)
        ws_config.freeze(rows=1)
        
        # Clear cache after update
        cache.clear()
        st.cache_data.clear()
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

# ------------------ Optimized History helpers ------------------
@st.cache_data(ttl=15, show_spinner=False)
def get_recent_production_entries_cached(_ws_production, product: str, limit: int = 20):
    try:
        # Only read necessary columns for better performance
        values = _ws_production.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        if "Product" in df.columns:
            df = df[df["Product"] == product]
        return df.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        return pd.DataFrame()

@st.cache_data(ttl=15, show_spinner=False)
def get_recent_downtime_entries_cached(_ws_downtime, limit: int = 20):
    try:
        values = _ws_downtime.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        return df.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading downtime history: {str(e)}")
        return pd.DataFrame()

def get_recent_production_entries(ws_production, product: str, limit: int = 20):
    return get_recent_production_entries_cached(ws_production, product, limit)

def get_recent_downtime_entries(ws_downtime, limit: int = 20):
    return get_recent_downtime_entries_cached(ws_downtime, limit)

def append_production_record(ws_production, record: dict):
    try:
        headers = ws_production.row_values(1)
        row = [record.get(h, "") for h in headers]
        ws_production.append_row(row, value_input_option="USER_ENTERED")
        
        # Clear cache after new entry
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error saving production record: {str(e)}")
        return False

def append_downtime_record(ws_downtime, record: dict):
    try:
        headers = ws_downtime.row_values(1)
        row = [record.get(h, "") for h in headers]
        ws_downtime.append_row(row, value_input_option="USER_ENTERED")
        
        # Clear cache after new entry
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error saving downtime record: {str(e)}")
        return False

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
        st.cache_data.clear()
        cache.clear()
        st.rerun()

# ------------------ Production Records UI ------------------
def production_records_ui(ws_config, ws_production):
    st.subheader("Production Records")
    
    # Auto-refresh config to get latest changes from admin
    refresh_config_if_needed(ws_config)
    
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="production_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="production_team")
    with col3:
        machine = st.selectbox("Machine", ["M1", "M2"], key="production_machine")
    
    product = st.selectbox("Select Product", sorted(st.session_state.cfg.keys()), key="production_product")
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS.copy())
    
    st.write("Fill **all fields** below:")
    values = {}
    
    # Generate dynamic form fields
    for subtopic in current_subtopics:
        if "quantity" in subtopic.lower() or "qty" in subtopic.lower() or "count" in subtopic.lower():
            values[subtopic] = st.number_input(subtopic, min_value=0, step=1, key=f"num_{subtopic}")
        elif "time" in subtopic.lower():
            values[subtopic] = st.text_input(subtopic, value=get_sri_lanka_time(), key=f"time_{subtopic}")
        else:
            values[subtopic] = st.text_input(subtopic, key=f"text_{subtopic}")
    
    comments = st.text_area("Comments", key="production_comments")

    if st.button("Submit Production Record", key="submit_production_btn"):
        # Validate required numeric fields
        required_fields = [st for st in current_subtopics if "quantity" in st.lower() or "qty" in st.lower() or "count" in st.lower()]
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
                    "Machine": machine,
                    "Product": product,
                    **values,
                    "Comments": comments
                }
                if append_production_record(ws_production, record):
                    st.success(f"Production Record Saved! EntryID: {entry_id}")
            except Exception as e:
                st.error(f"Error saving data: {str(e)}")

    # Display recent production entries with a spinner
    with st.spinner("Loading recent entries..."):
        df = get_recent_production_entries(ws_production, product)
        if not df.empty:
            st.subheader("Recent Production Entries")
            st.dataframe(df, use_container_width=True)
        else:
            st.caption("No production entries yet for this product.")

# ------------------ Quality Records UI ------------------
def quality_records_ui(ws_config, ws_production):
    st.subheader("Quality Team Records")
    
    # Password protection
    if not st.session_state.quality_password_entered:
        pw = st.text_input("Quality Team Password", type="password", key="quality_pw")
        if st.button("Authenticate", key="quality_auth_btn"):
            if pw == "quality123":
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

    col1, col2, col3 = st.columns(3)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="quality_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="quality_team")
    with col3:
        machine = st.selectbox("Machine", ["M1", "M2"], key="quality_machine")
    
    product = st.selectbox("Select Item", sorted(st.session_state.cfg.keys()), key="quality_product")
    
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
                "Machine": machine,
                "Product": product,
                "Number of rejects": reject_count,
                "Comments": comments
            }
            if append_production_record(ws_production, record):
                st.success(f"Quality Record Saved! EntryID: {entry_id}")
        except Exception as e:
            st.error(f"Error saving data: {str(e)}")

    # Display recent quality entries with a spinner
    with st.spinner("Loading recent entries..."):
        df = get_recent_production_entries(ws_production, product)
        if not df.empty:
            df = df[df["RecordType"] == "Quality"]
            st.subheader("Recent Quality Entries")
            st.dataframe(df, use_container_width=True)
        else:
            st.caption("No quality entries yet for this product.")

# ------------------ Downtime Records UI ------------------
def downtime_records_ui(ws_downtime):
    st.subheader("Machine Downtime Records")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="downtime_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="downtime_team")
    with col3:
        machine = st.selectbox("Machine", ["M1", "M2"], key="downtime_machine")
    
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
                "Machine": machine,
                "Planned_Item": planned_item,
                "Downtime_Reason": downtime_reason,
                "Other_Comments": other_comments,
                "Duration_Min": duration_min
            }
            if append_downtime_record(ws_downtime, record):
                st.success(f"Downtime Record Saved! EntryID: {entry_id}")
        except Exception as e:
            st.error(f"Error saving data: {str(e)}")

    # Display recent downtime entries with a spinner
    with st.spinner("Loading recent entries..."):
        df = get_recent_downtime_entries(ws_downtime)
        if not df.empty:
            st.subheader("Recent Downtime Entries")
            st.dataframe(df, use_container_width=True)
        else:
            st.caption("No downtime entries yet.")

# ------------------ Main UI ------------------
def main_ui(ws_config, ws_production, ws_downtime):
    st.title(APP_TITLE)
    
    # Section selection
    st.sidebar.header("Navigation")
    section = st.sidebar.radio(
        "Select Section", 
        ["Production Records", "Machine Downtime Records", "Quality Team Records"],
        key="section_selector"
    )
    
    # Show current section in top right corner
    st.sidebar.markdown(f"**Current Mode:** {section}")
    
    # Display the selected section
    if section == "Production Records":
        production_records_ui(ws_config, ws_production)
    elif section == "Machine Downtime Records":
        downtime_records_ui(ws_downtime)
    elif section == "Quality Team Records":
        quality_records_ui(ws_config, ws_production)

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    
    # Initialize Google Sheets client only once
    if st.session_state.gs_client is None:
        with st.spinner("Connecting to Google Sheets..."):
            st.session_state.gs_client = get_gs_client()
            st.session_state.spreadsheet = open_spreadsheet(st.session_state.gs_client)
    
    try:
        # Get worksheets
        ws_config = get_worksheet("Config")
        ws_production = get_worksheet("Production_Quality_Records")
        ws_downtime = get_worksheet("Machine_Downtime_Records")
        
        # Read config from Google Sheets at startup
        if not st.session_state.cfg:
            st.session_state.cfg = read_config(ws_config)
            st.session_state.last_config_update = datetime.now()

        # Check if user is admin
        st.sidebar.header("Admin Access")
        is_admin = st.sidebar.checkbox("Admin Mode", key="admin_mode")
        
        if is_admin:
            pw = st.sidebar.text_input("Admin Password", type="password", key="admin_pw")
            if pw == "admin123":
                admin_ui(ws_config)
            elif pw:
                st.sidebar.warning("Incorrect admin password")
            else:
                main_ui(ws_config, ws_production, ws_downtime)
        else:
            main_ui(ws_config, ws_production, ws_downtime)

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()
