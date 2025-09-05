import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz
import time
import json

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')

DEFAULT_SUBTOPICS = [
    "Date",
    "Machine", 
    "Shift",
    "Team",
    "Item",
    "Target_Quantity",
    "Actual_Quantity",
    "Slow_shot_Count",
    "Reject_Quantity",
    "Good_PCS_Quantity"
]

QUALITY_PASSWORD = "quality123"
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

DOWNTIME_PASSWORD = "downtime123"
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
    try:
        key = f"die_casting_{data_type}"
        st.session_state[key] = json.dumps(data)
    except Exception as e:
        st.error(f"Error saving to local storage: {str(e)}")

def load_from_local_storage(data_type, default=None):
    try:
        key = f"die_casting_{data_type}"
        if key in st.session_state:
            loaded_data = st.session_state[key]
            if isinstance(loaded_data, str):
                return json.loads(loaded_data)
            return loaded_data
    except Exception as e:
        st.error(f"Error loading from local storage: {str(e)}")
    return default if default is not None else []

def clear_local_storage(data_type):
    key = f"die_casting_{data_type}"
    if key in st.session_state:
        del st.session_state[key]

# ------------------ Local Data Management ------------------
def save_to_local(data_type, record):
    try:
        if not isinstance(record, dict):
            st.error("Invalid record format")
            return
        key = f"die_casting_{data_type}"
        current_data = st.session_state.get(key, [])
        if not isinstance(current_data, list):
            current_data = []
        current_data.append(record)
        st.session_state[key] = current_data
        save_to_local_storage(data_type, current_data)
        st.session_state.die_casting_pending_sync = True
        save_to_local_storage('pending_sync', True)
        st.success(f"{data_type.capitalize()} data saved locally!")
    except Exception as e:
        st.error(f"Error saving data locally: {str(e)}")

# ------------------ Initialize Session State ------------------
if 'cfg' not in st.session_state:
    st.session_state.cfg = {}
if 'last_config_update' not in st.session_state:
    st.session_state.last_config_update = None
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = ""
if 'sheet_initialized' not in st.session_state:
    st.session_state.sheet_initialized = False

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
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 120

# ------------------ Google Sheets ------------------
def get_gs_client():
    try:
        if 'gcp_service_account' not in st.secrets:
            st.error("Google Service Account credentials not found.")
            return None
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds_dict = st.secrets["gcp_service_account"]
        creds_dict["private_key"] = creds_dict["private_key"].replace('\\n', '\n')
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {str(e)}")
        return None

def initialize_google_sheets():
    if st.session_state.sheet_initialized:
        return True
    try:
        client = get_gs_client()
        if client is None:
            return False
        sh = client.open(st.secrets["gsheet"]["spreadsheet_name"])
        sh.worksheet("Production_Config")
        st.session_state.sheet_initialized = True
        return True
    except:
        st.warning("Google Sheets not accessible. Offline mode active.")
        return False

def read_downtime_config():
    try:
        if initialize_google_sheets():
            client = get_gs_client()
            sh = client.open(st.secrets["gsheet"]["spreadsheet_name"])
            ws = sh.worksheet("Downtime_Config")
            values = ws.get_all_records()
            machines = list({str(r.get("Machine","")).strip() for r in values if r.get("Machine")})
            breakdown_reasons = list({str(r.get("Breakdown_Reason","")).strip() for r in values if r.get("Breakdown_Reason")})
            return {"machines": machines, "breakdown_reasons": breakdown_reasons}
    except:
        pass
    return {"machines": ["Machine 1", "Machine 2", "Machine 3"],
            "breakdown_reasons": ["Electrical Fault","Mechanical Failure","Maintenance","Material Issue"]}

def get_default_config():
    return {"Product1": DEFAULT_SUBTOPICS.copy(), "Product2": DEFAULT_SUBTOPICS.copy()}

def refresh_config_if_needed():
    if should_refresh_config() and initialize_google_sheets():
        try:
            client = get_gs_client()
            sh = client.open(st.secrets["gsheet"]["spreadsheet_name"])
            ws = sh.worksheet("Production_Config")
            values = ws.get_all_records()
            cfg = {}
            for row in values:
                p = str(row.get("Product","")).strip()
                s = str(row.get("Subtopic","")).strip()
                if not p or not s: continue
                cfg.setdefault(p,[]).append(s)
            if cfg:
                st.session_state.cfg = cfg
                st.session_state.last_config_update = datetime.now()
                return True
        except:
            pass
    if not st.session_state.cfg:
        st.session_state.cfg = get_default_config()
    return False

# ------------------ Sync ------------------
def sync_with_google_sheets():
    if not st.session_state.get('die_casting_pending_sync', False):
        st.info("No data pending sync")
        return
    if not initialize_google_sheets():
        st.warning("Cannot connect to Google Sheets")
        return
    try:
        client = get_gs_client()
        sh = client.open(st.secrets["gsheet"]["spreadsheet_name"])
        sync_count = 0

        # Sync Production
        production_data = st.session_state.get('die_casting_production', [])
        if production_data:
            ws = sh.worksheet("History")
            df = pd.DataFrame(ws.get_all_records())
            for record in production_data:
                if isinstance(record, str):
                    record = json.loads(record)
                for k in record.keys():
                    if k not in df.columns:
                        df[k] = ""
                df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
                sync_count += 1
            ws.update([df.columns.tolist()] + df.values.tolist())

        # Sync Quality
        quality_data = st.session_state.get('die_casting_quality', [])
        if quality_data:
            ws_quality = sh.worksheet("Quality_History")
            for record in quality_data:
                if isinstance(record, str):
                    record = json.loads(record)
                headers = ["User","EntryID","Timestamp","Product"]+QUALITY_DEFAULT_FIELDS
                row = [record.get(h,"") for h in headers]
                ws_quality.append_row(row, value_input_option="USER_ENTERED")
                sync_count += 1
                time.sleep(1)

        # Sync Downtime
        downtime_data = st.session_state.get('die_casting_downtime', [])
        if downtime_data:
            ws_downtime = sh.worksheet("Downtime_History")
            for record in downtime_data:
                if isinstance(record, str):
                    record = json.loads(record)
                headers = ["User","EntryID","Timestamp"]+DOWNTIME_DEFAULT_FIELDS
                row = [record.get(h,"") for h in headers]
                ws_downtime.append_row(row, value_input_option="USER_ENTERED")
                sync_count += 1
                time.sleep(1)

        clear_local_storage('production')
        clear_local_storage('quality')
        clear_local_storage('downtime')
        st.session_state.die_casting_pending_sync = False
        st.success(f"Synced {sync_count} records to Google Sheets successfully!")

    except Exception as e:
        st.error(f"Sync failed: {str(e)}")

# ------------------ UIs ------------------
def login_ui():
    st.title(APP_TITLE)
    role = st.radio("Select Role", ["Admin", "Production", "Quality", "Downtime"])
    pwd = st.text_input("Enter Password", type="password") if role in ["Quality", "Downtime"] else ""
    if st.button("Login"):
        if role == "Quality" and pwd != QUALITY_PASSWORD:
            st.error("Invalid Password")
            return
        elif role == "Downtime" and pwd != DOWNTIME_PASSWORD:
            st.error("Invalid Password")
            return
        st.session_state.logged_in = True
        st.session_state.user_role = role
        st.session_state.current_user = role
        st.success(f"Logged in as {role}")

def production_ui():
    st.header("Production Data Entry")
    refresh_config_if_needed()
    products = list(st.session_state.cfg.keys())
    product = st.selectbox("Select Product", products)
    fields = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS)
    data = {}
    for f in fields:
        data[f] = st.text_input(f)
    if st.button("Save Production Record"):
        data['EntryID'] = str(uuid.uuid4())
        data['User'] = st.session_state.current_user
        data['Timestamp'] = get_sri_lanka_time()
        data['Product'] = product
        save_to_local("production", data)

def quality_ui():
    st.header("Quality Data Entry")
    data = {}
    for f in QUALITY_DEFAULT_FIELDS:
        data[f] = st.text_input(f)
    if st.button("Save Quality Record"):
        data['EntryID'] = str(uuid.uuid4())
        data['User'] = st.session_state.current_user
        data['Timestamp'] = get_sri_lanka_time()
        save_to_local("quality", data)

def downtime_ui():
    st.header("Downtime Data Entry")
    cfg = read_downtime_config()
    data = {}
    data['Machine'] = st.selectbox("Machine", cfg["machines"])
    data['Shift'] = st.selectbox("Shift", ["A","B","C"])
    data['Team'] = st.text_input("Team")
    data['Planned_Item'] = st.text_input("Planned Item")
    data['Breakdown_Reason'] = st.selectbox("Breakdown Reason", cfg["breakdown_reasons"])
    data['Duration_Mins'] = st.number_input("Duration (minutes)", min_value=0)
    if st.button("Save Downtime Record"):
        data['EntryID'] = str(uuid.uuid4())
        data['User'] = st.session_state.current_user
        data['Timestamp'] = get_sri_lanka_time()
        save_to_local("downtime", data)

# ------------------ Main ------------------
def main():
    try:
        if not st.session_state.logged_in:
            login_ui()
            return

        st.sidebar.title("Navigation")
        if st.session_state.user_role == "Admin":
            page = st.sidebar.radio("Go to", ["Production", "Quality", "Downtime", "Sync"])
        elif st.session_state.user_role == "Production":
            page = st.sidebar.radio("Go to", ["Production", "Sync"])
        elif st.session_state.user_role == "Quality":
            page = st.sidebar.radio("Go to", ["Quality", "Sync"])
        elif st.session_state.user_role == "Downtime":
            page = st.sidebar.radio("Go to", ["Downtime", "Sync"])
        else:
            st.error("Unknown user role. Please contact admin.")
            return

        if page == "Production":
            production_ui()
        elif page == "Quality":
            quality_ui()
        elif page == "Downtime":
            downtime_ui()
        elif page == "Sync":
            sync_with_google_sheets()
        else:
            st.error("Unknown page")

    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")


if __name__ == "__main__":
    main()
