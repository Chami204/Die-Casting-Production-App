import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz
import time
from functools import wraps

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
    "Approved Qty"
]

DEFAULT_DOWNTIME_REASONS = [
    "TAM - TRAPPED Al IN THE MOULD",
    "MOH - MOULD OVER HEAT",
    "SRR - SPRAY ROBBOT REPAIR",
    "TWT - TOTAL WORKED TIME(Mins)",
    "PM - PLANNED MAINTENANCE",
    "SRA - SET UP ROBBOT ARM",
    "MA - MOULD ASSEMBLE",
    "RAR - ROBBOT ARM REPAIR",
    "PC - POWER CUT",
    "MB - MACHINE BREAKDOWN",
    "PI - PLANING ISSUE",
    "FC - FURNACE CLEANING",
    "PTC - PLUNGER TOP CHANGE",
    "MS - MOULD SETUP",
    "D - DINING",
    "ERE - EXTRACTOR ROBOT ERROR",
    "SSR - SHOT SLEEVE REPLACE",
    "SC - STOCK COUNT",
    "PHF - PRE-HEATING FURNACE",
    "UC - UNSAFE CONDITION",
    "LLG - LACK OF LPG GAS",
    "PTS - PLUNGER TOP STUCK",
    "LRR - LADLER ROBBOT REPAIR",
    "UF - UNLOADING FURNACE",
    "PS - PLANT SHUTDOWN",
    "MTR - MOULD TEST RUN",
    "ASR - ADJUST THE SPRAY ROBBOT",
    "MAC - MACHINE CLEANING",
    "EPD - EJECTOR PIN DAMAGED",
    "MC - MOULD CHANGE",
    "TDT - TOTAL DOWN TIME",
    "SRB - SPRAY ROBBOT BREAKDOWN",
    "LOO - LACK OF OPERATORS",
    "NRA - NO RECORDS AVAILABLE",
    "MR - MOULD REPAIR",
    "MD - MOULD DAMAGE",
    "FF - FILLING THE FURNACE",
    "T - TRAINING",
    "GHD - GAS HOSE DAMAGE",
    "EF - ELECTRICAL FAULT",
    "LFT - LOW FURNACE TEMPERATURE",
    "SS - SHIFT STARTING",
    "SF - SHIFT FININSHING",
    "SCS - SCRAPS SHORTAGE",
    "MH - MOULD HEATING",
    "UM - UNPLANNED MAINTENANCE",
    "FRB - FURNACE RELATED BREAKDOWN",
    "CSR - COOLING SYSTEM REPAIR",
    "GOS - GEAR OIL OUT OF STOCK",
    "LOS - LUBRICANT OUT OF STOCK",
    "MCC - MOULD CLEANING",
    "PLE - PLUNGER TOP LUBRICANT ERROR",
    "FU - FURNACE UNLOADING",
    "MRS - MOULD RE-SET UP",
    "MCE - MOULD CLAMP ERROR",
    "PSC - PLUNGER SLEEVE CLEANING"
]

DEFAULT_PROCESS_STEPS = [
    "Casting",
    "Inspection",
    "Testing",
    "Final QC",
    "Packaging"
]

DEFAULT_USER_CREDENTIALS = {
    "Team A": "123",
    "Team B": "1234",
    "Team C": "12345"
}

QUALITY_PASSWORD = "quality123"

# ------------------ Initialize Session State ------------------
if 'cfg' not in st.session_state:
    st.session_state.cfg = {}
if 'last_config_update' not in st.session_state:
    st.session_state.last_config_update = None
if 'production_password_entered' not in st.session_state:
    st.session_state.production_password_entered = False
if 'quality_password_entered' not in st.session_state:
    st.session_state.quality_password_entered = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'gs_client' not in st.session_state:
    st.session_state.gs_client = None
if 'spreadsheet' not in st.session_state:
    st.session_state.spreadsheet = None
if 'downtime_reasons' not in st.session_state:
    st.session_state.downtime_reasons = DEFAULT_DOWNTIME_REASONS.copy()
if 'process_steps' not in st.session_state:
    st.session_state.process_steps = DEFAULT_PROCESS_STEPS.copy()
if 'user_credentials' not in st.session_state:
    st.session_state.user_credentials = DEFAULT_USER_CREDENTIALS.copy()
if 'pending_records' not in st.session_state:
    st.session_state.pending_records = {"production": [], "downtime": [], "quality": []}
if 'api_available' not in st.session_state:
    st.session_state.api_available = True

# ------------------ Helper Functions ------------------

def get_sri_lanka_time():
    """Get current time in Sri Lanka timezone"""
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 60

# ------------------ Safe API Call Wrapper ------------------
def safe_api_call(func, *args, **kwargs):
    try:
        if not st.session_state.api_available:
            return None
        result = func(*args, **kwargs)
        st.session_state.api_available = True
        return result
    except Exception as e:
        if "quota" in str(e).lower() or "429" in str(e):
            st.session_state.api_available = False
            st.warning("Google Sheets API quota exceeded. Some functionalities may be limited.")
            return None
        else:
            st.error(f"API Error: {str(e)}")
            return None

# ------------------ Google Sheets Setup ------------------
@st.cache_resource(show_spinner=False)
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
        }

        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {str(e)}")
        return None

@st.cache_resource(show_spinner=False)
def open_spreadsheet(_client):
    try:
        name = st.secrets["gsheet"]["spreadsheet_name"]
        return safe_api_call(_client.open, name)
    except Exception as e:
        st.error(f"Error opening spreadsheet: {str(e)}")
        return None

def get_worksheet(sheet_name):
    if not st.session_state.api_available or not st.session_state.spreadsheet:
        return None
    try:
        return safe_api_call(st.session_state.spreadsheet.worksheet, sheet_name)
    except Exception as e:
        st.error(f"Worksheet error: {str(e)}")
        return None

# ------------------ Read Config and Settings ------------------

@st.cache_data(ttl=300, show_spinner=False)
def read_config(ws_config):
    try:
        if not ws_config or not st.session_state.api_available:
            return st.session_state.cfg

        values = safe_api_call(ws_config.get_all_values)
        if values and len(values) > 1:
            headers = values[0]
            data = values[1:]
            cfg = {}
            for row in data:
                if len(row) >= 2:
                    p = str(row[0]).strip()
                    s = str(row[1]).strip()
                    if p and s:
                        cfg.setdefault(p, []).append(s)
            st.session_state.cfg = cfg
            return cfg
        return st.session_state.cfg
    except Exception as e:
        st.error(f"Error reading config: {str(e)}")
        return st.session_state.cfg

@st.cache_data(ttl=300, show_spinner=False)
def read_user_credentials(ws_credentials):
    try:
        if not ws_credentials or not st.session_state.api_available:
            return st.session_state.user_credentials

        values = safe_api_call(ws_credentials.get_all_values)
        if values and len(values) > 1:
            credentials = {}
            for row in values[1:]:
                if len(row) >= 2:
                    username = str(row[0]).strip()
                    password = str(row[1]).strip()
                    if username and password:
                        credentials[username] = password
            st.session_state.user_credentials = credentials
            return credentials
        return st.session_state.user_credentials
    except Exception as e:
        st.error(f"Error reading user credentials: {str(e)}")
        return st.session_state.user_credentials

@st.cache_data(ttl=300, show_spinner=False)
def read_downtime_reasons(ws_reasons):
    try:
        if not ws_reasons or not st.session_state.api_available:
            return st.session_state.downtime_reasons

        values = safe_api_call(ws_reasons.get_all_values)
        if values and len(values) > 1:
            reasons = [str(row[0]).strip() for row in values[1:] if row and str(row[0]).strip()]
            if reasons:
                st.session_state.downtime_reasons = reasons
                return reasons
        return st.session_state.downtime_reasons
    except Exception as e:
        st.error(f"Error reading downtime reasons: {str(e)}")
        return st.session_state.downtime_reasons

@st.cache_data(ttl=300, show_spinner=False)
def read_process_steps(ws_steps):
    try:
        if not ws_steps or not st.session_state.api_available:
            return st.session_state.process_steps

        values = safe_api_call(ws_steps.get_all_values)
        if values and len(values) > 1:
            steps = [str(row[0]).strip() for row in values[1:] if row and str(row[0]).strip()]
            if steps:
                st.session_state.process_steps = steps
                return steps
        return st.session_state.process_steps
    except Exception as e:
        st.error(f"Error reading process steps: {str(e)}")
        return st.session_state.process_steps

def refresh_config_if_needed(ws_config, ws_credentials, ws_reasons, ws_steps):
    if should_refresh_config():
        new_cfg = read_config(ws_config)
        new_credentials = read_user_credentials(ws_credentials)
        new_reasons = read_downtime_reasons(ws_reasons)
        new_steps = read_process_steps(ws_steps)
        st.session_state.last_config_update = datetime.now()

# ------------------ Append Records ONLY to Google Sheets ------------------

def append_record(ws, record):
    if not ws or not st.session_state.api_available:
        st.error("Cannot save record: API unavailable or worksheet missing.")
        return False
    try:
        headers = safe_api_call(ws.row_values, 1)
        if headers:
            row = [record.get(h, "") for h in headers]
            success = safe_api_call(ws.append_row, row, value_input_option="USER_ENTERED")
            return success is not None
        return False
    except Exception as e:
        st.error(f"Error saving record: {str(e)}")
        return False

def append_production_record(ws_production, record):
    return append_record(ws_production, record)

def append_downtime_record(ws_downtime, record):
    return append_record(ws_downtime, record)

def append_quality_record(ws_quality, record):
    return append_record(ws_quality, record)

# ------------------ Admin UI - No editing, only info and refresh ------------------

def admin_ui(ws_config, ws_credentials, ws_reasons, ws_steps):
    st.subheader("Admin Management Panel")
    
    if not st.session_state.api_available:
        st.warning("⚠️ Google Sheets API unavailable. Some functionalities may be limited.")
    
    st.info("Admin data editing is now **only available** via the Excel (Google Sheets) file directly.")
    st.write("Please edit Products, User Credentials, Downtime Reasons, and Process Steps in the Excel file.")
    
    if st.button("🔄 Refresh Configuration from Excel"):
        refresh_config_if_needed(ws_config, ws_credentials, ws_reasons, ws_steps)
        st.success("Configuration refreshed from Excel.")
        st.experimental_rerun()
    
    # Show current config info
    st.subheader("Current Products & Subtopics")
    st.json(st.session_state.cfg)
    
    st.subheader("Current User Credentials")
    st.json(st.session_state.user_credentials)
    
    st.subheader("Current Downtime Reasons")
    st.write(st.session_state.downtime_reasons)
    
    st.subheader("Current Process Steps")
    st.write(st.session_state.process_steps)

# ------------------ Main UI and Main ------------------

# Other UI functions like production_records_ui, downtime_records_ui, quality_records_ui
# remain similar but no changes needed for the storage logic except they depend on above append_* functions.

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    
    # Initialize Google Sheets client only once
    if st.session_state.gs_client is None:
        with st.spinner("Connecting to Google Sheets..."):
            st.session_state.gs_client = get_gs_client()
            if st.session_state.gs_client:
                st.session_state.spreadsheet = open_spreadsheet(st.session_state.gs_client)
    
    # Get worksheets
    ws_config = get_worksheet("Config") if st.session_state.spreadsheet else None
    ws_production = get_worksheet("Production_Quality_Records") if st.session_state.spreadsheet else None
    ws_downtime = get_worksheet("Machine_Downtime_Records") if st.session_state.spreadsheet else None
    ws_quality = get_worksheet("Quality_Records") if st.session_state.spreadsheet else None
    ws_credentials = get_worksheet("User_Credentials") if st.session_state.spreadsheet else None
    ws_reasons = get_worksheet("Downtime_Reasons") if st.session_state.spreadsheet else None
    ws_steps = get_worksheet("Process_Steps") if st.session_state.spreadsheet else None
    
    # Load config and settings from Google Sheets
    if not st.session_state.cfg:
        st.session_state.cfg = read_config(ws_config)
    if not st.session_state.user_credentials:
        st.session_state.user_credentials = read_user_credentials(ws_credentials)
    if not st.session_state.downtime_reasons:
        st.session_state.downtime_reasons = read_downtime_reasons(ws_reasons)
    if not st.session_state.process_steps:
        st.session_state.process_steps = read_process_steps(ws_steps)
    st.session_state.last_config_update = datetime.now()
    
    st.sidebar.header("Admin Access")
    is_admin = st.sidebar.checkbox("Admin Mode", key="admin_mode")
    
    if is_admin:
        pw = st.sidebar.text_input("Admin Password", type="password", key="admin_pw")
        if pw == "admin123":
            admin_ui(ws_config, ws_credentials, ws_reasons, ws_steps)
        elif pw:
            st.sidebar.warning("Incorrect admin password")
        else:
            # Show normal UI if password not entered
            # Call main UI functions (production, downtime, quality) here
            # For brevity, just info shown here
            st.info("Enter admin password to access admin panel.")
    else:
        # Show normal UI (production, downtime, quality) here
        # For brevity, just info shown here
        st.info("Select a section to proceed.")
        # The actual UI like production_records_ui can be called here

if __name__ == "__main__":
    main()
