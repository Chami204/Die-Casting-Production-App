import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz
import time
import threading
from functools import lru_cache
import json

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
# Quality section password
QUALITY_PASSWORD = "quality123"

# Quality default fields
QUALITY_DEFAULT_FIELDS = [
    "Total_Lot_Qty",
    "Sample_Size", 
    "AQL_Level",
    "Accept_Reject",
    "Results",
    "Quality_Inspector",
    "EPF_Number",
    "Digital_Signature"
]
# Downtime section password
DOWNTIME_PASSWORD = "downtime123"

# Downtime default fields
DOWNTIME_DEFAULT_FIELDS = [
    "Machine",
    "Shift",
    "Team", 
    "Planned_Item",
    "Breakdown_Reason",
    "Duration_Mins"
]

# ------------------ Local Storage Helpers ------------------
def save_to_local_storage(data_type, data):
    """Save data to browser's local storage"""
    try:
        key = f"die_casting_{data_type}"
        json_data = json.dumps(data)
        st.session_state[key] = json_data
    except Exception as e:
        st.error(f"Error saving to local storage: {str(e)}")

def load_from_local_storage(data_type, default=None):
    """Load data from browser's local storage"""
    try:
        key = f"die_casting_{data_type}"
        if key in st.session_state:
            loaded_data = st.session_state[key]
            # Check if it's a JSON string and parse it
            if isinstance(loaded_data, str):
                return json.loads(loaded_data)
            else:
                return loaded_data
    except Exception as e:
        st.error(f"Error loading from local storage: {str(e)}")
    return default if default is not None else []

def clear_local_storage(data_type):
    """Clear data from local storage"""
    try:
        key = f"die_casting_{data_type}"
        if key in st.session_state:
            del st.session_state[key]
    except:
        pass

# ------------------ Initialize Session State ------------------
if 'cfg' not in st.session_state:
    st.session_state.cfg = {}
if 'last_config_update' not in st.session_state:
    st.session_state.last_config_update = None
if 'editing_entry' not in st.session_state:
    st.session_state.editing_entry = None
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = ""
if 'sheet_initialized' not in st.session_state:
    st.session_state.sheet_initialized = False

# Initialize local data from storage
if 'die_casting_production' not in st.session_state:
    st.session_state.die_casting_production = load_from_local_storage('production', [])
if 'die_casting_quality' not in st.session_state:
    st.session_state.die_casting_quality = load_from_local_storage('quality', [])
if 'die_casting_downtime' not in st.session_state:
    st.session_state.die_casting_downtime = load_from_local_storage('downtime', [])
if 'die_casting_pending_sync' not in st.session_state:
    st.session_state.die_casting_pending_sync = load_from_local_storage('pending_sync', False)

# ------------------ Helper Functions ------------------
def get_sri_lanka_time():
    """Get current time in Sri Lanka timezone"""
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    """Check if config should be refreshed with longer interval"""
    if st.session_state.last_config_update is None:
        return True
    # Increased to 2 minutes to reduce API calls
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 120

# ------------------ Google Sheets ------------------
def get_gs_client():
    try:
        if 'gcp_service_account' not in st.secrets:
            st.error("Google Service Account credentials not found in secrets.")
            return None
            
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
        ]
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {str(e)}")
        return None

def initialize_google_sheets():
    """Initialize Google Sheets connection only when needed"""
    if st.session_state.sheet_initialized:
        return True
        
    try:
        client = get_gs_client()
        if client is None:
            return False
            
        name = st.secrets["gsheet"]["spreadsheet_name"]
        sh = client.open(name)
        
        # Try to access a sheet to test connection
        try:
            sh.worksheet("Production_Config")
            st.session_state.sheet_initialized = True
            return True
        except:
            st.warning("Google Sheets not fully accessible. Working in offline mode.")
            return False
    except Exception as e:
        st.warning(f"Google Sheets connection issue: {str(e)}. Working in offline mode.")
        return False

def read_downtime_config():
    """Read downtime configuration from Google Sheets"""
    try:
        if initialize_google_sheets():
            client = get_gs_client()
            name = st.secrets["gsheet"]["spreadsheet_name"]
            sh = client.open(name)
            ws_downtime_config = sh.worksheet("Downtime_Config")
            
            values = ws_downtime_config.get_all_records()
            machines = []
            breakdown_reasons = []
            
            for row in values:
                machine = str(row.get("Machine", "")).strip()
                reason = str(row.get("Breakdown_Reason", "")).strip()
                
                if machine:
                    machines.append(machine)
                if reason:
                    breakdown_reasons.append(reason)
            
            return {
                "machines": list(set(machines)),
                "breakdown_reasons": list(set(breakdown_reasons))
            }
    except Exception as e:
        st.warning(f"Could not load downtime config: {str(e)}")
    
    # Return default values if cannot connect
    return {
        "machines": ["Machine 1", "Machine 2", "Machine 3"],
        "breakdown_reasons": ["Electrical Fault", "Mechanical Failure", "Maintenance", "Material Issue"]
    }

def ensure_google_sheets():
    """Ensure all required Google Sheets exist"""
    try:
        client = get_gs_client()
        if client is None:
            return False
            
        name = st.secrets["gsheet"]["spreadsheet_name"]
        sh = client.open(name)
        
        # List of sheets to ensure exist
        sheets_to_create = [
            ("Production_Config", [["Product", "Subtopic"]]),
            ("Quality_Config", [["Field", "Type"]]),
            ("Downtime_Config", [["Machine", "Breakdown_Reason"]]),
            ("User_Credentials", [["Username", "Password", "Role"]]),
            ("History", [["User", "EntryID", "Timestamp", "Product", "Comments"] + DEFAULT_SUBTOPICS]),
            ("Quality_History", [["User", "EntryID", "Timestamp", "Product"] + QUALITY_DEFAULT_FIELDS]),
            ("Downtime_History", [["User", "EntryID", "Timestamp"] + DOWNTIME_DEFAULT_FIELDS + ["Comments"]])
        ]
        
        for sheet_name, headers in sheets_to_create:
            try:
                sh.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
                worksheet.update("A1", headers)
                worksheet.freeze(rows=1)
                time.sleep(1)  # Delay between sheet creations
        
        return True
        
    except Exception as e:
        st.warning(f"Could not ensure Google Sheets: {str(e)}")
        return False

# ------------------ Config helpers ------------------
def get_default_config():
    """Return default configuration for offline use"""
    return {
        "Product1": DEFAULT_SUBTOPICS.copy(),
        "Product2": DEFAULT_SUBTOPICS.copy()
    }

def refresh_config_if_needed():
    """Refresh config from Google Sheets if needed and available"""
    if should_refresh_config() and initialize_google_sheets():
        try:
            client = get_gs_client()
            if client:
                name = st.secrets["gsheet"]["spreadsheet_name"]
                sh = client.open(name)
                ws_config = sh.worksheet("Production_Config")
                
                values = ws_config.get_all_records()
                cfg = {}
                for row in values:
                    p = str(row.get("Product", "")).strip()
                    s = str(row.get("Subtopic", "")).strip()
                    if not p or not s:
                        continue
                    cfg.setdefault(p, []).append(s)
                
                if cfg:
                    st.session_state.cfg = cfg
                    st.session_state.last_config_update = datetime.now()
                    return True
        except Exception as e:
            # Silently fail - we'll use offline config
            pass
    
    # Ensure we always have some config
    if not st.session_state.cfg:
        st.session_state.cfg = get_default_config()
    
    return False

# ------------------ Local Data Management ------------------
def save_to_local(data_type, record):
    """Save data to local storage"""
    try:
        # Ensure record is a dictionary
        if not isinstance(record, dict):
            st.error("Invalid record format")
            return
            
        # Get current data - ensure it's always a list
        key = f"die_casting_{data_type}"
        current_data = st.session_state.get(key, [])
        
        # Make sure current_data is a list, not a string
        if not isinstance(current_data, list):
            current_data = []
        
        # Add new record
        current_data.append(record)
        
        # Save back to session state and local storage
        st.session_state[key] = current_data
        save_to_local_storage(data_type, current_data)
        
        # Mark as pending sync
        st.session_state.die_casting_pending_sync = True
        save_to_local_storage('pending_sync', True)
        
    except Exception as e:
        st.error(f"Error saving data locally: {str(e)}")

def sync_with_google_sheets():
    """Sync local data with Google Sheets when connection is available"""
    if not st.session_state.get('die_casting_pending_sync', False):
        st.info("No data pending sync")
        return
    
    if not initialize_google_sheets():
        st.warning("Cannot connect to Google Sheets")
        return
        
    try:
        client = get_gs_client()
        if client is None:
            return
            
        name = st.secrets["gsheet"]["spreadsheet_name"]
        sh = client.open(name)
        
        # Sync production data
        sync_count = 0
        production_data = st.session_state.get('die_casting_production', [])
        if production_data:
            try:
                ws_history = sh.worksheet("History")
                for record in production_data:
                    headers = ["User", "EntryID", "Timestamp", "Product", "Comments"] + st.session_state.cfg.get(record["Product"], DEFAULT_SUBTOPICS.copy())
                    row = [record.get(h, "") for h in headers]
                    ws_history.append_row(row, value_input_option="USER_ENTERED")
                    sync_count += 1
                    time.sleep(1)  # Delay between writes
            except Exception as e:
                st.error(f"Error syncing production data: {str(e)}")
        
        # Sync quality data
        quality_data = st.session_state.get('die_casting_quality', [])
        if quality_data:
            try:
                ws_quality_history = sh.worksheet("Quality_History")
                for record in quality_data:
                    headers = ["User", "EntryID", "Timestamp", "Product"] + QUALITY_DEFAULT_FIELDS
                    row = [record.get(h, "") for h in headers]
                    ws_quality_history.append_row(row, value_input_option="USER_ENTERED")
                    sync_count += 1
                    time.sleep(1)  # Delay between writes
            except Exception as e:
                st.error(f"Error syncing quality data: {str(e)}")
        
        # Sync downtime data
        downtime_data = st.session_state.get('die_casting_downtime', [])
        if downtime_data:
            try:
                ws_downtime_history = sh.worksheet("Downtime_History")
                for record in downtime_data:
                    headers = ["User", "EntryID", "Timestamp"] + DOWNTIME_DEFAULT_FIELDS + ["Comments"]
                    row = [record.get(h, "") for h in headers]
                    ws_downtime_history.append_row(row, value_input_option="USER_ENTERED")
                    sync_count += 1
                    time.sleep(1)  # Delay between writes
            except Exception as e:
                st.error(f"Error syncing downtime data: {str(e)}")
        
        if sync_count > 0:
            # Clear synced data from local storage
            st.session_state.die_casting_production = []
            st.session_state.die_casting_quality = []
            st.session_state.die_casting_downtime = []
            st.session_state.die_casting_pending_sync = False
            
            # Clear from browser storage
            clear_local_storage('production')
            clear_local_storage('quality')
            clear_local_storage('downtime')
            clear_local_storage('pending_sync')
            
            st.success(f"Successfully synced {sync_count} records with Google Sheets!")
            
            # Also refresh config after sync
            st.session_state.last_config_update = None
            refresh_config_if_needed()
        else:
            st.info("No data needed syncing")
        
    except Exception as e:
        st.warning(f"Sync failed: {str(e)}. Data remains saved locally.")

# ------------------ Login System ------------------
def login_system():
    st.sidebar.header("Login")
    
    if st.session_state.logged_in:
        st.sidebar.success(f"Logged in as: {st.session_state.current_user}")
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.current_user = None
            st.session_state.user_role = ""
            st.rerun()
        return True
    
    # Read users from sheet for production login
    users = {}
    try:
        if initialize_google_sheets():
            client = get_gs_client()
            if client:
                name = st.secrets["gsheet"]["spreadsheet_name"]
                sh = client.open(name)
                ws_users = sh.worksheet("User_Credentials")
                user_records = ws_users.get_all_records()
                
                for row in user_records:
                    username = str(row.get("Username", "")).strip()
                    password = str(row.get("Password", "")).strip()
                    role = str(row.get("Role", "")).strip()
                    if username and password:
                        users[username] = {
                            "password": password,
                            "role": role
                        }
    except Exception as e:
        st.sidebar.warning("Could not load user list from Google Sheets")
    
    # Regular user login section - CHANGED TO DROPDOWN
    st.sidebar.subheader("Production Login")
    
    if users:
        username = st.sidebar.selectbox("Select User", options=[""] + list(users.keys()), key="prod_username")
        password = st.sidebar.text_input("Password", type="password", key="prod_password")
        
        if st.sidebar.button("Production Login"):
            if username in users and users[username]["password"] == password:
                st.session_state.logged_in = True
                st.session_state.current_user = username
                st.session_state.user_role = users[username].get("role", "Production")
                st.sidebar.success("Login successful!")
                st.rerun()
            else:
                st.sidebar.error("Invalid username or password")
    else:
        username = st.sidebar.text_input("Username", key="prod_username")
        password = st.sidebar.text_input("Password", type="password", key="prod_password")
        
        if st.sidebar.button("Production Login"):
            if username and password:
                st.session_state.logged_in = True
                st.session_state.current_user = username
                st.session_state.user_role = "Production"
                st.sidebar.success("Login successful!")
                st.rerun()
            else:
                st.sidebar.error("Please enter username and password")
    
    # Downtime login section
    st.sidebar.subheader("Downtime Login")
    downtime_username = st.sidebar.text_input("Downtime Username", key="downtime_username")
    downtime_password = st.sidebar.text_input("Downtime Password", type="password", key="downtime_password")
    
    if st.sidebar.button("Downtime Login"):
        if downtime_password == DOWNTIME_PASSWORD and downtime_username:
            st.session_state.logged_in = True
            st.session_state.current_user = downtime_username
            st.session_state.user_role = "Downtime"
            st.sidebar.success("Downtime login successful!")
            st.rerun()
        else:
            st.sidebar.error("Invalid downtime credentials")
    
    # Quality login section
    st.sidebar.subheader("Quality Login")
    quality_username = st.sidebar.text_input("Quality Username", key="quality_username")
    quality_password = st.sidebar.text_input("Quality Password", type="password", key="quality_password")
    
    if st.sidebar.button("Quality Login"):
        if quality_password == QUALITY_PASSWORD and quality_username:
            st.session_state.logged_in = True
            st.session_state.current_user = quality_username
            st.session_state.user_role = "Quality"
            st.sidebar.success("Quality login successful!")
            st.rerun()
        else:
            st.sidebar.error("Invalid quality credentials")
            
    return st.session_state.logged_in

# ------------------ Admin UI ------------------
def admin_ui():
    st.subheader("Admin Panel - Manage Products")
    
    refresh_config_if_needed()

    st.info("""
    **Offline Mode Active**
    - Product configuration changes should be made directly in Google Sheets
    - The app will sync when the connection is available
    - Current products are loaded from local cache
    """)
    
    # Display current configuration
    st.subheader("Current Products Configuration")
    
    if st.session_state.cfg:
        for product, subtopics in st.session_state.cfg.items():
            with st.expander(f"Product: {product}"):
                st.write("Subtopics:")
                for subtopic in subtopics:
                    st.write(f"- {subtopic}")
    else:
        st.info("No products configured yet.")

    # Manual refresh button with cooldown
    if st.button("🔄 Refresh Configuration from Google Sheets"):
        st.session_state.last_config_update = None
        if refresh_config_if_needed():
            st.success("Configuration refreshed from Google Sheets!")
        else:
            st.warning("Could not connect to Google Sheets")
        st.rerun()

# ------------------ Production UI ------------------
def production_ui():
    st.subheader(f"Production Data Entry - User: {st.session_state.current_user}")
    
    # Refresh button at the top
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("")  # Spacer
    with col2:
        if st.button("🔄 Refresh Products", key="prod_refresh_btn"):
            st.session_state.last_config_update = None
            if refresh_config_if_needed():
                st.success("Products refreshed from Google Sheets!")
            else:
                st.warning("Using local product cache")
            st.rerun()
    
    refresh_config_if_needed()
    
    if not st.session_state.cfg:
        st.info("No products available yet.")
        return

    product = st.selectbox("Select Product", sorted(st.session_state.cfg.keys()), key="user_product")
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
                    "User": st.session_state.current_user,
                    "EntryID": entry_id,
                    "Timestamp": get_sri_lanka_time(),
                    "Product": product,
                    **values,
                    "Comments": comments
                }
                save_to_local('production', record)
                st.success(f"Saved locally! EntryID: {entry_id}")
                
                # Try to sync in background
                if st.button("🔄 Sync with Google Sheets Now"):
                    sync_with_google_sheets()
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Error saving data: {str(e)}")

    # Display local entries
    production_data = st.session_state.get('die_casting_production', [])
    if production_data:
        st.subheader("Local Entries (Pending Sync)")
        try:
            # Convert to list of dictionaries first
            data_for_df = []
            for record in production_data:
                if isinstance(record, dict):
                    data_for_df.append(record)
            
            if data_for_df:
                local_df = pd.DataFrame(data_for_df)
                display_cols = ["User", "Timestamp", "Product"]
                available_cols = [col for col in display_cols if col in local_df.columns]
                if available_cols:
                    st.dataframe(local_df[available_cols].head(10))
                else:
                    st.info("No displayable data available")
            else:
                st.info("No valid production data available")
        except Exception as e:
            st.error(f"Error displaying data: {str(e)}")

# ------------------ Quality UI ------------------
def quality_ui():
    st.subheader(f"Quality Data Entry - Inspector: {st.session_state.current_user}")
    
    # Refresh button at the top
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("")  # Spacer
    with col2:
        if st.button("🔄 Refresh Products", key="quality_refresh_btn"):
            st.session_state.last_config_update = None
            if refresh_config_if_needed():
                st.success("Products refreshed from Google Sheets!")
            else:
                st.warning("Using local product cache")
            st.rerun()
    
    refresh_config_if_needed()
    
    # Read available products from production config
    available_products = list(st.session_state.cfg.keys())
    
    if not available_products:
        st.error("No products available.")
        return
    
    st.write("Fill all quality inspection details below:")
    
    # Product selection
    product = st.selectbox("Select Product", options=available_products, key="quality_product")
    
    # Quality fields
    values = {}
    
    col1, col2 = st.columns(2)
    
    with col1:
        values["Total_Lot_Qty"] = st.number_input("Total Lot Qty", min_value=1, step=1, key="total_lot_qty")
        values["Sample_Size"] = st.number_input("Sample Size", min_value=1, step=1, key="sample_size")
        values["AQL_Level"] = st.text_input("AQL Level", key="aql_level")
        values["Accept_Reject"] = st.selectbox("Accept/Reject", options=["Accept", "Reject"], key="accept_reject")
    
    with col2:
        values["Results"] = st.text_input("Results", key="results")
        values["Quality_Inspector"] = st.text_input("Quality Inspector", value=st.session_state.current_user, key="quality_inspector")
        values["EPF_Number"] = st.text_input("EPF Number", key="epf_number")
        
        # Digital Signature
        st.write("Digital Signature:")
        signature = st.text_input("Type your signature", key="digital_signature")
        values["Digital_Signature"] = signature
    
    comments = st.text_area("Additional Comments", key="quality_comments")
    
    if st.button("Submit Quality Data", key="submit_quality_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "User": st.session_state.current_user,
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "Product": product,
                **values,
                "Comments": comments
            }
            
            save_to_local('quality', record)
            st.success(f"Quality data saved locally! Entry ID: {entry_id}")
            
            # Try to sync in background
            if st.button("🔄 Sync Quality Data with Google Sheets Now"):
                sync_with_google_sheets()
                st.rerun()
                
        except Exception as e:
            st.error(f"Error saving quality data: {str(e)}")
    
    # Display local quality entries
    quality_data = st.session_state.get('die_casting_quality', [])
    if quality_data:
        st.subheader("Local Quality Entries (Pending Sync)")
        try:
            # Convert to list of dictionaries first
            data_for_df = []
            for record in quality_data:
                if isinstance(record, dict):
                    data_for_df.append(record)
            
            if data_for_df:
                local_df = pd.DataFrame(data_for_df)
                display_cols = ["User", "Timestamp", "Product", "Total_Lot_Qty", "Sample_Size", 
                               "AQL_Level", "Accept_Reject", "Results"]
                available_cols = [col for col in display_cols if col in local_df.columns]
                if available_cols:
                    st.dataframe(local_df[available_cols].head(10))
                else:
                    st.info("No displayable quality data available")
            else:
                st.info("No valid quality data available")
        except Exception as e:
            st.error(f"Error displaying quality data: {str(e)}")

# ------------------ Downtime UI ------------------
def downtime_ui():
    st.subheader(f"Machine Downtime Entry - Technician: {st.session_state.current_user}")
    
    # Refresh button at the top
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("")  # Spacer
    with col2:
        if st.button("🔄 Refresh Data", key="downtime_refresh_btn"):
            st.session_state.last_config_update = None
            if refresh_config_if_needed():
                st.success("Data refreshed from Google Sheets!")
            else:
                st.warning("Using local data cache")
            st.rerun()
    
    refresh_config_if_needed()
    
    # Read downtime configuration
    downtime_config = read_downtime_config()
    machines = downtime_config["machines"]
    breakdown_reasons = downtime_config["breakdown_reasons"]
    
    # Read available products from production config
    available_products = list(st.session_state.cfg.keys())
    
    if not available_products:
        st.error("No products available. Please ask admin to add products first.")
        return
    
    st.write("Fill all machine downtime details below:")
    
    # Current time and date
    current_time = get_sri_lanka_time()
    st.write(f"**Current Time (Sri Lanka):** {current_time}")
    
    # Downtime fields
    values = {}
    
    col1, col2 = st.columns(2)
    
    with col1:
        values["Machine"] = st.selectbox("Machine", options=machines, key="downtime_machine")
        values["Shift"] = st.selectbox("Shift", options=["Night", "Day"], key="downtime_shift")
        values["Team"] = st.selectbox("Team", options=["A", "B", "C"], key="downtime_team")
    
    with col2:
        values["Planned_Item"] = st.selectbox("Planned Item", options=available_products, key="downtime_planned_item")
        values["Breakdown_Reason"] = st.selectbox("Breakdown Reason", options=breakdown_reasons, key="downtime_reason")
        values["Duration_Mins"] = st.number_input("Duration (Minutes)", min_value=1, step=1, key="downtime_duration")
    
    comments = st.text_area("Additional Comments", key="downtime_comments")
    
    if st.button("Submit Downtime Data", key="submit_downtime_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "User": st.session_state.current_user,
                "EntryID": entry_id,
                "Timestamp": current_time,
                **values,
                "Comments": comments
            }
            
            save_to_local('downtime', record)
            st.success(f"Downtime data saved locally! Entry ID: {entry_id}")
            
            # Try to sync in background
            if st.button("🔄 Sync Downtime Data Now"):
                sync_with_google_sheets()
                st.rerun()
                
        except Exception as e:
            st.error(f"Error saving downtime data: {str(e)}")
    
    # Display local downtime entries
    downtime_data = st.session_state.get('die_casting_downtime', [])
    if downtime_data:
        st.subheader("Local Downtime Entries (Pending Sync)")
        try:
            # Convert to list of dictionaries first
            data_for_df = []
            for record in downtime_data:
                if isinstance(record, dict):
                    data_for_df.append(record)
            
            if data_for_df:
                local_df = pd.DataFrame(data_for_df)
                display_cols = ["User", "Timestamp", "Machine", "Shift", "Breakdown_Reason", "Duration_Mins"]
                available_cols = [col for col in display_cols if col in local_df.columns]
                if available_cols:
                    st.dataframe(local_df[available_cols].head(10))
                else:
                    st.info("No displayable downtime data available")
            else:
                st.info("No valid downtime data available")
        except Exception as e:
            st.error(f"Error displaying downtime data: {str(e)}")
            
# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    # Show sync status
    if st.session_state.get('die_casting_pending_sync', False):
        st.warning("⚠️ Data pending sync with Google Sheets")
        if st.button("🔄 Try to Sync Now"):
            sync_with_google_sheets()
            st.rerun()

    try:
        # Initialize with default config if empty
        if not st.session_state.cfg:
            st.session_state.cfg = get_default_config()

        # Login system
        if not login_system():
            st.info("Please login to access the system")
            return

        # Navigation based on user role
        if st.session_state.user_role == "Admin":
            admin_ui()
        elif st.session_state.user_role == "Production":
            production_ui()
        elif st.session_state.user_role == "Quality":
            quality_ui()
        elif st.session_state.user_role == "Downtime":
            downtime_ui()
        else:
            # Default to production if role not specified
            production_ui()

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()
