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

# Replace old defaults with your provided downtime reasons
DEFAULT_DOWNTIME_REASONS = [
    "TAM\tTRAPPED Al IN THE MOULD",
    "MOH\tMOULD OVER HEAT",
    "SRR\tSPRAY ROBBOT REPAIR",
    "TWT\tTOTAL WORKED TIME(Mins)",
    "PM\tPLANNED MAINTENANCE",
    "SRA\tSET UP ROBBOT ARM",
    "MA\tMOULD ASSEMBLE",
    "RAR\tROBBOT ARM REPAIR",
    "PC\tPOWER CUT",
    "MB\tMACHINE BREAKDOWN",
    "PI\tPLANING ISSUE",
    "FC\tFURNACE CLEANING",
    "PTC\tPLUNGER TOP CHANGE",
    "MS\tMOULD SETUP",
    "D\tDINING",
    "ERE\tEXTRACTOR ROBOT ERROR",
    "SSR\tSHOT SLEEVE REPLACE",
    "SC\tSTOCK COUNT",
    "PHF\tPRE-HEATING FURNACE",
    "UC\tUNSAFE CONDITION",
    "LLG\tLACK OF LPG GAS",
    "PTS\tPLUNGER TOP STUCK",
    "LRR\tLADLER ROBBOT REPAIR",
    "UF\tUNLOADING FURNACE",
    "PS\tPLANT SHUTDOWN",
    "MTR\tMOULD TEST RUN",
    "ASR\tADJUST THE SPRAY ROBBOT",
    "MAC\tMACHINE CLEANING",
    "EPD\tEJECTOR PIN DAMAGED",
    "MC\tMOULD CHANGE",
    "TDT\tTOTAL DOWN TIME",
    "SRB\tSPRAY ROBBOT BREAKDOWN",
    "LOO\tLACK OF OPERATORS",
    "NRA\tNO RECORDS AVAILABLE",
    "MR\tMOULD REPAIR",
    "MD\tMOULD DAMAGE",
    "FF\tFILLING THE FURNACE",
    "T\tTRAINING",
    "GHD\tGAS HOSE DAMAGE",
    "EF\tELECTRICAL FAULT",
    "LFT\tLOW FURNACE TEMPERATURE",
    "SS\tSHIFT STARTING",
    "SF\tSHIFT FININSHING",
    "SCS\tSCRAPS SHORTAGE",
    "MH\tMOULD HEATING",
    "UM\tUNPLANNED MAINTENANCE",
    "FRB\tFURNACE RELATED BREAKDOWN",
    "CSR\tCOOLING SYSTEM REPAIR",
    "GOS\tGEAR OIL OUT OF STOCK",
    "LOS\tLUBRICANT OUT OF STOCK",
    "MCC\tMOULD CLEANING",
    "PLE\tPLUNGER TOP LUBRICANT ERROR",
    "FU\tFURNACE UNLOADING",
    "MRS\tMOULD RE-SET UP",
    "MCE\tMOULD CLAMP ERROR",
    "PSC\tPLUNGER SLEEVE CLEANING"
]

DEFAULT_SUBTOPICS = [
    "Target Quantity(Planned Shot Count - per Shift and Machine )",
    "Input time",
    "Actual Qty(Actual Shot Count - per shift and Machine)",
    "Slow shot Count (Trial shots during production)",
    "Reject Qty(Reject Point 01 - During production )",
    "Approved Qty"
]

DEFAULT_PROCESS_STEPS = [
    "Inspection",
    "Testing",
    "Final QC",
    "Packaging"
]

DEFAULT_USER_CREDENTIALS = {
    "operator1": "password1",
    "operator2": "password2",
    "operator3": "password3"
}

QUALITY_PASSWORD = "quality123"

# ------------------ Cache Setup ------------------
cache = cachetools.TTLCache(maxsize=100, ttl=30)

# ------------------ Helper Functions ------------------

def get_sri_lanka_time():
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > 30

# ------------------ Google Sheets Functions ------------------

@st.cache_resource(show_spinner=False)
def get_gs_client():
    try:
        if 'gcp_service_account' not in st.secrets:
            st.error("Google Service Account credentials not found in secrets.")
            st.stop()
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_info = st.secrets["gcp_service_account"]
        creds_dict = {k: (v.replace('\\n', '\n') if k == "private_key" else v) for k,v in creds_info.items()}
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {e}")
        st.stop()

@st.cache_resource(show_spinner=False)
def open_spreadsheet(client):
    try:
        name = st.secrets["gsheet"]["spreadsheet_name"]
        return client.open(name)
    except Exception as e:
        st.error(f"Error opening spreadsheet: {e}")
        st.stop()

def get_worksheet(sheet_name):
    cache_key = f"worksheet_{sheet_name}"
    if cache_key in cache:
        return cache[cache_key]
    try:
        ws = st.session_state.spreadsheet.worksheet(sheet_name)
        cache[cache_key] = ws
        return ws
    except gspread.WorksheetNotFound:
        # Create missing sheets with headers and default rows if needed
        ws = None
        if sheet_name == "Config":
            ws = st.session_state.spreadsheet.add_worksheet(title="Config", rows=1000, cols=2)
            headers = [["Product", "Subtopic"]]
            ws.update("A1", headers)
            ws.freeze(rows=1)
        elif sheet_name == "Production_Quality_Records":
            ws = st.session_state.spreadsheet.add_worksheet(title="Production_Quality_Records", rows=2000, cols=50)
            headers = ["RecordType", "EntryID", "Timestamp", "Shift", "Team", "Machine", "Product", "Operator", "Comments"] + DEFAULT_SUBTOPICS
            ws.update("A1", [headers])
            ws.freeze(rows=1)
        elif sheet_name == "Machine_Downtime_Records":
            ws = st.session_state.spreadsheet.add_worksheet(title="Machine_Downtime_Records", rows=2000, cols=20)
            headers = ["EntryID", "Timestamp", "Shift", "Team", "Machine", "Planned_Item", "Downtime_Reason", "Other_Comments", "Duration_Min"]
            ws.update("A1", [headers])
            ws.freeze(rows=1)
        elif sheet_name == "Quality_Records":
            ws = st.session_state.spreadsheet.add_worksheet(title="Quality_Records", rows=2000, cols=50)
            headers = [
                "EntryID", "Timestamp", "Process_Step", "Product", "Total_Lot_Qty", 
                "Sample_Size", "AQL_Level", "Accept_Reject", "Defects_Found", 
                "Results", "Quality_Inspector", "ETF_Number", "Digital_Signature", "Comments"
            ]
            ws.update("A1", [headers])
            ws.freeze(rows=1)
        elif sheet_name == "User_Credentials":
            ws = st.session_state.spreadsheet.add_worksheet(title="User_Credentials", rows=100, cols=3)
            headers = ["Username", "Password", "Role"]
            ws.update("A1", [headers])
            # Add default users
            default_users = [
                ["operator1", "password1", "Operator"],
                ["operator2", "password2", "Operator"],
                ["operator3", "password3", "Operator"]
            ]
            ws.update("A2", default_users)
            ws.freeze(rows=1)
        elif sheet_name == "Downtime_Reasons":
            ws = st.session_state.spreadsheet.add_worksheet(title="Downtime_Reasons", rows=100, cols=1)
            headers = ["Reason"]
            ws.update("A1", [headers])
            # Add new default downtime reasons
            rows = [[reason] for reason in DEFAULT_DOWNTIME_REASONS]
            ws.update("A2", rows)
            ws.freeze(rows=1)
        elif sheet_name == "Process_Steps":
            ws = st.session_state.spreadsheet.add_worksheet(title="Process_Steps", rows=100, cols=1)
            headers = ["Step"]
            ws.update("A1", [headers])
            rows = [[step] for step in DEFAULT_PROCESS_STEPS]
            ws.update("A2", rows)
            ws.freeze(rows=1)
        else:
            st.error(f"Worksheet '{sheet_name}' does not exist and cannot be created automatically.")
            st.stop()
        
        cache[cache_key] = ws
        return ws

def robust_write_worksheet(ws, rows):
    """Write rows to worksheet with retries to handle quota & network issues."""
    try_count = 3
    for attempt in range(try_count):
        try:
            ws.clear()
            ws.update("A1", rows)
            ws.freeze(rows=1)
            cache.clear()
            st.cache_data.clear()
            return True
        except Exception as e:
            if attempt == try_count - 1:
                st.error(f"Error writing to sheet after {try_count} attempts: {e}")
                return False
            time.sleep(2)  # wait before retry

def read_list_from_ws(ws, col=0, skip_header=True):
    try:
        vals = ws.col_values(col + 1)
        if skip_header:
            return vals[1:] if len(vals) > 1 else []
        return vals
    except Exception as e:
        st.error(f"Error reading worksheet data: {e}")
        return []

# Config read/write helpers
def read_config(ws_config):
    try:
        values = ws_config.get_all_values()
        if len(values) < 2:
            return {}
        cfg = {}
        for row in values[1:]:
            if len(row) >= 2:
                product = row[0].strip()
                subtopic = row[1].strip()
                if product and subtopic:
                    cfg.setdefault(product, []).append(subtopic)
        return cfg
    except Exception as e:
        st.error(f"Error reading config: {e}")
        return {}

def write_config(ws_config, config):
    rows = [["Product", "Subtopic"]]
    for product, subtopics in config.items():
        for s in subtopics:
            rows.append([product, s])
    return robust_write_worksheet(ws_config, rows)

# User credentials read/write
def read_user_credentials(ws_credentials):
    try:
        values = ws_credentials.get_all_values()
        if len(values) < 2:
            return DEFAULT_USER_CREDENTIALS.copy()
        creds = {}
        for row in values[1:]:
            if len(row) >= 2:
                username = row[0].strip()
                password = row[1].strip()
                if username and password:
                    creds[username] = password
        return creds
    except Exception as e:
        st.error(f"Error reading user credentials: {e}")
        return DEFAULT_USER_CREDENTIALS.copy()

def write_user_credentials(ws_credentials, creds):
    rows = [["Username", "Password", "Role"]]
    for username, password in creds.items():
        rows.append([username, password, "Operator"])
    return robust_write_worksheet(ws_credentials, rows)

# Downtime reasons read/write
def read_downtime_reasons(ws_reasons):
    reasons = read_list_from_ws(ws_reasons)
    if not reasons:
        reasons = DEFAULT_DOWNTIME_REASONS.copy()
    return reasons

def write_downtime_reasons(ws_reasons, reasons):
    rows = [["Reason"]] + [[r] for r in reasons]
    return robust_write_worksheet(ws_reasons, rows)

# Process steps read/write
def read_process_steps(ws_steps):
    steps = read_list_from_ws(ws_steps)
    if not steps:
        steps = DEFAULT_PROCESS_STEPS.copy()
    return steps

def write_process_steps(ws_steps, steps):
    rows = [["Step"]] + [[s] for s in steps]
    return robust_write_worksheet(ws_steps, rows)

# ------------------ Config Refresh ------------------

def refresh_config_if_needed(ws_config, ws_credentials, ws_reasons, ws_steps):
    if should_refresh_config():
        new_cfg = read_config(ws_config)
        if new_cfg != st.session_state.cfg:
            st.session_state.cfg = new_cfg
        
        new_creds = read_user_credentials(ws_credentials)
        if new_creds != st.session_state.user_credentials:
            st.session_state.user_credentials = new_creds
        
        new_reasons = read_downtime_reasons(ws_reasons)
        if new_reasons != st.session_state.downtime_reasons:
            st.session_state.downtime_reasons = new_reasons
        
        new_steps = read_process_steps(ws_steps)
        if new_steps != st.session_state.process_steps:
            st.session_state.process_steps = new_steps
        
        st.session_state.last_config_update = datetime.now()

# ------------------ Append new records helpers ------------------

def append_record(ws, record):
    try:
        headers = ws.row_values(1)
        row = [record.get(h, "") for h in headers]
        ws.append_row(row, value_input_option="USER_ENTERED")
        cache.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error saving record: {e}")
        return False

# ------------------ Signature Component ------------------

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
    signature = st.text_input("Digital Signature", key="signature_input", placeholder="Enter your full name here", label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)
    return signature

# ------------------ UI Sections ------------------

def admin_ui(ws_config, ws_credentials, ws_reasons, ws_steps):
    st.subheader("Admin Management Panel")
    tabs = st.tabs(["Products & Subtopics", "User Credentials", "Downtime Reasons", "Process Steps", "Quality Team Settings"])
    
    # Products & Subtopics
    with tabs[0]:
        st.subheader("Manage Products & Subtopics")
        refresh_config_if_needed(ws_config, ws_credentials, ws_reasons, ws_steps)
        
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
                        st.experimental_rerun()
        
        if st.session_state.cfg:
            with st.expander("Edit Product"):
                prod = st.selectbox("Select Product", sorted(st.session_state.cfg.keys()), key="edit_product")
                st.caption("Current subtopics:")
                st.write(st.session_state.cfg[prod])
                
                new_sub = st.text_input("Add Subtopic", key="new_subtopic")
                if st.button("Add Subtopic to Product"):
                    if new_sub.strip():
                        st.session_state.cfg[prod].append(new_sub.strip())
                        if write_config(ws_config, st.session_state.cfg):
                            st.success(f"Added '{new_sub}' to {prod}.")
                            st.experimental_rerun()
                
                subs_to_remove = st.multiselect("Remove subtopics", st.session_state.cfg[prod], key="remove_subtopics")
                if st.button("Remove Selected Subtopics"):
                    if subs_to_remove:
                        st.session_state.cfg[prod] = [s for s in st.session_state.cfg[prod] if s not in subs_to_remove]
                        if write_config(ws_config, st.session_state.cfg):
                            st.warning(f"Removed: {', '.join(subs_to_remove)}")
                            st.experimental_rerun()
            
            with st.expander("Delete Product"):
                prod_del = st.selectbox("Choose product to delete", sorted(st.session_state.cfg.keys()), key="delete_product")
                if st.button("Delete Product Permanently"):
                    del st.session_state.cfg[prod_del]
                    if write_config(ws_config, st.session_state.cfg):
                        st.error(f"Deleted product '{prod_del}' and its subtopics.")
                        st.experimental_rerun()

        st.divider()
        st.subheader("Current Products Configuration")
        st.json(st.session_state.cfg)
    
    # User Credentials
    with tabs[1]:
        st.subheader("Manage User Credentials")
        st.write("Current Users:")
        for username, password in st.session_state.user_credentials.items():
            st.write(f"- {username}: {password}")
        with st.expander("Add/Edit User"):
            username = st.text_input("Username", key="edit_username")
            password = st.text_input("Password", type="password", key="edit_password")
            if st.button("Save User Credentials"):
                if username and password:
                    st.session_state.user_credentials[username] = password
                    if write_user_credentials(ws_credentials, st.session_state.user_credentials):
                        st.success(f"Credentials updated for {username}")
                        st.experimental_rerun()
        with st.expander("Remove User"):
            user_to_remove = st.selectbox("Select user to remove", list(st.session_state.user_credentials.keys()), key="remove_user")
            if st.button("Remove User"):
                if user_to_remove in st.session_state.user_credentials:
                    del st.session_state.user_credentials[user_to_remove]
                    if write_user_credentials(ws_credentials, st.session_state.user_credentials):
                        st.warning(f"Removed user: {user_to_remove}")
                        st.experimental_rerun()

    # Downtime Reasons
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
                        st.experimental_rerun()
        with st.expander("Remove Downtime Reason"):
            reason_to_remove = st.selectbox("Select reason to remove", st.session_state.downtime_reasons, key="remove_reason")
            if st.button("Remove Reason"):
                if reason_to_remove in st.session_state.downtime_reasons:
                    st.session_state.downtime_reasons.remove(reason_to_remove)
                    if write_downtime_reasons(ws_reasons, st.session_state.downtime_reasons):
                        st.warning(f"Removed reason: {reason_to_remove}")
                        st.experimental_rerun()

    # Process Steps
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
                        st.experimental_rerun()
        with st.expander("Remove Process Step"):
            step_to_remove = st.selectbox("Select step to remove", st.session_state.process_steps, key="remove_step")
            if st.button("Remove Step"):
                if step_to_remove in st.session_state.process_steps:
                    st.session_state.process_steps.remove(step_to_remove)
                    if write_process_steps(ws_steps, st.session_state.process_steps):
                        st.warning(f"Removed step: {step_to_remove}")
                        st.experimental_rerun()
        with st.expander("Edit Process Steps"):
            st.write("Edit existing process steps:")
            edited_steps = []
            for i, step in enumerate(st.session_state.process_steps):
                edited_step = st.text_input(f"Process Step {i+1}", value=step, key=f"edit_step_{i}")
                edited_steps.append(edited_step)
            if st.button("Save All Process Steps"):
                cleaned_steps = list(dict.fromkeys([step.strip() for step in edited_steps if step.strip()]))
                if cleaned_steps:
                    st.session_state.process_steps = cleaned_steps
                    if write_process_steps(ws_steps, st.session_state.process_steps):
                        st.success("All process steps updated successfully!")
                        st.experimental_rerun()

    # Quality Team Settings Tab
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
                for step in DEFAULT_PROCESS_STEPS:
                    if step not in st.session_state.process_steps:
                        st.session_state.process_steps.append(step)
                if write_process_steps(ws_steps, st.session_state.process_steps):
                    st.success("Default process steps added!")
                    st.experimental_rerun()
            if st.button("Clear All Process Steps"):
                st.session_state.process_steps = []
                if write_process_steps(ws_steps, st.session_state.process_steps):
                    st.warning("All process steps cleared!")
                    st.experimental_rerun()
        st.divider()
        st.write("**Quality Section Password:**")
        st.write(f"Current Password: `{QUALITY_PASSWORD}`")
        st.info("To change the password, modify the QUALITY_PASSWORD variable in the code")
        st.divider()
        st.write("**Add Multiple Process Steps:**")
        multiple_steps = st.text_area("Enter multiple process steps (one per line):", height=100, help="Enter each process step on a separate line")
        if st.button("Add Multiple Steps"):
            if multiple_steps.strip():
                new_steps = [step.strip() for step in multiple_steps.split('\n') if step.strip()]
                for step in new_steps:
                    if step not in st.session_state.process_steps:
                        st.session_state.process_steps.append(step)
                if write_process_steps(ws_steps, st.session_state.process_steps):
                    st.success(f"Added {len(new_steps)} new process steps!")
                    st.experimental_rerun()

    # Manual config refresh button
    if st.button("🔄 Refresh All Configuration"):
        st.session_state.last_config_update = None
        cache.clear()
        st.cache_data.clear()
        st.experimental_rerun()

# ------------------ Production Records UI ------------------

def production_records_ui(ws_config, ws_production, ws_credentials):
    st.subheader("Production Records")
    
    if not st.session_state.production_password_entered:
        username = st.selectbox("Username", list(st.session_state.user_credentials.keys()), key="production_username")
        password = st.text_input("Password", type="password", key="production_password")
        if st.button("Login", key="production_login"):
            if username in st.session_state.user_credentials and st.session_state.user_credentials[username] == password:
                st.session_state.production_password_entered = True
                st.session_state.current_user = username
                st.experimental_rerun()
            else:
                st.error("Invalid password")
        return
    
    st.success(f"Logged in as: {st.session_state.current_user}")
    if st.button("Logout", key="production_logout"):
        st.session_state.production_password_entered = False
        st.session_state.current_user = None
        st.experimental_rerun()

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

    for subtopic in current_subtopics:
        if any(x in subtopic.lower() for x in ["quantity", "qty", "count"]):
            values[subtopic] = st.number_input(subtopic, min_value=0, step=1, key=f"num_{subtopic}")
        elif "time" in subtopic.lower():
            values[subtopic] = st.text_input(subtopic, value=get_sri_lanka_time(), key=f"time_{subtopic}")
        else:
            values[subtopic] = st.text_input(subtopic, key=f"text_{subtopic}")

    comments = st.text_area("Comments", key="production_comments")

    if st.button("Submit Production Record", key="submit_production_btn"):
        required_fields = [st for st in current_subtopics if ("quantity" in st.lower() or "qty" in st.lower() or "count" in st.lower()) and "slow" not in st.lower() and "reject" not in st.lower()]
        missing_fields = [f for f in required_fields if not values.get(f)]
        if missing_fields:
            st.error(f"Please fill in all required fields: {', '.join(missing_fields)}")
        else:
            entry_id = uuid.uuid4().hex
            record = {
                "RecordType": "Production",
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "Shift": shift,
                "Team": team,
                "Machine": machine,
                "Product": product,
                "Operator": st.session_state.current_user,
                **values,
                "Comments": comments
            }
            if append_record(ws_production, record):
                st.success(f"Production Record Saved! EntryID: {entry_id}")
            else:
                st.error("Failed to save production record.")

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

    planned_item = st.selectbox("Planned Item", sorted(st.session_state.cfg.keys()), key="planned_item")

    downtime_reason = st.selectbox("Downtime Reason", st.session_state.downtime_reasons, key="downtime_reason")
    other_comments = st.text_area("Other Comments", key="downtime_comments")
    duration_min = st.number_input("Duration (Min)", min_value=1, step=1, key="duration_min")

    if st.button("Submit Downtime Record", key="submit_downtime_btn"):
        if not other_comments.strip():
            st.error("Comments cannot be empty.")
        elif duration_min <= 0:
            st.error("Duration must be greater than 0.")
        else:
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
            if append_record(ws_downtime, record):
                st.success(f"Downtime Record Saved! EntryID: {entry_id}")
            else:
                st.error("Failed to save downtime record.")

# ------------------ Quality Records UI ------------------

def quality_records_ui(ws_quality, ws_config, ws_steps):
    st.subheader("Quality Team Records")

    if not st.session_state.quality_password_entered:
        st.info("Please enter the quality team password to access this section")
        quality_pw = st.text_input("Quality Team Password", type="password", key="quality_password")
        if st.button("Authenticate", key="quality_auth_btn"):
            if quality_pw == QUALITY_PASSWORD:
                st.session_state.quality_password_entered = True
                st.experimental_rerun()
            else:
                st.error("Incorrect password. Please try again.")
        return

    st.success("✓ Authenticated as Quality Team Member")
    if st.button("Logout from Quality", key="quality_logout_btn"):
        st.session_state.quality_password_entered = False
        st.experimental_rerun()

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

    st.subheader("Digital Signature")
    digital_signature = signature_canvas()

    comments = st.text_area("Comments", key="quality_comments")

    if st.button("Submit Quality Record", key="submit_quality_btn"):
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
            if append_record(ws_quality, record):
                st.success(f"Quality Record Saved! EntryID: {entry_id}")
            else:
                st.error("Failed to save quality record.")

# ------------------ Main UI ------------------

def main_ui(ws_config, ws_production, ws_downtime, ws_quality, ws_credentials, ws_reasons, ws_steps):
    st.title(APP_TITLE)
    st.sidebar.header("Navigation")

    section = st.sidebar.radio(
        "Select Section", 
        ["Production Records", "Machine Downtime Records", "Quality Team Records"],
        key="section_selector"
    )
    st.sidebar.markdown(f"**Current Mode:** {section}")

    if section == "Production Records":
        production_records_ui(ws_config, ws_production, ws_credentials)
    elif section == "Machine Downtime Records":
        downtime_records_ui(ws_downtime, ws_config, ws_reasons)
    elif section == "Quality Team Records":
        quality_records_ui(ws_quality, ws_config, ws_steps)

# ------------------ Main Function ------------------

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")

    if st.session_state.gs_client is None:
        with st.spinner("Connecting to Google Sheets..."):
            st.session_state.gs_client = get_gs_client()
            st.session_state.spreadsheet = open_spreadsheet(st.session_state.gs_client)

    ws_config = get_worksheet("Config")
    ws_production = get_worksheet("Production_Quality_Records")
    ws_downtime = get_worksheet("Machine_Downtime_Records")
    ws_quality = get_worksheet("Quality_Records")
    ws_credentials = get_worksheet("User_Credentials")
    ws_reasons = get_worksheet("Downtime_Reasons")
    ws_steps = get_worksheet("Process_Steps")

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
            main_ui(ws_config, ws_production, ws_downtime, ws_quality, ws_credentials, ws_reasons, ws_steps)
    else:
        main_ui(ws_config, ws_production, ws_downtime, ws_quality, ws_credentials, ws_reasons, ws_steps)

if __name__ == "__main__":
    main()
