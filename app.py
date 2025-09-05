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
import numpy as np

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
        # Convert int64 to regular int for JSON serialization
        def convert_int64(obj):
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, list):
                return [convert_int64(item) for item in obj]
            elif isinstance(obj, dict):
                return {k: convert_int64(v) for k, v in obj.items()}
            return obj
        
        converted_data = convert_int64(data)
        
        key = f"die_casting_{data_type}"
        json_data = json.dumps(converted_data)
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

# ------------------ Local Data Management ------------------
def save_to_local(data_type, record):
    """Save data to local storage"""
    try:
        # Ensure record is a dictionary
        if not isinstance(record, dict):
            st.error("Invalid record format")
            return
            
        # Convert int64 values to regular int for JSON serialization
        converted_record = {}
        for key, value in record.items():
            if hasattr(value, 'dtype'):  # Check if it's a numpy type
                if np.issubdtype(value.dtype, np.integer):
                    converted_record[key] = int(value)
                else:
                    converted_record[key] = value
            else:
                converted_record[key] = value
            
        # Get current data - ensure it's always a list
        key = f"die_casting_{data_type}"
        current_data = st.session_state.get(key, [])
        
        # Make sure current_data is a list
        if not isinstance(current_data, list):
            current_data = []
        
        # Add new record
        current_data.append(converted_record)
        
        # Save back to session state
        st.session_state[key] = current_data
        
        # Save to local storage
        save_to_local_storage(data_type, current_data)
        
        # Mark as pending sync
        st.session_state.die_casting_pending_sync = True
        save_to_local_storage('pending_sync', True)
        
        st.success("Data saved locally successfully!")
        
    except Exception as e:
        st.error(f"Error saving data locally: {str(e)}")
        

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

# ... (Other helper functions and Google Sheets connection code remain unchanged) ...


# ------------------ Production UI ------------------
def production_ui():
    st.subheader(f"Production Data Entry - User: {st.session_state.current_user}")
    
    # Refresh button at the top
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("")  # Spacer
    with col2:
        if st.button("🔄 Refresh Data", key="prod_refresh_btn"):
            st.session_state.last_config_update = None
            if refresh_config_if_needed():
                st.success("Data refreshed from Google Sheets!")
            else:
                st.warning("Using local data cache")
            st.experimental_rerun()
    
    # Try to refresh config (non-blocking)
    refresh_config_if_needed()
    
    # Read production configuration directly from sheet
    config_df = pd.DataFrame()
    try:
        if initialize_google_sheets():
            client = get_gs_client()
            name = st.secrets["gsheet"]["spreadsheet_name"]
            sh = client.open(name)
            try:
                ws_config = sh.worksheet("Production_Config")
                config_values = ws_config.get_all_records()
                config_df = pd.DataFrame(config_values)
            except Exception:
                config_df = pd.DataFrame()
    except Exception:
        config_df = pd.DataFrame()
    
    # Determine available items
    if not config_df.empty and "Product" in config_df.columns:
        available_items = list(config_df["Product"].dropna().unique())
    else:
        available_items = list(st.session_state.cfg.keys())
    
    if not available_items:
        st.info("No products available yet.")
        return

    st.write("Fill **all fields** below:")
    
    col1, col2 = st.columns(2)
    
    # Column 1 - Date & Time, Item
    sri_time = get_sri_lanka_time()
    with col1:
        date_value = st.text_input("Date & Time", value=sri_time, key="date_field")
        item_value = st.selectbox("Item", options=available_items, key="item_field")
    
    # Column 2 - dynamic subtopics (from Production_Config) + legacy numeric fields
    dynamic_record = {}
    with col2:
        if not config_df.empty and "Product" in config_df.columns and item_value:
            filtered = config_df[config_df["Product"] == item_value]
            for idx, row in filtered.iterrows():
                subtopic = str(row.get("Subtopic", "")).strip()
                dropdown_flag = str(row.get("Dropdown or Not", "")).strip().lower() == "yes"
                options_text = str(row.get("Dropdown Options", "")).strip()
                
                # Timestamp & Date auto-filled
                if subtopic.lower() == "timestamp":
                    st.text_input(subtopic, value=sri_time, disabled=True, key=f"dyn_{idx}_{subtopic}")
                    dynamic_record[subtopic] = sri_time
                    continue
                if subtopic.lower() == "date":
                    st.text_input(subtopic, value=sri_time, disabled=True, key=f"dyn_{idx}_{subtopic}")
                    dynamic_record[subtopic] = sri_time
                    continue
                
                # Dropdown or text input
                if dropdown_flag:
                    options = [opt.strip() for opt in options_text.split(",") if opt.strip()]
                    dynamic_record[subtopic] = st.selectbox(subtopic, [""] + options, key=f"dyn_{idx}_{subtopic}")
                else:
                    dynamic_record[subtopic] = st.text_input(subtopic, key=f"dyn_{idx}_{subtopic}")
        else:
            # Legacy numeric fields if no config
            target_quantity = int(st.number_input("Target Quantity", min_value=1, step=1, key="target_quantity"))
            actual_quantity = int(st.number_input("Actual Quantity", min_value=1, step=1, key="actual_quantity"))
            slow_shot_count = int(st.number_input("Slow shot Count", min_value=0, step=1, key="slow_shot_count"))
            reject_quantity = int(st.number_input("Reject Quantity", min_value=0, step=1, key="reject_quantity"))
            good_pcs_quantity = int(st.number_input("Good PCS Quantity", min_value=0, step=1, key="good_pcs_quantity"))
            
            dynamic_record["Target_Quantity"] = target_quantity
            dynamic_record["Actual_Quantity"] = actual_quantity
            dynamic_record["Slow_shot_Count"] = slow_shot_count
            dynamic_record["Reject_Quantity"] = reject_quantity
            dynamic_record["Good_PCS_Quantity"] = good_pcs_quantity

    comments = st.text_area("Comments", key="comments")

    # Build final record
    record = {
        "User": st.session_state.current_user,
        "EntryID": uuid.uuid4().hex,
        "Timestamp": dynamic_record.get("Timestamp", sri_time),
        "Date": dynamic_record.get("Date", date_value if date_value else sri_time),
        "Item": item_value,
        "Comments": comments
    }
    record.update(dynamic_record)

    # Save locally
    if st.button("Save Locally", key="submit_btn"):
        missing = [k for k, v in record.items() if k != "Comments" and (v is None or v == "")]
        if missing:
            st.error(f"Please fill required fields. Missing: {', '.join(missing[:5])}")
        else:
            try:
                save_to_local('production', record)
                st.success(f"Saved locally! EntryID: {record['EntryID']}")
            except Exception as e:
                st.error(f"Error saving data: {str(e)}")

    # Display local entries
    production_data = st.session_state.get('die_casting_production', [])
    if production_data:
        st.subheader("Local Entries (Pending Sync)")
        try:
            data_for_df = []
            for rec in production_data:
                # If record stored as JSON string, try to parse safely
                if isinstance(rec, str):
                    try:
                        obj = json.loads(rec)
                        if isinstance(obj, dict):
                            data_for_df.append(obj)
                    except Exception:
                        continue
                elif isinstance(rec, dict):
                    data_for_df.append(rec)
            
            if data_for_df:
                local_df = pd.DataFrame(data_for_df)
                display_cols = ["User", "Timestamp", "Date", "Item", 
                                "Target_Quantity", "Actual_Quantity", "Good_PCS_Quantity"]
                available_cols = [col for col in display_cols if col in local_df.columns]
                st.dataframe(local_df[available_cols].head(10) if available_cols else local_df.head(10))
            else:
                st.info("No valid production data available")
        except Exception as e:
            st.error(f"Error displaying data: {str(e)}")

    # Sync button
    if st.button("🔄 Sync with Google Sheets Now"):
        sync_with_google_sheets()
        st.experimental_rerun()


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
            st.experimental_rerun()
    
    refresh_config_if_needed()
    
    # Read available products from production config
    available_products = list(st.session_state.cfg.keys())
    
    if not available_products:
        st.error("No products available.")
        return
    
    st.write("Fill all quality inspection details below:")
    
    # Product selection
    product = st.selectbox("Select Product", options=available_products, key="quality_product")
    
    col1, col2 = st.columns(2)
    
    with col1:
        total_lot_qty = st.number_input("Total Lot Qty", min_value=1, step=1, key="total_lot_qty")
        sample_size = st.number_input("Sample Size", min_value=1, step=1, key="sample_size")
        aql_level = st.text_input("AQL Level", key="aql_level")
        accept_reject = st.selectbox("Accept/Reject", options=["Accept", "Reject"], key="accept_reject")
    
    with col2:
        results = st.text_input("Results", key="results")
        quality_inspector = st.text_input("Quality Inspector", value=st.session_state.current_user, key="quality_inspector")
        epf_number = st.text_input("EPF Number", key="epf_number")
        
        st.write("Digital Signature:")
        digital_signature = st.text_input("Type your signature", key="digital_signature")
    
    comments = st.text_area("Additional Comments", key="quality_comments")
    
    if st.button("Submit Quality Data", key="submit_quality_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "User": st.session_state.current_user,
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "Product": product,
                "Total_Lot_Qty": total_lot_qty,
                "Sample_Size": sample_size,
                "AQL_Level": aql_level,
                "Accept_Reject": accept_reject,
                "Results": results,
                "Quality_Inspector": quality_inspector,
                "EPF_Number": epf_number,
                "Digital_Signature": digital_signature,
                "Comments": comments
            }

            save_to_local('quality', record)
            st.success(f"Quality data saved locally! Entry ID: {entry_id}")
            st.experimental_rerun()

        except Exception as e:
            st.error(f"Error saving quality data: {str(e)}")

    # Display local quality entries
    quality_data = st.session_state.get('die_casting_quality', [])
    
    if quality_data:
        st.subheader("Local Quality Entries (Pending Sync)")
        try:
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
            st.experimental_rerun()
    
    refresh_config_if_needed()
    
    downtime_config = read_downtime_config()
    machines = downtime_config["machines"]
    breakdown_reasons = downtime_config["breakdown_reasons"]
    
    available_products = list(st.session_state.cfg.keys())
    
    if not available_products:
        st.error("No products available. Please ask admin to add products first.")
        return
    
    st.write("Fill all machine downtime details below:")
    
    current_time = get_sri_lanka_time()
    st.write(f"**Current Time (Sri Lanka):** {current_time}")
    
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
            values["Duration_Mins"] = int(values.get("Duration_Mins", 0))
            
            record = {
                "User": st.session_state.current_user,
                "EntryID": entry_id,
                "Timestamp": current_time,
                **values,
                "Comments": comments
            }
            
            save_to_local('downtime', record)
            st.success(f"Downtime data saved locally! Entry ID: {entry_id}")
            
        except Exception as e:
            st.error(f"Error saving downtime data: {str(e)}")
    
    if st.button("🔄 Sync Downtime Data Now"):
        sync_with_google_sheets()
        st.experimental_rerun()
    
    downtime_data = st.session_state.get('die_casting_downtime', [])
    if downtime_data:
        st.subheader("Local Downtime Entries (Pending Sync)")
        try:
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


# The rest of the code (Login system, Admin UI, syncing functions, main, etc.) remains unmodified.

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    if st.session_state.get('die_casting_pending_sync', False):
        st.warning("⚠️ Data pending sync with Google Sheets")
        if st.button("🔄 Try to Sync Now"):
            sync_with_google_sheets()
            st.experimental_rerun()

    try:
        if not st.session_state.cfg:
            st.session_state.cfg = get_default_config()

        if not login_system():
            st.info("Please login to access the system")
            return

        if st.session_state.user_role == "Admin":
            admin_ui()
        elif st.session_state.user_role == "Production":
            production_ui()
        elif st.session_state.user_role == "Quality":
            quality_ui()
        elif st.session_state.user_role == "Downtime":
            downtime_ui()
        else:
            production_ui()

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()
