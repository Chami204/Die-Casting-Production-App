import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz
import time

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production System"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')
AUTO_REFRESH_SECONDS = 20

# Default configurations for different modules
DEFAULT_PRODUCTION_SUBTOPICS = [
    "Input number of pcs",
    "Input time",
    "Output number of pcs",
    "Output time",
    "Num of pcs to rework",
    "Number of rejects"
]

DEFAULT_QUALITY_FIELDS = [
    "Process_Step", "Product", "Total_Lot_Qty", "Sample_Size", "AQL_Level",
    "Accept_Reject", "Defects_Found", "Results", "Quality_Inspector",
    "ETF_Number", "Digital_Signature", "Comments"
]

DEFAULT_DOWNTIME_FIELDS = [
    "Shift", "Team", "Machine", "Planned_Item", "Downtime_Reason",
    "Duration_Min", "Other_Comments"
]

DEFAULT_USER_FIELDS = [
    "Name", "Password", "Role", "Department"
]

# ------------------ Initialize Session State ------------------
if 'production_cfg' not in st.session_state:
    st.session_state.production_cfg = {}
if 'quality_cfg' not in st.session_state:
    st.session_state.quality_cfg = {}
if 'downtime_cfg' not in st.session_state:
    st.session_state.downtime_cfg = {}
if 'users_cfg' not in st.session_state:
    st.session_state.users_cfg = {}
if 'last_config_update' not in st.session_state:
    st.session_state.last_config_update = None
if 'editing_entry' not in st.session_state:
    st.session_state.editing_entry = None
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# ------------------ Helper Functions ------------------
def get_sri_lanka_time():
    """Get current time in Sri Lanka timezone"""
    return datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)

def should_refresh_config():
    """Check if config should be refreshed"""
    if st.session_state.last_config_update is None:
        return True
    return (datetime.now() - st.session_state.last_config_update).total_seconds() > AUTO_REFRESH_SECONDS

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
    # Production Config sheet
    try:
        ws_production_config = sh.worksheet("Production_Config")
    except gspread.WorksheetNotFound:
        ws_production_config = sh.add_worksheet(title="Production_Config", rows=1000, cols=2)
        rows = [["Product", "Subtopic"]]
        ws_production_config.update("A1", rows)
        ws_production_config.freeze(rows=1)

    # Production History sheet
    try:
        ws_production_history = sh.worksheet("Production_History")
    except gspread.WorksheetNotFound:
        ws_production_history = sh.add_worksheet(title="Production_History", rows=2000, cols=50)
        headers = ["EntryID", "Timestamp", "User", "Product", "Comments"] + DEFAULT_PRODUCTION_SUBTOPICS
        ws_production_history.update("A1", [headers])
        ws_production_history.freeze(rows=1)

    # Quality Config sheet
    try:
        ws_quality_config = sh.worksheet("Quality_Config")
    except gspread.WorksheetNotFound:
        ws_quality_config = sh.add_worksheet(title="Quality_Config", rows=1000, cols=2)
        rows = [["Field", "Type"]]
        ws_quality_config.update("A1", rows)
        ws_quality_config.freeze(rows=1)

    # Quality History sheet
    try:
        ws_quality_history = sh.worksheet("Quality_History")
    except gspread.WorksheetNotFound:
        ws_quality_history = sh.add_worksheet(title="Quality_History", rows=2000, cols=50)
        headers = ["EntryID", "Timestamp", "User"] + DEFAULT_QUALITY_FIELDS
        ws_quality_history.update("A1", [headers])
        ws_quality_history.freeze(rows=1)

    # Downtime Config sheet
    try:
        ws_downtime_config = sh.worksheet("Downtime_Config")
    except gspread.WorksheetNotFound:
        ws_downtime_config = sh.add_worksheet(title="Downtime_Config", rows=1000, cols=2)
        rows = [["Field", "Type"]]
        ws_downtime_config.update("A1", rows)
        ws_downtime_config.freeze(rows=1)

    # Downtime History sheet
    try:
        ws_downtime_history = sh.worksheet("Downtime_History")
    except gspread.WorksheetNotFound:
        ws_downtime_history = sh.add_worksheet(title="Downtime_History", rows=2000, cols=50)
        headers = ["EntryID", "Timestamp", "User"] + DEFAULT_DOWNTIME_FIELDS
        ws_downtime_history.update("A1", [headers])
        ws_downtime_history.freeze(rows=1)

    # Users Config sheet
    try:
        ws_users_config = sh.worksheet("Users_Config")
    except gspread.WorksheetNotFound:
        ws_users_config = sh.add_worksheet(title="Users_Config", rows=1000, cols=4)
        headers = DEFAULT_USER_FIELDS
        ws_users_config.update("A1", [headers])
        ws_users_config.freeze(rows=1)

    return {
        'production_config': ws_production_config,
        'production_history': ws_production_history,
        'quality_config': ws_quality_config,
        'quality_history': ws_quality_history,
        'downtime_config': ws_downtime_config,
        'downtime_history': ws_downtime_history,
        'users_config': ws_users_config
    }

# ------------------ Config helpers ------------------
def read_production_config(ws_config):
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
        st.error(f"Error reading production config: {str(e)}")
        return {}

def read_general_config(ws_config, default_fields):
    try:
        values = ws_config.get_all_records()
        cfg = {}
        for row in values:
            field = str(row.get("Field", "")).strip()
            field_type = str(row.get("Type", "")).strip()
            if not field:
                continue
            cfg[field] = field_type
        return cfg
    except Exception as e:
        st.error(f"Error reading config: {str(e)}")
        return {field: "text" for field in default_fields}

def read_users_config(ws_config):
    try:
        values = ws_config.get_all_records()
        users = {}
        for row in values:
            name = str(row.get("Name", "")).strip()
            password = str(row.get("Password", "")).strip()
            role = str(row.get("Role", "")).strip()
            department = str(row.get("Department", "")).strip()
            if name and password:
                users[name] = {
                    "password": password,
                    "role": role,
                    "department": department
                }
        return users
    except Exception as e:
        st.error(f"Error reading users config: {str(e)}")
        return {}

def write_production_config(ws_config, cfg: dict):
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
        st.error(f"Error writing production config: {str(e)}")
        return False

def write_general_config(ws_config, cfg: dict):
    try:
        rows = [["Field", "Type"]]
        for field, field_type in cfg.items():
            rows.append([field, field_type])
        ws_config.clear()
        ws_config.update("A1", rows)
        ws_config.freeze(rows=1)
        return True
    except Exception as e:
        st.error(f"Error writing config: {str(e)}")
        return False

def write_users_config(ws_config, users: dict):
    try:
        rows = [DEFAULT_USER_FIELDS]
        for name, user_data in users.items():
            rows.append([
                name,
                user_data.get("password", ""),
                user_data.get("role", ""),
                user_data.get("department", "")
            ])
        ws_config.clear()
        ws_config.update("A1", rows)
        ws_config.freeze(rows=1)
        return True
    except Exception as e:
        st.error(f"Error writing users config: {str(e)}")
        return False

def refresh_all_configs(worksheets):
    """Refresh all configurations from Google Sheets"""
    st.session_state.production_cfg = read_production_config(worksheets['production_config'])
    st.session_state.quality_cfg = read_general_config(worksheets['quality_config'], DEFAULT_QUALITY_FIELDS)
    st.session_state.downtime_cfg = read_general_config(worksheets['downtime_config'], DEFAULT_DOWNTIME_FIELDS)
    st.session_state.users_cfg = read_users_config(worksheets['users_config'])
    st.session_state.last_config_update = datetime.now()

def refresh_config_if_needed(worksheets):
    """Refresh config from Google Sheets if needed"""
    if should_refresh_config():
        refresh_all_configs(worksheets)

# ------------------ History helpers ------------------
def ensure_history_headers(ws_history, headers):
    current_headers = ws_history.row_values(1)
    if set(current_headers) != set(headers):
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)
    return headers

def append_history(ws_history, record: dict, headers: list):
    ensure_history_headers(ws_history, headers)
    row = [record.get(h, "") for h in headers]
    ws_history.append_row(row, value_input_option="USER_ENTERED")

def get_recent_entries(ws_history, limit: int = 50) -> pd.DataFrame:
    try:
        values = ws_history.get_all_records()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values)
        return df.sort_values(by="Timestamp", ascending=False).head(limit)
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        return pd.DataFrame()

def update_entry(ws_history, entry_id: str, updated_data: dict, headers: list):
    """Update an existing entry in the history sheet"""
    try:
        # Find the row with the matching EntryID
        cell = ws_history.find(entry_id)
        if not cell:
            st.error("Entry not found.")
            return False
        
        # Prepare the updated row
        updated_row = []
        for header in headers:
            if header in updated_data:
                updated_row.append(updated_data[header])
            else:
                # Get the existing value for this header
                existing_value = ws_history.cell(cell.row, headers.index(header) + 1).value
                updated_row.append(existing_value)
        
        # Update the row
        ws_history.update(f"A{cell.row}", [updated_row], value_input_option="USER_ENTERED")
        return True
        
    except Exception as e:
        st.error(f"Error updating entry: {str(e)}")
        return False

def find_entry_by_id(ws_history, entry_id: str, headers: list) -> dict:
    """Find an entry by its ID and return as dictionary"""
    try:
        cell = ws_history.find(entry_id)
        if not cell:
            return None
        
        row_values = ws_history.row_values(cell.row)
        
        entry_data = {}
        for i, header in enumerate(headers):
            if i < len(row_values):
                entry_data[header] = row_values[i]
            else:
                entry_data[header] = ""
        
        return entry_data
    except Exception as e:
        st.error(f"Error finding entry: {str(e)}")
        return None

# ------------------ Login System ------------------
def login_system():
    st.sidebar.header("User Login")
    
    if st.session_state.logged_in:
        st.sidebar.success(f"Logged in as: {st.session_state.current_user}")
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.current_user = None
            st.rerun()
        return True
    
    username = st.sidebar.selectbox("Username", options=[""] + list(st.session_state.users_cfg.keys()))
    password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Login"):
        if username in st.session_state.users_cfg and st.session_state.users_cfg[username]["password"] == password:
            st.session_state.logged_in = True
            st.session_state.current_user = username
            st.sidebar.success("Login successful!")
            st.rerun()
        else:
            st.sidebar.error("Invalid username or password")
    
    return st.session_state.logged_in

# ------------------ Admin UI ------------------
def admin_ui(worksheets):
    st.header("Admin Panel")
    
    # Auto-refresh config to see changes from other devices
    refresh_config_if_needed(worksheets)

    tab1, tab2, tab3, tab4 = st.tabs([
        "Production Data", 
        "Machine Downtime", 
        "Quality Reports", 
        "User Credentials"
    ])

    with tab1:
        st.subheader("Manage Products & Subtopics")
        
        # Create new product
        with st.expander("Create New Product"):
            new_product = st.text_input("New Product Name", key="new_product")
            if st.button("Create Product"):
                if not new_product.strip():
                    st.warning("Enter a valid product name.")
                elif new_product in st.session_state.production_cfg:
                    st.warning("That product already exists.")
                else:
                    st.session_state.production_cfg[new_product] = DEFAULT_PRODUCTION_SUBTOPICS.copy()
                    if write_production_config(worksheets['production_config'], st.session_state.production_cfg):
                        st.success(f"Product '{new_product}' created with default subtopics.")
                        st.rerun()

        # Edit existing product
        if st.session_state.production_cfg:
            with st.expander("Edit Product"):
                prod = st.selectbox("Select Product", sorted(st.session_state.production_cfg.keys()), key="edit_product")
                st.caption("Current subtopics:")
                st.write(st.session_state.production_cfg[prod])

                # Add new subtopic
                new_sub = st.text_input("Add Subtopic", key="new_subtopic")
                if st.button("Add Subtopic to Product"):
                    if new_sub.strip():
                        st.session_state.production_cfg[prod].append(new_sub.strip())
                        if write_production_config(worksheets['production_config'], st.session_state.production_cfg):
                            st.success(f"Added '{new_sub}' to {prod}.")
                            st.rerun()

                # Remove subtopics
                subs_to_remove = st.multiselect("Remove subtopics", st.session_state.production_cfg[prod], key="remove_subtopics")
                if st.button("Remove Selected Subtopics"):
                    if subs_to_remove:
                        st.session_state.production_cfg[prod] = [s for s in st.session_state.production_cfg[prod] if s not in subs_to_remove]
                        if write_production_config(worksheets['production_config'], st.session_state.production_cfg):
                            st.warning(f"Removed: {', '.join(subs_to_remove)}")
                            st.rerun()

            # Delete product
            with st.expander("Delete Product"):
                prod_del = st.selectbox("Choose product to delete", sorted(st.session_state.production_cfg.keys()), key="delete_product")
                if st.button("Delete Product Permanently"):
                    del st.session_state.production_cfg[prod_del]
                    if write_production_config(worksheets['production_config'], st.session_state.production_cfg):
                        st.error(f"Deleted product '{prod_del}' and its subtopics.")
                        st.rerun()

    with tab2:
        st.subheader("Machine Downtime Configuration")
        st.info("Configure downtime reasons and fields. Changes made directly in Google Sheets will be reflected here.")
        
        st.write("Current Downtime Configuration:")
        st.json(st.session_state.downtime_cfg)

    with tab3:
        st.subheader("Quality Reports Configuration")
        st.info("Configure quality report fields. Changes made directly in Google Sheets will be reflected here.")
        
        st.write("Current Quality Configuration:")
        st.json(st.session_state.quality_cfg)

    with tab4:
        st.subheader("User Credentials Management")
        
        # Add new user
        with st.expander("Add New User"):
            new_name = st.text_input("Full Name", key="new_user_name")
            new_password = st.text_input("Password", type="password", key="new_user_password")
            new_role = st.selectbox("Role", ["Operator", "Supervisor", "Quality Inspector", "Admin"], key="new_user_role")
            new_department = st.text_input("Department", key="new_user_department")
            
            if st.button("Add User"):
                if new_name and new_password:
                    st.session_state.users_cfg[new_name] = {
                        "password": new_password,
                        "role": new_role,
                        "department": new_department
                    }
                    if write_users_config(worksheets['users_config'], st.session_state.users_cfg):
                        st.success(f"User '{new_name}' added successfully!")
                        st.rerun()
                else:
                    st.warning("Please provide both name and password.")

        # Manage existing users
        with st.expander("Manage Existing Users"):
            if st.session_state.users_cfg:
                user_to_edit = st.selectbox("Select User", options=list(st.session_state.users_cfg.keys()))
                
                if user_to_edit:
                    user_data = st.session_state.users_cfg[user_to_edit]
                    new_password = st.text_input("New Password", value=user_data["password"], type="password", key=f"edit_{user_to_edit}_pw")
                    new_role = st.selectbox("Role", ["Operator", "Supervisor", "Quality Inspector", "Admin"], 
                                          index=["Operator", "Supervisor", "Quality Inspector", "Admin"].index(user_data["role"]) 
                                          if user_data["role"] in ["Operator", "Supervisor", "Quality Inspector", "Admin"] else 0,
                                          key=f"edit_{user_to_edit}_role")
                    new_department = st.text_input("Department", value=user_data["department"], key=f"edit_{user_to_edit}_dept")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Update User"):
                            st.session_state.users_cfg[user_to_edit] = {
                                "password": new_password,
                                "role": new_role,
                                "department": new_department
                            }
                            if write_users_config(worksheets['users_config'], st.session_state.users_cfg):
                                st.success(f"User '{user_to_edit}' updated successfully!")
                                st.rerun()
                    
                    with col2:
                        if st.button("Delete User"):
                            del st.session_state.users_cfg[user_to_edit]
                            if write_users_config(worksheets['users_config'], st.session_state.users_cfg):
                                st.error(f"User '{user_to_edit}' deleted!")
                                st.rerun()

    # Manual refresh button
    if st.button("🔄 Refresh All Configurations"):
        refresh_all_configs(worksheets)
        st.success("All configurations refreshed!")
        st.rerun()

# ------------------ Production Data UI ------------------
def production_data_ui(worksheets):
    st.header("Production Data Entry")
    
    # Manual refresh button
    if st.button("🔄 Refresh Production Data"):
        refresh_config_if_needed(worksheets)
        st.rerun()

    if not st.session_state.production_cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    product = st.selectbox("Select Main Product", sorted(st.session_state.production_cfg.keys()), key="user_product")
    current_subtopics = st.session_state.production_cfg.get(product, DEFAULT_PRODUCTION_SUBTOPICS.copy())
    
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

    if st.button("Submit Production Data", key="submit_production_btn"):
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
                    "User": st.session_state.current_user,
                    "Product": product,
                    **values,
                    "Comments": comments
                }
                
                headers = ["EntryID", "Timestamp", "User", "Product", "Comments"] + current_subtopics
                append_history(worksheets['production_history'], record, headers)
                st.success(f"Production data saved! EntryID: {entry_id}")
            except Exception as e:
                st.error(f"Error saving production data: {str(e)}")

    # Display recent production entries
    df = get_recent_entries(worksheets['production_history'])
    if not df.empty:
        st.subheader("Recent Production Entries")
        st.dataframe(df.head(10))

# ------------------ Quality Record UI ------------------
def quality_record_ui(worksheets):
    st.header("Quality Record Entry")
    
    if st.button("🔄 Refresh Quality Data"):
        refresh_config_if_needed(worksheets)
        st.rerun()

    # Get available products from production config
    available_products = list(st.session_state.production_cfg.keys())
    
    values = {}
    col1, col2 = st.columns(2)
    
    with col1:
        values["Process_Step"] = st.text_input("Process Step", key="process_step")
        values["Product"] = st.selectbox("Product", options=available_products, key="quality_product")
        values["Total_Lot_Qty"] = st.number_input("Total Lot Quantity", min_value=1, step=1, key="total_lot_qty")
        values["Sample_Size"] = st.number_input("Sample Size", min_value=1, step=1, key="sample_size")
        values["AQL_Level"] = st.text_input("AQL Level", key="aql_level")
        values["Accept_Reject"] = st.selectbox("Accept/Reject", options=["Accept", "Reject"], key="accept_reject")
    
    with col2:
        values["Defects_Found"] = st.number_input("Defects Found", min_value=0, step=1, key="defects_found")
        values["Results"] = st.text_input("Results", key="results")
        values["Quality_Inspector"] = st.text_input("Quality Inspector", key="quality_inspector")
        values["ETF_Number"] = st.text_input("ETF Number", key="etf_number")
        values["Digital_Signature"] = st.text_input("Digital Signature", key="digital_signature")
        values["Comments"] = st.text_area("Comments", key="quality_comments")

    if st.button("Submit Quality Record", key="submit_quality_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "User": st.session_state.current_user,
                **values
            }
            
            headers = ["EntryID", "Timestamp", "User"] + DEFAULT_QUALITY_FIELDS
            append_history(worksheets['quality_history'], record, headers)
            st.success(f"Quality record saved! EntryID: {entry_id}")
        except Exception as e:
            st.error(f"Error saving quality record: {str(e)}")

    # Display recent quality entries
    df = get_recent_entries(worksheets['quality_history'])
    if not df.empty:
        st.subheader("Recent Quality Records")
        st.dataframe(df.head(10))

# ------------------ Machine Downtime UI ------------------
def machine_downtime_ui(worksheets):
    st.header("Machine Downtime Entry")
    
    if st.button("🔄 Refresh Downtime Data"):
        refresh_config_if_needed(worksheets)
        st.rerun()

    values = {}
    col1, col2 = st.columns(2)
    
    with col1:
        values["Shift"] = st.selectbox("Shift", options=["A", "B", "C"], key="shift")
        values["Team"] = st.text_input("Team", key="team")
        values["Machine"] = st.text_input("Machine", key="machine")
        values["Planned_Item"] = st.text_input("Planned Item", key="planned_item")
    
    with col2:
        values["Downtime_Reason"] = st.text_input("Downtime Reason", key="downtime_reason")
        values["Duration_Min"] = st.number_input("Duration (Minutes)", min_value=1, step=1, key="duration_min")
        values["Other_Comments"] = st.text_area("Other Comments", key="other_comments")

    if st.button("Submit Downtime Record", key="submit_downtime_btn"):
        try:
            entry_id = uuid.uuid4().hex
            record = {
                "EntryID": entry_id,
                "Timestamp": get_sri_lanka_time(),
                "User": st.session_state.current_user,
                **values
            }
            
            headers = ["EntryID", "Timestamp", "User"] + DEFAULT_DOWNTIME_FIELDS
            append_history(worksheets['downtime_history'], record, headers)
            st.success(f"Downtime record saved! EntryID: {entry_id}")
        except Exception as e:
            st.error(f"Error saving downtime record: {str(e)}")

    # Display recent downtime entries
    df = get_recent_entries(worksheets['downtime_history'])
    if not df.empty:
        st.subheader("Recent Downtime Records")
        st.dataframe(df.head(10))

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🏭", layout="wide")
    st.title(APP_TITLE)

    try:
        client = get_gs_client()
        sh = open_spreadsheet(client)
        worksheets = ensure_worksheets(sh)
        
        # Read all configs from Google Sheets at startup
        if not st.session_state.production_cfg:
            refresh_all_configs(worksheets)

        # Auto-refresh placeholder
        refresh_placeholder = st.empty()
        if should_refresh_config():
            with refresh_placeholder:
                if st.button("🔄 Auto-refresh data"):
                    refresh_all_configs(worksheets)
                    st.rerun()

        # Login system
        if not login_system():
            st.info("Please login to access the system")
            return

        # Navigation based on user role
        user_role = st.session_state.users_cfg.get(st.session_state.current_user, {}).get("role", "Operator")
        
        if user_role == "Admin":
            tabs = st.tabs(["Admin", "Production Data", "Quality Record", "Machine Downtime"])
            with tabs[0]:
                admin_ui(worksheets)
            with tabs[1]:
                production_data_ui(worksheets)
            with tabs[2]:
                quality_record_ui(worksheets)
            with tabs[3]:
                machine_downtime_ui(worksheets)
        else:
            # Regular users see only relevant tabs based on role
            if user_role == "Quality Inspector":
                tabs = st.tabs(["Quality Record", "Production Data"])
                with tabs[0]:
                    quality_record_ui(worksheets)
                with tabs[1]:
                    production_data_ui(worksheets)
            else:
                tabs = st.tabs(["Production Data", "Machine Downtime"])
                with tabs[0]:
                    production_data_ui(worksheets)
                with tabs[1]:
                    machine_downtime_ui(worksheets)

    except Exception as e:
        st.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()
