import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz
import time
import cachetools
import json
from functools import wraps
import os
from pathlib import Path
import openpyxl

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

# Updated Default Downtime Reasons as requested
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
    "Inspection",
    "Testing",
    "Final QC",
    "Packaging",
    "Casting"
]

DEFAULT_USER_CREDENTIALS = {
    "Team A": "123",
    "Team B": "1234",
    "Team C": "12345"
}

# Quality section password
QUALITY_PASSWORD = "quality123"

# ------------------ Local Storage Settings ------------------
DESKTOP_PATH = Path("C:\Users\chami.gangoda\Downloads")
LOCAL_EXCEL_FILE = DESKTOP_PATH / "die_casting_production_data.xlsx"
LOCAL_BACKUP_INTERVAL = 300  # 5 minutes in seconds

# ------------------ Limits ------------------
MAX_USERS = 20  # Limited to 10 users

# ------------------ Cache Setup ------------------
cache = cachetools.TTLCache(maxsize=100, ttl=120)  # Increased TTL to reduce API calls

# ------------------ Initialize Session State ------------------
if 'cfg' not in st.session_state:
    st.session_state.cfg = {}
if 'last_config_update' not in st.session_state:
    st.session_state.last_config_update = None
if 'editing_entry' not in st.session_state:
    st.session_state.editing_entry = None
if 'current_section' not in st.session_state:
    st.session_state.current_section = "Production Records"
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
if 'signature_data' not in st.session_state:
    st.session_state.signature_data = None
if 'pending_records' not in st.session_state:
    st.session_state.pending_records = {"production": [], "downtime": [], "quality": []}
if 'api_available' not in st.session_state:
    st.session_state.api_available = True
if 'local_storage' not in st.session_state:
    st.session_state.local_storage = {
        "production": [],
        "downtime": [], 
        "quality": [],
        "config": {},
        "user_credentials": DEFAULT_USER_CREDENTIALS.copy(),
        "downtime_reasons": DEFAULT_DOWNTIME_REASONS.copy(),
        "process_steps": DEFAULT_PROCESS_STEPS.copy()
    }
if 'last_local_backup' not in st.session_state:
    st.session_state.last_local_backup = None

# ------------------ Helper Functions ------------------
def get_sri_lanka_time():
    """Get current time in Sri Lanka timezone"""
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    """Check if config should be refreshed (every 60 seconds)"""
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 60

def should_backup_to_local():
    """Check if local backup should be performed"""
    if st.session_state.last_local_backup is None:
        return True
    return (datetime.now() - st.session_state.last_local_backup).total_seconds() > LOCAL_BACKUP_INTERVAL

# ------------------ Local Excel File Operations ------------------
def init_local_excel_file():
    """Initialize the local Excel file with required sheets if it doesn't exist"""
    try:
        # Ensure directory exists
        DESKTOP_PATH.mkdir(parents=True, exist_ok=True)
        
        if not LOCAL_EXCEL_FILE.exists():
            # Create a new Excel file with all required sheets
            with pd.ExcelWriter(LOCAL_EXCEL_FILE, engine='openpyxl') as writer:
                # Production sheet
                production_df = pd.DataFrame(columns=[
                    "RecordType", "EntryID", "Timestamp", "Shift", "Team", "Machine", 
                    "Product", "Operator", "Comments"
                ] + DEFAULT_SUBTOPICS)
                production_df.to_excel(writer, sheet_name='Production_Records', index=False)
                
                # Downtime sheet
                downtime_df = pd.DataFrame(columns=[
                    "EntryID", "Timestamp", "Shift", "Team", "Machine", "Planned_Item", 
                    "Downtime_Reason", "Other_Comments", "Duration_Min"
                ])
                downtime_df.to_excel(writer, sheet_name='Downtime_Records', index=False)
                
                # Quality sheet
                quality_df = pd.DataFrame(columns=[
                    "EntryID", "Timestamp", "Process_Step", "Product", "Total_Lot_Qty", 
                    "Sample_Size", "AQL_Level", "Accept_Reject", "Defects_Found", 
                    "Results", "Quality_Inspector", "ETF_Number", "Digital_Signature", "Comments"
                ])
                quality_df.to_excel(writer, sheet_name='Quality_Records', index=False)
                
                # Config sheet
                config_df = pd.DataFrame(columns=["Product", "Subtopic"])
                config_df.to_excel(writer, sheet_name='Config', index=False)
                
                # User credentials sheet
                user_df = pd.DataFrame(columns=["Username", "Password", "Role"])
                user_df.to_excel(writer, sheet_name='User_Credentials', index=False)
                
                # Downtime reasons sheet
                reasons_df = pd.DataFrame(columns=["Reason"])
                reasons_df.to_excel(writer, sheet_name='Downtime_Reasons', index=False)
                
                # Process steps sheet
                steps_df = pd.DataFrame(columns=["Step"])
                steps_df.to_excel(writer, sheet_name='Process_Steps', index=False)
            
            st.success(f"Created local Excel file: {LOCAL_EXCEL_FILE}")
        return True
    except Exception as e:
        st.error(f"Error creating local Excel file: {str(e)}")
        
        # Try a fallback location if the primary location fails
        try:
            fallback_path = Path.cwd() / "data"
            fallback_path.mkdir(exist_ok=True)
            fallback_file = fallback_path / "die_casting_production_data.xlsx"
            
            with pd.ExcelWriter(fallback_file, engine='openpyxl') as writer:
                pd.DataFrame().to_excel(writer, sheet_name='Production_Records', index=False)
                pd.DataFrame().to_excel(writer, sheet_name='Downtime_Records', index=False)
                pd.DataFrame().to_excel(writer, sheet_name='Quality_Records', index=False)
                pd.DataFrame().to_excel(writer, sheet_name='Config', index=False)
                pd.DataFrame().to_excel(writer, sheet_name='User_Credentials', index=False)
                pd.DataFrame().to_excel(writer, sheet_name='Downtime_Reasons', index=False)
                pd.DataFrame().to_excel(writer, sheet_name='Process_Steps', index=False)
            
            # Update the global variable to use the fallback location
            global LOCAL_EXCEL_FILE
            LOCAL_EXCEL_FILE = fallback_file
            st.success(f"Using fallback location: {fallback_file}")
            return True
        except Exception as e2:
            st.error(f"Failed to create Excel file in fallback location: {str(e2)}")
            return False


def append_to_local_excel(sheet_name, record):
    """Append a record to the local Excel file"""
    try:
        # Read existing data
        if LOCAL_EXCEL_FILE.exists():
            existing_df = pd.read_excel(LOCAL_EXCEL_FILE, sheet_name=sheet_name)
        else:
            # Create empty DataFrame with correct columns
            if sheet_name == 'Production_Records':
                existing_df = pd.DataFrame(columns=[
                    "RecordType", "EntryID", "Timestamp", "Shift", "Team", "Machine", 
                    "Product", "Operator", "Comments"
                ] + DEFAULT_SUBTOPICS)
            elif sheet_name == 'Downtime_Records':
                existing_df = pd.DataFrame(columns=[
                    "EntryID", "Timestamp", "Shift", "Team", "Machine", "Planned_Item", 
                    "Downtime_Reason", "Other_Comments", "Duration_Min"
                ])
            elif sheet_name == 'Quality_Records':
                existing_df = pd.DataFrame(columns=[
                    "EntryID", "Timestamp", "Process_Step", "Product", "Total_Lot_Qty", 
                    "Sample_Size", "AQL_Level", "Accept_Reject", "Defects_Found", 
                    "Results", "Quality_Inspector", "ETF_Number", "Digital_Signature", "Comments"
                ])
            else:
                return False
        
        # Convert record to DataFrame and append
        new_row = pd.DataFrame([record])
        updated_df = pd.concat([existing_df, new_row], ignore_index=True)
        
        # Save back to Excel
        with pd.ExcelWriter(LOCAL_EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            updated_df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        return True
    except Exception as e:
        st.error(f"Error appending to local Excel: {str(e)}")
        return False

def read_local_excel(sheet_name):
    """Read data from local Excel file"""
    try:
        if LOCAL_EXCEL_FILE.exists():
            return pd.read_excel(LOCAL_EXCEL_FILE, sheet_name=sheet_name)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error reading local Excel: {str(e)}")
        return pd.DataFrame()

def update_local_excel_sheet(sheet_name, data):
    """Update an entire sheet in the local Excel file"""
    try:
        # Read the entire Excel file first
        if LOCAL_EXCEL_FILE.exists():
            with pd.ExcelWriter(LOCAL_EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                data.to_excel(writer, sheet_name=sheet_name, index=False)
            return True
        return False
    except Exception as e:
        st.error(f"Error updating local Excel: {str(e)}")
        return False

def backup_all_data_to_local():
    """Backup all data to local Excel file"""
    try:
        # Initialize if needed
        init_local_excel_file()
        
        # Backup production records
        production_df = pd.DataFrame(st.session_state.local_storage["production"])
        if not production_df.empty:
            update_local_excel_sheet('Production_Records', production_df)
        
        # Backup downtime records
        downtime_df = pd.DataFrame(st.session_state.local_storage["downtime"])
        if not downtime_df.empty:
            update_local_excel_sheet('Downtime_Records', downtime_df)
        
        # Backup quality records
        quality_df = pd.DataFrame(st.session_state.local_storage["quality"])
        if not quality_df.empty:
            update_local_excel_sheet('Quality_Records', quality_df)
        
        # Backup config
        config_rows = []
        for product, subs in st.session_state.local_storage["config"].items():
            for s in subs:
                config_rows.append({"Product": product, "Subtopic": s})
        config_df = pd.DataFrame(config_rows)
        if not config_df.empty:
            update_local_excel_sheet('Config', config_df)
        
        # Backup user credentials
        user_rows = []
        for username, password in st.session_state.local_storage["user_credentials"].items():
            user_rows.append({"Username": username, "Password": password, "Role": "Operator"})
        user_df = pd.DataFrame(user_rows)
        if not user_df.empty:
            update_local_excel_sheet('User_Credentials', user_df)
        
        # Backup downtime reasons
        reasons_df = pd.DataFrame({"Reason": st.session_state.local_storage["downtime_reasons"]})
        if not reasons_df.empty:
            update_local_excel_sheet('Downtime_Reasons', reasons_df)
        
        # Backup process steps
        steps_df = pd.DataFrame({"Step": st.session_state.local_storage["process_steps"]})
        if not steps_df.empty:
            update_local_excel_sheet('Process_Steps', steps_df)
        
        st.session_state.last_local_backup = datetime.now()
        return True
    except Exception as e:
        st.error(f"Error backing up data to local Excel: {str(e)}")
        return False

def load_from_local_excel():
    """Load data from local Excel file into session state"""
    try:
        if not LOCAL_EXCEL_FILE.exists():
            return False
        
        # Load production records
        production_df = read_local_excel('Production_Records')
        if not production_df.empty:
            st.session_state.local_storage["production"] = production_df.to_dict('records')
        
        # Load downtime records
        downtime_df = read_local_excel('Downtime_Records')
        if not downtime_df.empty:
            st.session_state.local_storage["downtime"] = downtime_df.to_dict('records')
        
        # Load quality records
        quality_df = read_local_excel('Quality_Records')
        if not quality_df.empty:
            st.session_state.local_storage["quality"] = quality_df.to_dict('records')
        
        # Load config
        config_df = read_local_excel('Config')
        if not config_df.empty:
            cfg = {}
            for _, row in config_df.iterrows():
                p = str(row["Product"]).strip()
                s = str(row["Subtopic"]).strip()
                if p and s:
                    cfg.setdefault(p, []).append(s)
            st.session_state.local_storage["config"] = cfg
            st.session_state.cfg = cfg
        
        # Load user credentials
        user_df = read_local_excel('User_Credentials')
        if not user_df.empty:
            credentials = {}
            for _, row in user_df.iterrows():
                username = str(row["Username"]).strip()
                password = str(row["Password"]).strip()
                if username and password:
                    credentials[username] = password
            st.session_state.local_storage["user_credentials"] = credentials
            st.session_state.user_credentials = credentials
        
        # Load downtime reasons
        reasons_df = read_local_excel('Downtime_Reasons')
        if not reasons_df.empty:
            reasons = [str(row["Reason"]).strip() for _, row in reasons_df.iterrows() if str(row["Reason"]).strip()]
            st.session_state.local_storage["downtime_reasons"] = reasons
            st.session_state.downtime_reasons = reasons
        
        # Load process steps
        steps_df = read_local_excel('Process_Steps')
        if not steps_df.empty:
            steps = [str(row["Step"]).strip() for _, row in steps_df.iterrows() if str(row["Step"]).strip()]
            st.session_state.local_storage["process_steps"] = steps
            st.session_state.process_steps = steps
        
        return True
    except Exception as e:
        st.error(f"Error loading from local Excel: {str(e)}")
        return False

# ------------------ Rate Limiting Decorator ------------------
def rate_limited(max_per_minute):
    min_interval = 60.0 / max_per_minute
    def decorator(func):
        last_time_called = [0.0]
        @wraps(func)
        def rate_limited_function(*args, **kwargs):
            elapsed = time.time() - last_time_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            last_time_called[0] = time.time()
            return func(*args, **kwargs)
        return rate_limited_function
    return decorator

# ------------------ Safe API Call Wrapper ------------------
def safe_api_call(func, *args, **kwargs):
    """Wrapper for Google Sheets calls with error handling"""
    try:
        if not st.session_state.api_available:
            return None
        result = func(*args, **kwargs)
        st.session_state.api_available = True
        return result
    except Exception as e:
        if "quota" in str(e).lower() or "429" in str(e):
            st.session_state.api_available = False
            st.warning("Google Sheets API quota exceeded. Using local storage. Data will be synced when available.")
            return None
        else:
            st.error(f"API Error: {str(e)}")
            return None

# ------------------ Cached Google Sheets Functions ------------------
@st.cache_resource(show_spinner=False)
@rate_limited(10)  # 10 calls per minute max
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
@rate_limited(5)  # 5 calls per minute max
def open_spreadsheet(_client):
    try:
        name = st.secrets["gsheet"]["spreadsheet_name"]
        return safe_api_call(_client.open, name)
    except Exception as e:
        st.error(f"Error opening spreadsheet: {str(e)}")
        return None

def get_worksheet(sheet_name):
    """Get worksheet with caching and fallback"""
    cache_key = f"worksheet_{sheet_name}"
    if cache_key in cache:
        return cache[cache_key]
    
    if not st.session_state.api_available:
        return None
        
    try:
        worksheet = safe_api_call(st.session_state.spreadsheet.worksheet, sheet_name)
        if worksheet:
            cache[cache_key] = worksheet
        return worksheet
    except gspread.WorksheetNotFound:
        try:
            if sheet_name == "Config":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="Config", rows=1000, cols=2)
                if worksheet:
                    rows = [["Product", "Subtopic"]]
                    safe_api_call(worksheet.update, "A1", rows)
                    safe_api_call(worksheet.freeze, rows=1)
            elif sheet_name == "Production_Quality_Records":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="Production_Quality_Records", rows=2000, cols=50)
                if worksheet:
                    headers = ["RecordType", "EntryID", "Timestamp", "Shift", "Team", "Machine", "Product", "Operator", "Comments"] + DEFAULT_SUBTOPICS
                    safe_api_call(worksheet.update, "A1", [headers])
                    safe_api_call(worksheet.freeze, rows=1)
            elif sheet_name == "Machine_Downtime_Records":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="Machine_Downtime_Records", rows=2000, cols=20)
                if worksheet:
                    headers = ["EntryID", "Timestamp", "Shift", "Team", "Machine", "Planned_Item", "Downtime_Reason", "Other_Comments", "Duration_Min"]
                    safe_api_call(worksheet.update, "A1", [headers])
                    safe_api_call(worksheet.freeze, rows=1)
            elif sheet_name == "Quality_Records":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="Quality_Records", rows=2000, cols=50)
                if worksheet:
                    headers = [
                        "EntryID", "Timestamp", "Process_Step", "Product", "Total_Lot_Qty", 
                        "Sample_Size", "AQL_Level", "Accept_Reject", "Defects_Found", 
                        "Results", "Quality_Inspector", "ETF_Number", "Digital_Signature", "Comments"
                    ]
                    safe_api_call(worksheet.update, "A1", [headers])
                    safe_api_call(worksheet.freeze, rows=1)
            elif sheet_name == "User_Credentials":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="User_Credentials", rows=100, cols=3)
                if worksheet:
                    headers = ["Username", "Password", "Role"]
                    safe_api_call(worksheet.update, "A1", [headers])
                    default_users = [
                        ["operator1", "password1", "Operator"],
                        ["operator2", "password2", "Operator"],
                        ["operator3", "password3", "Operator"]
                    ]
                    safe_api_call(worksheet.update, "A2", default_users)
                    safe_api_call(worksheet.freeze, rows=1)
            elif sheet_name == "Downtime_Reasons":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="Downtime_Reasons", rows=100, cols=1)
                if worksheet:
                    headers = ["Reason"]
                    safe_api_call(worksheet.update, "A1", [headers])
                    default_reasons = [[reason] for reason in DEFAULT_DOWNTIME_REASONS]
                    safe_api_call(worksheet.update, "A2", default_reasons)
                    safe_api_call(worksheet.freeze, rows=1)
            elif sheet_name == "Process_Steps":
                worksheet = safe_api_call(st.session_state.spreadsheet.add_worksheet, title="Process_Steps", rows=100, cols=1)
                if worksheet:
                    headers = ["Step"]
                    safe_api_call(worksheet.update, "A1", [headers])
                    default_steps = [[step] for step in DEFAULT_PROCESS_STEPS]
                    safe_api_call(worksheet.update, "A2", default_steps)
                    safe_api_call(worksheet.freeze, rows=1)
            
            if worksheet:
                cache[cache_key] = worksheet
            return worksheet
        except Exception as e:
            st.error(f"Error creating worksheet: {str(e)}")
            return None

# ------------------ Optimized Config helpers ------------------
@st.cache_data(ttl=300, show_spinner=False)
def read_config_cached(_ws_config):
    try:
        if not _ws_config or not st.session_state.api_available:
            return st.session_state.local_storage["config"]
            
        values = safe_api_call(_ws_config.get_all_values)
        if values and len(values) > 1:
            headers = values[0]
            data = values[1:]  # No limit for products
            cfg = {}
            for row in data:
                if len(row) >= 2:
                    p = str(row[0]).strip()
                    s = str(row[1]).strip()
                    if p and s:
                        cfg.setdefault(p, []).append(s)
            # Update local storage
            st.session_state.local_storage["config"] = cfg
            return cfg
        return st.session_state.local_storage["config"]
    except Exception as e:
        st.error(f"Error reading config: {str(e)}")
        return st.session_state.local_storage["config"]

@st.cache_data(ttl=300, show_spinner=False)
def read_user_credentials_cached(_ws_credentials):
    try:
        if not _ws_credentials or not st.session_state.api_available:
            return st.session_state.local_storage["user_credentials"]
            
        values = safe_api_call(_ws_credentials.get_all_values)
        if values and len(values) > 1:
            credentials = {}
            for row in values[1:MAX_USERS + 1]:
                if len(row) >= 2:
                    username = str(row[0]).strip()
                    password = str(row[1]).strip()
                    if username and password:
                        credentials[username] = password
            # Update local storage
            st.session_state.local_storage["user_credentials"] = credentials
            return credentials
        return st.session_state.local_storage["user_credentials"]
    except Exception as e:
        st.error(f"Error reading user credentials: {str(e)}")
        return st.session_state.local_storage["user_credentials"]

@st.cache_data(ttl=300, show_spinner=False)
def read_downtime_reasons_cached(_ws_reasons):
    try:
        if not _ws_reasons or not st.session_state.api_available:
            return st.session_state.local_storage["downtime_reasons"]
            
        values = safe_api_call(_ws_reasons.get_all_values)
        if values and len(values) > 1:
            reasons = []
            for row in values[1:]:
                if row and str(row[0]).strip():
                    reasons.append(str(row[0]).strip())
            result = reasons if reasons else st.session_state.local_storage["downtime_reasons"]
            st.session_state.local_storage["downtime_reasons"] = result
            return result
        return st.session_state.local_storage["downtime_reasons"]
    except Exception as e:
        st.error(f"Error reading downtime reasons: {str(e)}")
        return st.session_state.local_storage["downtime_reasons"]

@st.cache_data(ttl=300, show_spinner=False)
def read_process_steps_cached(_ws_steps):
    try:
        if not _ws_steps or not st.session_state.api_available:
            return st.session_state.local_storage["process_steps"]
            
        values = safe_api_call(_ws_steps.get_all_values)
        if values and len(values) > 1:
            steps = []
            for row in values[1:]:
                if row and str(row[0]).strip():
                    steps.append(str(row[0]).strip())
            result = steps if steps else st.session_state.local_storage["process_steps"]
            st.session_state.local_storage["process_steps"] = result
            return result
        return st.session_state.local_storage["process_steps"]
    except Exception as e:
        st.error(f"Error reading process steps: {str(e)}")
        return st.session_state.local_storage["process_steps"]

def read_config(ws_config):
    return read_config_cached(ws_config)

def read_user_credentials(ws_credentials):
    return read_user_credentials_cached(ws_credentials)

def read_downtime_reasons(ws_reasons):
    return read_downtime_reasons_cached(ws_reasons)

def read_process_steps(ws_steps):
    return read_process_steps_cached(ws_steps)

def write_config(ws_config, cfg: dict):
    try:
        if not st.session_state.api_available:
            st.session_state.local_storage["config"] = cfg
            st.success("Config saved to local storage (will sync when API available)")
            # Also save to local Excel
            backup_all_data_to_local()
            return True
            
        rows = [["Product", "Subtopic"]]
        for product, subs in cfg.items():
            for s in subs:
                rows.append([product, s])
        safe_api_call(ws_config.clear)
        safe_api_call(ws_config.update, "A1", rows)
        safe_api_call(ws_config.freeze, rows=1)
        
        # Update local storage
        st.session_state.local_storage["config"] = cfg
        
        # Also save to local Excel
        backup_all_data_to_local()
        
        # Clear cache after update
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error writing config: {str(e)}")
        st.session_state.local_storage["config"] = cfg
        # Also save to local Excel
        backup_all_data_to_local()
        return True

def write_user_credentials(ws_credentials, credentials: dict):
    try:
        if not st.session_state.api_available:
            st.session_state.local_storage["user_credentials"] = credentials
            st.success("User credentials saved to local storage (will sync when API available)")
            # Also save to local Excel
            backup_all_data_to_local()
            return True
            
        rows = [["Username", "Password", "Role"]]
        for username, password in credentials.items():
            rows.append([username, password, "Operator"])
        safe_api_call(ws_credentials.clear)
        safe_api_call(ws_credentials.update, "A1", rows)
        safe_api_call(ws_credentials.freeze, rows=1)
        
        # Update local storage
        st.session_state.local_storage["user_credentials"] = credentials
        
        # Also save to local Excel
        backup_all_data_to_local()
        
        # Clear cache after update
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error writing user credentials: {str(e)}")
        st.session_state.local_storage["user_credentials"] = credentials
        # Also save to local Excel
        backup_all_data_to_local()
        return True

def write_downtime_reasons(ws_reasons, reasons: list):
    try:
        if not st.session_state.api_available:
            st.session_state.local_storage["downtime_reasons"] = reasons
            st.success("Downtime reasons saved to local storage (will sync when API available)")
            # Also save to local Excel
            backup_all_data_to_local()
            return True
            
        rows = [["Reason"]]
        for reason in reasons:
            rows.append([reason])
        safe_api_call(ws_reasons.clear)
        safe_api_call(ws_reasons.update, "A1", rows)
        safe_api_call(ws_reasons.freeze, rows=1)
        
        # Update local storage
        st.session_state.local_storage["downtime_reasons"] = reasons
        
        # Also save to local Excel
        backup_all_data_to_local()
        
        # Clear cache after update
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error writing downtime reasons: {str(e)}")
        st.session_state.local_storage["downtime_reasons"] = reasons
        # Also save to local Excel
        backup_all_data_to_local()
        return True

def write_process_steps(ws_steps, steps: list):
    try:
        if not st.session_state.api_available:
            st.session_state.local_storage["process_steps"] = steps
            st.success("Process steps saved to local storage (will sync when API available)")
            # Also save to local Excel
            backup_all_data_to_local()
            return True
            
        rows = [["Step"]]
        for step in steps:
            rows.append([step])
        safe_api_call(ws_steps.clear)
        safe_api_call(ws_steps.update, "A1", rows)
        safe_api_call(ws_steps.freeze, rows=1)
        
        # Update local storage
        st.session_state.local_storage["process_steps"] = steps
        
        # Also save to local Excel
        backup_all_data_to_local()
        
        # Clear cache after update
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error writing process steps: {str(e)}")
        st.session_state.local_storage["process_steps"] = steps
        # Also save to local Excel
        backup_all_data_to_local()
        return True

def refresh_config_if_needed(ws_config, ws_credentials, ws_reasons, ws_steps):
    """Refresh config from Google Sheets if needed"""
    if should_refresh_config():
        new_cfg = read_config(ws_config)
        if new_cfg != st.session_state.cfg:
            st.session_state.cfg = new_cfg
        
        new_credentials = read_user_credentials(ws_credentials)
        if new_credentials != st.session_state.user_credentials:
            st.session_state.user_credentials = new_credentials
        
        new_reasons = read_downtime_reasons(ws_reasons)
        if new_reasons != st.session_state.downtime_reasons:
            st.session_state.downtime_reasons = new_reasons
        
        new_steps = read_process_steps(ws_steps)
        if new_steps != st.session_state.process_steps:
            st.session_state.process_steps = new_steps
        
        st.session_state.last_config_update = datetime.now()

# ------------------ Optimized History helpers ------------------
@st.cache_data(ttl=120, show_spinner=False)
def get_recent_production_entries_cached(_ws_production, product: str, limit: int = 10):
    try:
        # Combine API data with local storage
        api_data = pd.DataFrame()
        if _ws_production and st.session_state.api_available:
            values = safe_api_call(_ws_production.get_all_values)
            if values and len(values) > 1:
                headers = values[0]
                data = values[1:limit+1]
                api_data = pd.DataFrame(data, columns=headers)
        
        # Get local storage data
        local_data = pd.DataFrame(st.session_state.local_storage["production"])
        
        # Combine and filter
        if not api_data.empty and not local_data.empty:
            combined = pd.concat([api_data, local_data], ignore_index=True)
        elif not api_data.empty:
            combined = api_data
        else:
            combined = local_data
            
        if "Product" in combined.columns:
            combined = combined[combined["Product"] == product]
        return combined.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        return pd.DataFrame()

@st.cache_data(ttl=120, show_spinner=False)
def get_recent_downtime_entries_cached(_ws_downtime, limit: int = 10):
    try:
        # Combine API data with local storage
        api_data = pd.DataFrame()
        if _ws_downtime and st.session_state.api_available:
            values = safe_api_call(_ws_downtime.get_all_values)
            if values and len(values) > 1:
                headers = values[0]
                data = values[1:limit+1]
                api_data = pd.DataFrame(data, columns=headers)
        
        # Get local storage data
        local_data = pd.DataFrame(st.session_state.local_storage["downtime"])
        
        # Combine
        if not api_data.empty and not local_data.empty:
            combined = pd.concat([api_data, local_data], ignore_index=True)
        elif not api_data.empty:
            combined = api_data
        else:
            combined = local_data
            
        return combined.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading downtime history: {str(e)}")
        return pd.DataFrame()

@st.cache_data(ttl=120, show_spinner=False)
def get_recent_quality_entries_cached(_ws_quality, product: str, limit: int = 10):
    try:
        # Combine API data with local storage
        api_data = pd.DataFrame()
        if _ws_quality and st.session_state.api_available:
            values = safe_api_call(_ws_quality.get_all_values)
            if values and len(values) > 1:
                headers = values[0]
                data = values[1:limit+1]
                api_data = pd.DataFrame(data, columns=headers)
        
        # Get local storage data
        local_data = pd.DataFrame(st.session_state.local_storage["quality"])
        
        # Combine and filter
        if not api_data.empty and not local_data.empty:
            combined = pd.concat([api_data, local_data], ignore_index=True)
        elif not api_data.empty:
            combined = api_data
        else:
            combined = local_data
            
        if "Product" in combined.columns:
            combined = combined[combined["Product"] == product]
        return combined.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading quality history: {str(e)}")
        return pd.DataFrame()

def get_recent_production_entries(ws_production, product: str, limit: int = 10):
    return get_recent_production_entries_cached(ws_production, product, limit)

def get_recent_downtime_entries(ws_downtime, limit: int = 10):
    return get_recent_downtime_entries_cached(ws_downtime, limit)

def get_recent_quality_entries(ws_quality, product: str, limit: int = 10):
    return get_recent_quality_entries_cached(ws_quality, product, limit)

def append_production_record(ws_production, record: dict):
    try:
        # Always save to local storage first
        st.session_state.local_storage["production"].append(record)
        
        # Always save to local Excel file
        append_to_local_excel('Production_Records', record)
        
        if not st.session_state.api_available:
            st.success("Production record saved to local storage and Excel file")
            return True
            
        headers = safe_api_call(ws_production.row_values, 1)
        if headers:
            row = [record.get(h, "") for h in headers]
            success = safe_api_call(ws_production.append_row, row, value_input_option="USER_ENTERED")
            
            if success:
                # Clear cache after new entry
                cache.clear()
                st.cache_data.clear()
                return True
            else:
                st.session_state.pending_records["production"].append(record)
                return True
        return True
    except Exception as e:
        st.error(f"Error saving production record: {str(e)}")
        st.session_state.pending_records["production"].append(record)
        return True

def append_downtime_record(ws_downtime, record: dict):
    try:
        # Always save to local storage first
        st.session_state.local_storage["downtime"].append(record)
        
        # Always save to local Excel file
        append_to_local_excel('Downtime_Records', record)
        
        if not st.session_state.api_available:
            st.success("Downtime record saved to local storage and Excel file")
            return True
            
        headers = safe_api_call(ws_downtime.row_values, 1)
        if headers:
            row = [record.get(h, "") for h in headers]
            success = safe_api_call(ws_downtime.append_row, row, value_input_option="USER_ENTERED")
            
            if success:
                # Clear cache after new entry
                cache.clear()
                st.cache_data.clear()
                return True
            else:
                st.session_state.pending_records["downtime"].append(record)
                return True
        return True
    except Exception as e:
        st.error(f"Error saving downtime record: {str(e)}")
        st.session_state.pending_records["downtime"].append(record)
        return True

def append_quality_record(ws_quality, record: dict):
    try:
        # Always save to local storage first
        st.session_state.local_storage["quality"].append(record)
        
        # Always save to local Excel file
        append_to_local_excel('Quality_Records', record)
        
        if not st.session_state.api_available:
            st.success("Quality record saved to local storage and Excel file")
            return True
            
        headers = safe_api_call(ws_quality.row_values, 1)
        if headers:
            row = [record.get(h, "") for h in headers]
            success = safe_api_call(ws_quality.append_row, row, value_input_option="USER_ENTERED")
            
            if success:
                # Clear cache after new entry
                cache.clear()
                st.cache_data.clear()
                return True
            else:
                st.session_state.pending_records["quality"].append(record)
                return True
        return True
    except Exception as e:
        st.error(f"Error saving quality record: {str(e)}")
        st.session_state.pending_records["quality"].append(record)
        return True

# ------------------ Signature Canvas Component ------------------
def signature_canvas():
    st.markdown("""
    <style>
    .signature-container {
        border: 2px dashed #ccc;
        padding: 15px;
        border-radius: 8px;
        background-color: #f9f9f9;
        margin-bottom: 15px;
    }
    .signature-instruction {
        color: #666;
        font-size: 14px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown("<div class='signature-container'>", unsafe_allow_html=True)
    st.markdown("<div class='signature-instruction'>Please type your full name as your digital signature:</div>", unsafe_allow_html=True)
    
    signature = st.text_input("Digital Signature", key="signature_input", 
                             placeholder="Enter your full name here", 
                             label_visibility="collapsed")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    return signature

# ------------------ Admin UI ------------------
def admin_ui(ws_config, ws_credentials, ws_reasons, ws_steps):
    st.subheader("Admin Management Panel")
    
    # Display API status
    if not st.session_state.api_available:
        st.warning("⚠️ Google Sheets API unavailable. Working in offline mode. Data will sync when connection is restored.")
        if st.button("🔄 Try to Reconnect to Google Sheets"):
            st.session_state.api_available = True
            st.rerun()
    
    # Display local file status
    if LOCAL_EXCEL_FILE.exists():
        file_size = os.path.getsize(LOCAL_EXCEL_FILE) / 1024  # Size in KB
        st.info(f"📁 Local backup file: {LOCAL_EXCEL_FILE.name} ({file_size:.1f} KB)")
        
        if st.button("💾 Backup All Data to Local Excel Now"):
            if backup_all_data_to_local():
                st.success("All data backed up to local Excel file!")
    else:
        st.warning("Local backup file not found. It will be created automatically when needed.")
    
    tabs = st.tabs(["Products & Subtopics", "User Credentials", "Downtime Reasons", "Process Steps", "Quality Team Settings"])
    
    with tabs[0]:
        st.subheader("Manage Products & Subtopics")
        
        # Auto-refresh config to see changes from other devices
        refresh_config_if_needed(ws_config, ws_credentials, ws_reasons, ws_steps)

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
    
    with tabs[1]:
        st.subheader("Manage User Credentials")
        
        st.write(f"Current Users ({len(st.session_state.user_credentials)}/{MAX_USERS}):")
        for username, password in st.session_state.user_credentials.items():
            st.write(f"- {username}: {password}")
        
        with st.expander("Add/Edit User"):
            username = st.text_input("Username", key="edit_username")
            password = st.text_input("Password", type="password", key="edit_password")
            if st.button("Save User Credentials"):
                if username and password:
                    if len(st.session_state.user_credentials) >= MAX_USERS and username not in st.session_state.user_credentials:
                        st.error(f"Maximum number of users reached ({MAX_USERS}). Cannot add more users.")
                    else:
                        st.session_state.user_credentials[username] = password
                        if write_user_credentials(ws_credentials, st.session_state.user_credentials):
                            st.success(f"Credentials updated for {username}")
                            st.rerun()
        
        with st.expander("Remove User"):
            user_to_remove = st.selectbox("Select user to remove", list(st.session_state.user_credentials.keys()), key="remove_user")
            if st.button("Remove User"):
                if user_to_remove in st.session_state.user_credentials:
                    del st.session_state.user_credentials[user_to_remove]
                    if write_user_credentials(ws_credentials, st.session_state.user_credentials):
                        st.warning(f"Removed user: {user_to_remove}")
                        st.rerun()
    
    with tabs[2]:
        st.subheader("Manage Downtime Reasons")
        
        st.write("Current Downtime Reasons:")
        for reason in st.session_state.downtime_reasons:
            st.write(f"- {reason}")
        
        with st.expander("Add Downtime Reason"):
            new_reason = st.text_input("New Downtime Reason", key="new_reason")
            if st.button("Add Reason"):
                if new_reason.strip() and new_reason not in st.session_state.downtime_reasons:
                    st.session_state.downtime_reasons.append(new_reason.strip())
                    if write_downtime_reasons(ws_reasons, st.session_state.downtime_reasons):
                        st.success(f"Added downtime reason: {new_reason}")
                        st.rerun()
        
        with st.expander("Remove Downtime Reason"):
            reason_to_remove = st.selectbox("Select reason to remove", st.session_state.downtime_reasons, key="remove_reason")
            if st.button("Remove Reason"):
                if reason_to_remove in st.session_state.downtime_reasons:
                    st.session_state.downtime_reasons.remove(reason_to_remove)
                    if write_downtime_reasons(ws_reasons, st.session_state.downtime_reasons):
                        st.warning(f"Removed reason: {reason_to_remove}")
                        st.rerun()
    
    with tabs[3]:
        st.subheader("Manage Process Steps")
        
        st.write("Current Process Steps:")
        for step in st.session_state.process_steps:
            st.write(f"- {step}")
        
        with st.expander("Add Process Step"):
            new_step = st.text_input("New Process Step", key="new_step")
            if st.button("Add Step"):
                if new_step.strip() and new_step not in st.session_state.process_steps:
                    st.session_state.process_steps.append(new_step.strip())
                    if write_process_steps(ws_steps, st.session_state.process_steps):
                        st.success(f"Added process step: {new_step}")
                        st.rerun()
        
        with st.expander("Remove Process Step"):
            step_to_remove = st.selectbox("Select step to remove", st.session_state.process_steps, key="remove_step")
            if st.button("Remove Step"):
                if step_to_remove in st.session_state.process_steps:
                    st.session_state.process_steps.remove(step_to_remove)
                    if write_process_steps(ws_steps, st.session_state.process_steps):
                        st.warning(f"Removed step: {step_to_remove}")
                        st.rerun()
        
        with st.expander("Edit Process Steps"):
            st.write("Edit existing process steps:")
            edited_steps = []
            for i, step in enumerate(st.session_state.process_steps):
                edited_step = st.text_input(f"Process Step {i+1}", value=step, key=f"edit_step_{i}")
                edited_steps.append(edited_step)
            
            if st.button("Save All Process Steps"):
                # Remove empty steps and duplicates
                cleaned_steps = list(set([step.strip() for step in edited_steps if step.strip()]))
                if cleaned_steps:
                    st.session_state.process_steps = cleaned_steps
                    if write_process_steps(ws_steps, st.session_state.process_steps):
                        st.success("All process steps updated successfully!")
                        st.rerun()
    
    with tabs[4]:
        st.subheader("Quality Team Records Settings")
        
        st.info("Manage all quality team record settings in this section")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Current Process Steps:**")
            for i, step in enumerate(st.session_state.process_steps, 1):
                st.write(f"{i}. {step}")
        
        with col2:
            st.write("**Quick Actions:**")
            if st.button("Add Default Process Steps"):
                default_steps = DEFAULT_PROCESS_STEPS.copy()
                for step in default_steps:
                    if step not in st.session_state.process_steps:
                        st.session_state.process_steps.append(step)
                if write_process_steps(ws_steps, st.session_state.process_steps):
                    st.success("Default process steps added!")
                    st.rerun()
            
            if st.button("Clear All Process Steps"):
                st.session_state.process_steps = []
                if write_process_steps(ws_steps, st.session_state.process_steps):
                    st.warning("All process steps cleared!")
                    st.rerun()
        
        st.divider()
        st.write("**Quality Section Password:**")
        st.write(f"Current Password: `{QUALITY_PASSWORD}`")
        st.info("To change the password, modify the QUALITY_PASSWORD variable in the code")
        
        st.divider()
        st.write("**Add Multiple Process Steps:**")
        multiple_steps = st.text_area("Enter multiple process steps (one per line):", 
                                     height=100,
                                     help="Enter each process step on a separate line")
        if st.button("Add Multiple Steps"):
            if multiple_steps.strip():
                new_steps = [step.strip() for step in multiple_steps.split('\n') if step.strip()]
                for step in new_steps:
                    if step not in st.session_state.process_steps:
                        st.session_state.process_steps.append(step)
                if write_process_steps(ws_steps, st.session_state.process_steps):
                    st.success(f"Added {len(new_steps)} new process steps!")
                    st.rerun()
    
    # Manual refresh button
    if st.button("🔄 Refresh All Configuration"):
        st.session_state.last_config_update = None
        st.cache_data.clear()
        cache.clear()
        st.rerun()

# ------------------ Production Records UI ------------------
def production_records_ui(ws_config, ws_production, ws_credentials):
    st.subheader("Production Records")
    
    # Password protection
    if not st.session_state.production_password_entered:
        username = st.selectbox("Username", list(st.session_state.user_credentials.keys()), key="production_username")
        password = st.text_input("Password", type="password", key="production_password")
        
        if st.button("Login", key="production_login"):
            if username in st.session_state.user_credentials and st.session_state.user_credentials[username] == password:
                st.session_state.production_password_entered = True
                st.session_state.current_user = username
                st.rerun()
            else:
                st.error("Invalid password")
        return
    
    st.success(f"Logged in as: {st.session_state.current_user}")
    if st.button("Logout", key="production_logout"):
        st.session_state.production_password_entered = False
        st.session_state.current_user = None
        st.rerun()
    
    # Auto-refresh config to get latest changes from admin
    refresh_config_if_needed(ws_config, ws_credentials, None, None)
    
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
        # Validate required numeric fields (excluding Slow shot Count and Reject Qty which can be 0)
        required_fields = [st for st in current_subtopics 
                          if ("quantity" in st.lower() or "qty" in st.lower() or "count" in st.lower()) 
                          and "slow" not in st.lower() and "reject" not in st.lower()]
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
                    "Operator": st.session_state.current_user,  # Add operator name
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

# ------------------ Machine Downtime Records UI ------------------
def downtime_records_ui(ws_downtime, ws_config, ws_reasons):
    st.subheader("Machine Downtime Records")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        shift = st.selectbox("Shift", ["Day", "Night"], key="downtime_shift")
    with col2:
        team = st.selectbox("Team", ["A", "B", "C"], key="downtime_team")
    with col3:
        machine = st.selectbox("Machine", ["M1", "M2"], key="downtime_machine")
    
    # Planned Item dropdown with products from admin config
    planned_item = st.selectbox("Planned Item", sorted(st.session_state.cfg.keys()), key="planned_item")
    
    downtime_reason = st.selectbox(
        "Downtime Reason", 
        st.session_state.downtime_reasons,
        key="downtime_reason"
    )
    other_comments = st.text_area("Other Comments", key="downtime_comments")
    duration_min = st.number_input("Duration (Min)", min_value=1, step=1, key="duration_min")

    if st.button("Submit Downtime Record", key="submit_downtime_btn"):
        # Validate required fields
        if not other_comments.strip():
            st.error("Comments cannot be empty.")
        elif duration_min <= 0:
            st.error("Duration must be greater than 0.")
        else:
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

# ------------------ Quality Records UI ------------------
def quality_records_ui(ws_quality, ws_config, ws_steps):
    st.subheader("Quality Team Records")
    
    # Password protection for Quality section
    if not st.session_state.quality_password_entered:
        st.info("Please enter the quality team password to access this section")
        quality_pw = st.text_input("Quality Team Password", type="password", key="quality_password")
        
        if st.button("Authenticate", key="quality_auth_btn"):
            if quality_pw == QUALITY_PASSWORD:
                st.session_state.quality_password_entered = True
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
        return
    
    st.success("✓ Authenticated as Quality Team Member")
    if st.button("Logout from Quality", key="quality_logout_btn"):
        st.session_state.quality_password_entered = False
        st.rerun()
    
    st.info("Sri Lanka Time: " + get_sri_lanka_time())
    
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    col1, col2 = st.columns(2)
    with col1:
        process_step = st.selectbox("Process Step", st.session_state.process_steps, key="process_step")
    with col2:
        product = st.selectbox("Select Item", sorted(st.session_state.cfg.keys()), key="quality_product")
    
    total_lot_qty = st.number_input("Total Lot Qty", min_value=1, step=1, key="total_lot_qty")
    sample_size = st.number_input("Sample Size", min_value=1, step=1, key="sample_size")
    aql_level = st.text_input("AQL Level", key="aql_level")
    accept_reject = st.selectbox("Accept/Reject", ["Accept", "Reject"], key="accept_reject")
    defects_found = st.text_area("Defects Found", key="defects_found")
    results = st.selectbox("Results", ["Pass", "Fail"], key="results")
    quality_inspector = st.text_input("Quality Inspector", key="quality_inspector")
    etf_number = st.text_input("ETF Number", key="etf_number")
    
    # Digital signature canvas
    st.subheader("Digital Signature")
    digital_signature = signature_canvas()
    
    comments = st.text_area("Comments", key="quality_comments")

    if st.button("Submit Quality Record", key="submit_quality_btn"):
        # Validate required fields
        required_fields = {
            "Total Lot Qty": total_lot_qty,
            "Sample Size": sample_size,
            "AQL Level": aql_level,
            "Accept/Reject": accept_reject,
            "Results": results,
            "Quality Inspector": quality_inspector,
            "ETF Number": etf_number,
            "Digital Signature": digital_signature
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        
        if missing_fields:
            st.error(f"Please fill in all required fields: {', '.join(missing_fields)}")
        else:
            try:
                entry_id = uuid.uuid4().hex
                record = {
                    "EntryID": entry_id,
                    "Timestamp": get_sri_lanka_time(),
                    "Process_Step": process_step,
                    "Product": product,
                    "Total_Lot_Qty": total_lot_qty,
                    "Sample_Size": sample_size,
                    "AQL_Level": aql_level,
                    "Accept_Reject": accept_reject,
                    "Defects_Found": defects_found,
                    "Results": results,
                    "Quality_Inspector": quality_inspector,
                    "ETF_Number": etf_number,
                    "Digital_Signature": digital_signature,
                    "Comments": comments
                }
                if append_quality_record(ws_quality, record):
                    st.success(f"Quality Record Saved! EntryID: {entry_id}")
            except Exception as e:
                st.error(f"Error saving data: {str(e)}")

    # Display recent quality entries with a spinner
    with st.spinner("Loading recent entries..."):
        df = get_recent_quality_entries(ws_quality, product)
        if not df.empty:
            st.subheader("Recent Quality Entries")
            st.dataframe(df, use_container_width=True)
        else:
            st.caption("No quality entries yet for this product.")

# ------------------ Main UI ------------------
def main_ui(ws_config, ws_production, ws_downtime, ws_quality, ws_credentials, ws_reasons, ws_steps):
    st.title(APP_TITLE)
    
    # Display API status
    if not st.session_state.api_available:
        st.warning("⚠️ Google Sheets API unavailable. Working in offline mode. Data will sync when connection is restored.")
    
    # Display local backup status
    if LOCAL_EXCEL_FILE.exists():
        file_size = os.path.getsize(LOCAL_EXCEL_FILE) / 1024  # Size in KB
        st.info(f"📁 Local backup file: {LOCAL_EXCEL_FILE.name} ({file_size:.1f} KB)")
    else:
        st.info("📁 Local backup file will be created automatically when needed")
    
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
        production_records_ui(ws_config, ws_production, ws_credentials)
    elif section == "Machine Downtime Records":
        downtime_records_ui(ws_downtime, ws_config, ws_reasons)
    elif section == "Quality Team Records":
        quality_records_ui(ws_quality, ws_config, ws_steps)

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    
    # Initialize local Excel file
    init_local_excel_file()
    
    # Load data from local Excel file if available
    load_from_local_excel()
    
    # Initialize Google Sheets client only once
    if st.session_state.gs_client is None:
        with st.spinner("Connecting to Google Sheets..."):
            st.session_state.gs_client = get_gs_client()
            if st.session_state.gs_client:
                st.session_state.spreadsheet = open_spreadsheet(st.session_state.gs_client)
    
    try:
        # Get worksheets
        ws_config = get_worksheet("Config") if st.session_state.spreadsheet else None
        ws_production = get_worksheet("Production_Quality_Records") if st.session_state.spreadsheet else None
        ws_downtime = get_worksheet("Machine_Downtime_Records") if st.session_state.spreadsheet else None
        ws_quality = get_worksheet("Quality_Records") if st.session_state.spreadsheet else None
        ws_credentials = get_worksheet("User_Credentials") if st.session_state.spreadsheet else None
        ws_reasons = get_worksheet("Downtime_Reasons") if st.session_state.spreadsheet else None
        ws_steps = get_worksheet("Process_Steps") if st.session_state.spreadsheet else None
        
        # Read config from Google Sheets at startup or use local storage
        if not st.session_state.cfg:
            st.session_state.cfg = read_config(ws_config)
        
        if not st.session_state.user_credentials:
            st.session_state.user_credentials = read_user_credentials(ws_credentials)
        
        if not st.session_state.downtime_reasons:
            st.session_state.downtime_reasons = read_downtime_reasons(ws_reasons)
        
        if not st.session_state.process_steps:
            st.session_state.process_steps = read_process_steps(ws_steps)
        
        st.session_state.last_config_update = datetime.now()

        # Check if user is admin
        st.sidebar.header("Admin Access")
        is_admin = st.sidebar.checkbox("Admin Mode", key="admin_mode")
        
        if is_admin:
            pw = st.sidebar.text_input("Admin Password", type="password", key="admin_pw")
            if pw == "admin123":
                admin_ui(ws_config, ws_credentials, ws_reasons, ws_steps)
            elif pw:
                st.sidebar.warning("Incorrect admin password")
            else:
                main_ui(ws_config, ws_production, ws_downtime, ws_quality, ws_credentials, ws_reasons, ws_steps)
        else:
            main_ui(ws_config, ws_production, ws_downtime, ws_quality, ws_credentials, ws_reasons, ws_steps)

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()








