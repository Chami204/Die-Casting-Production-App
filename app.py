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


# ------------------ User Management ------------------
def read_users_config(ws_users):
    """Read users from Google Sheets"""
    try:
        values = ws_users.get_all_records()
        users = {}
        for row in values:
            username = str(row.get("Username", "")).strip()
            password = str(row.get("Password", "")).strip()
            role = str(row.get("Role", "")).strip()
            if username and password:
                users[username] = {
                    "password": password,
                    "role": role
                }
        return users
    except Exception as e:
        st.error(f"Error reading users config: {str(e)}")
        return {}

def write_users_config(ws_users, users: dict):
    """Write users to Google Sheets"""
    try:
        rows = [["Username", "Password", "Role"]]
        for username, user_data in users.items():
            rows.append([
                username,
                user_data.get("password", ""),
                user_data.get("role", "")
            ])
        ws_users.clear()
        ws_users.update("A1", rows)
        return True
    except Exception as e:
        st.error(f"Error writing users config: {str(e)}")
        return False

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
    # Production Config sheet
    try:
        ws_config = sh.worksheet("Production_Config")
    except gspread.WorksheetNotFound:
        ws_config = sh.add_worksheet(title="Production_Config", rows=1000, cols=2)
        rows = [["Product", "Subtopic"]]
        ws_config.update("A1", rows)
        ws_config.freeze(rows=1)

    # Quality Config sheet
    try:
        ws_quality_config = sh.worksheet("Quality_Config")
    except gspread.WorksheetNotFound:
        ws_quality_config = sh.add_worksheet(title="Quality_Config", rows=1000, cols=2)
        rows = [["Field", "Type"]]
        ws_quality_config.update("A1", rows)
        ws_quality_config.freeze(rows=1)

    # Users Config sheet
    try:
        ws_users = sh.worksheet("User_Credentials")
    except gspread.WorksheetNotFound:
        ws_users = sh.add_worksheet(title="User_Credentials", rows=1000, cols=3)
        rows = [["Username", "Password", "Role"]]
        ws_users.update("A1", rows)
        ws_users.freeze(rows=1)

    # History sheet
    try:
        ws_history = sh.worksheet("History")
        headers = ws_history.row_values(1)
        if "User" not in headers:
            new_headers = ["User"] + headers
            ws_history.update("A1", [new_headers])
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title = "History", rows=2000, cols=50)
        headers = ["User", "EntryID", "Timestamp", "Product", "Comments"] + DEFAULT_SUBTOPICS
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)

    # Quality History sheet
    try:
        ws_quality_history = sh.worksheet("Quality_History")
    except gspread.WorksheetNotFound:
        ws_quality_history = sh.add_worksheet(title="Quality_History", rows=2000, cols=50)
        headers = ["User", "EntryID", "Timestamp", "Product"] + QUALITY_DEFAULT_FIELDS
        ws_quality_history.update("A1", [headers])
        ws_quality_history.freeze(rows=1)

    return ws_config, ws_history, ws_users, ws_quality_config, ws_quality_history

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

def add_product_with_default_subtopics(ws_config, product_name):
    """Add a new product with all default subtopics"""
    if not product_name.strip():
        return False, "Product name cannot be empty"
    
    if product_name in st.session_state.cfg:
        return False, "Product already exists"
    
    # Add the product with all default subtopics
    st.session_state.cfg[product_name] = DEFAULT_SUBTOPICS.copy()
    
    # Update the Google Sheet
    if write_config(ws_config, st.session_state.cfg):
        return True, f"Product '{product_name}' created with default subtopics"
    else:
        return False, "Failed to update Google Sheets"

def refresh_config_if_needed(ws_config):
    """Refresh config from Google Sheets if needed"""
    if should_refresh_config():
        new_cfg = read_config(ws_config)
        if new_cfg != st.session_state.cfg:
            st.session_state.cfg = new_cfg
        st.session_state.last_config_update = datetime.now()

def read_quality_config(ws_quality_config):
    """Read quality configuration from Google Sheets"""
    try:
        values = ws_quality_config.get_all_records()
        quality_fields = {}
        for row in values:
            field = str(row.get("Field", "")).strip()
            field_type = str(row.get("Type", "")).strip()
            if field:
                quality_fields[field] = field_type
        return quality_fields
    except Exception as e:
        st.error(f"Error reading quality config: {str(e)}")
        return {field: "text" for field in QUALITY_DEFAULT_FIELDS}

def ensure_quality_history_headers(ws_quality_history, quality_fields):
    """Ensure quality history sheet has correct headers"""
    headers = ws_quality_history.row_values(1)
    needed_headers = ["User", "EntryID", "Timestamp", "Product"] + list(quality_fields.keys())
    
    if set(headers) != set(needed_headers):
        ws_quality_history.update("A1", [needed_headers])
        ws_quality_history.freeze(rows=1)
    return needed_headers

def append_quality_history(ws_quality_history, record: dict, quality_fields):
    """Append record to quality history"""
    headers = ensure_quality_history_headers(ws_quality_history, quality_fields)
    row = [record.get(h, "") for h in headers]
    ws_quality_history.append_row(row, value_input_option="USER_ENTERED")

# ------------------ History helpers ------------------
def ensure_history_headers(ws_history, product):
    current_subtopics = st.session_state.cfg.get(product, DEFAULT_SUBTOPICS.copy())
    headers = ws_history.row_values(1)
    needed_headers = ["User", "EntryID", "Timestamp", "Product", "Comments"] + current_subtopics
    
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

def update_entry(ws_history, entry_id: str, updated_data: dict):
    """Update an existing entry in the history sheet"""
    try:
        # Find the row with the matching EntryID
        cell = ws_history.find(entry_id)
        if not cell:
            st.error("Entry not found.")
            return False
        
        # Get current headers
        headers = ws_history.row_values(1)
        
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

def find_entry_by_id(ws_history, entry_id: str) -> dict:
    """Find an entry by its ID and return as dictionary"""
    try:
        cell = ws_history.find(entry_id)
        if not cell:
            return None
        
        headers = ws_history.row_values(1)
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
def login_system(ws_users):
    st.sidebar.header("Login")
    
    if st.session_state.logged_in:
        st.sidebar.success(f"Logged in as: {st.session_state.current_user}")
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.current_user = None
            st.session_state.user_role = ""
            st.rerun()
        return True
    
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
    
    # Regular user login section
    st.sidebar.subheader("Production/Admin Login")
    
    # Read users from sheet
    users = read_users_config(ws_users)
    
    if not users:
        st.sidebar.info("No production users configured.")
        return False
    
    username = st.sidebar.selectbox("Select User", options=[""] + list(users.keys()))
    password = st.sidebar.text_input("Password", type="password", key="prod_password")
    
    if st.sidebar.button("Login"):
        if username in users and users[username]["password"] == password:
            st.session_state.logged_in = True
            st.session_state.current_user = username
            st.session_state.user_role = users[username].get("role", "")
            st.sidebar.success("Login successful!")
            st.rerun()
        else:
            st.sidebar.error("Invalid username or password")
    
    return st.session_state.logged_in

# ------------------ Admin UI ------------------
def admin_ui(ws_config, ws_users):
    st.subheader("Admin Panel - Manage Products & Users")
    
    # Auto-refresh config to see changes from other devices
    refresh_config_if_needed(ws_config)

    tab1, tab2 = st.tabs(["Manage Products", "Manage Users"])

    with tab1:
        # Create new product
        with st.expander("Create New Product"):
            new_product = st.text_input("New Product Name", key="new_product")
            if st.button("Create Product"):
                success, message = add_product_with_default_subtopics(ws_config, new_product)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

        # Display current configuration
        st.divider()
        st.subheader("Current Products Configuration")
        st.info("""
        Instructions:
        1. To add a product: Use the form above or edit the 'Production_Config' sheet directly
        2. When adding directly to Google Sheets: Add only the product name in column A
        3. The app will automatically add all default subtopics when it detects a new product
        4. Click 'Refresh Configuration' to sync changes
        """)
        
        if st.session_state.cfg:
            for product, subtopics in st.session_state.cfg.items():
                with st.expander(f"Product: {product}"):
                    st.write("Subtopics:")
                    for subtopic in subtopics:
                        st.write(f"- {subtopic}")
        else:
            st.info("No products configured yet.")

    with tab2:
        st.subheader("Manage User Credentials")
        st.info("Edit the 'User_Credentials' sheet in Google Sheets to add/remove users.")
        
        # Display current users
        users = read_users_config(ws_users)
        if users:
            st.write("Current Users:")
            for username, user_data in users.items():
                st.write(f"- **{username}**: {user_data.get('role', 'No role')}")
        else:
            st.info("No users configured yet.")
        
        # Add new user form
        with st.expander("Add New User"):
            new_username = st.text_input("Username", key="new_username")
            new_password = st.text_input("Password", type="password", key="new_password")
            new_role = st.selectbox("Role", ["Production", "Quality", "Downtime", "Admin"], key="new_role")
            
            if st.button("Add User"):
                if new_username and new_password:
                    users[new_username] = {
                        "password": new_password,
                        "role": new_role
                    }
                    if write_users_config(ws_users, users):
                        st.success(f"User '{new_username}' added successfully!")
                        st.rerun()
                else:
                    st.warning("Please provide both username and password.")

    # Manual refresh button
    if st.button("🔄 Refresh Configuration"):
        st.session_state.last_config_update = None
        st.rerun()

# ------------------ Production UI ------------------
def production_ui(ws_config, ws_history):
    st.subheader(f"Production Data Entry - User: {st.session_state.current_user}")
    
    # Manual refresh button
    if st.button("🔄 Refresh Data"):
        refresh_config_if_needed(ws_config)
        st.rerun()

    # Auto-refresh config to get latest changes
    refresh_config_if_needed(ws_config)
    
    if not st.session_state.cfg:
        st.info("No products available yet. Ask Admin to create a product.")
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
                    "User": st.session_state.current_user,  # Add username first
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
        # Show User column first in the display
        display_columns = ["User", "Timestamp", "Product"] + current_subtopics + ["Comments"]
        available_columns = [col for col in display_columns if col in df.columns]
        st.dataframe(df[available_columns].head(10))
    else:
        st.caption("No entries yet for this product.")

# ------------------ Quality UI ------------------
def quality_ui(ws_config, ws_quality_history, ws_quality_config):
    st.subheader(f"Quality Data Entry - Inspector: {st.session_state.current_user}")
    
    # Read quality configuration
    quality_fields = read_quality_config(ws_quality_config)
    
    # Read available products from production config
    available_products = list(st.session_state.cfg.keys())
    
    if not available_products:
        st.error("No products available. Please ask admin to add products first.")
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
        
        # Digital Signature Canvas
        st.write("Digital Signature:")
        signature_canvas = st.empty()
        signature = signature_canvas.text_input("Draw your signature or type it here", key="digital_signature")
    
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
            
            append_quality_history(ws_quality_history, record, quality_fields)
            st.success(f"Quality data saved! Entry ID: {entry_id}")
            
            # Clear signature
            signature_canvas.text_input("Draw your signature or type it here", value="", key="digital_signature_clear")
            
        except Exception as e:
            st.error(f"Error saving quality data: {str(e)}")
    
    # Display recent quality entries
    try:
        quality_records = ws_quality_history.get_all_records()
        if quality_records:
            df = pd.DataFrame(quality_records)
            st.subheader("Recent Quality Entries")
            display_cols = ["User", "Timestamp", "Product", "Total_Lot_Qty", "Sample_Size", 
                           "AQL_Level", "Accept_Reject", "Results"]
            available_cols = [col for col in display_cols if col in df.columns]
            st.dataframe(df[available_cols].head(10).sort_values("Timestamp", ascending=False))
    except Exception as e:
        st.warning("No quality entries yet or error loading history.")

# ------------------ Downtime UI ------------------
def downtime_ui():
    st.subheader("Downtime Module - Coming Soon")
    st.info("Downtime module will be implemented in the next update")
    st.write("Planned features:")
    st.write("- Machine downtime tracking")
    st.write("- Reason categorization")
    st.write("- Downtime analysis reports")

# ------------------ Main ------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    st.title(APP_TITLE)

    try:
        client = get_gs_client()
        sh = open_spreadsheet(client)
        worksheets = ensure_worksheets(sh)
        ws_config, ws_history, ws_users, ws_quality_config, ws_quality_history = worksheets
        
        # Read config from Google Sheets at startup
        if not st.session_state.cfg:
            st.session_state.cfg = read_config(ws_config)
            st.session_state.last_config_update = datetime.now()

        # Check if there are products without subtopics and add default ones
        products_in_sheet = set()
        try:
            records = ws_config.get_all_records()
            for record in records:
                product = str(record.get("Product", "")).strip()
                if product:
                    products_in_sheet.add(product)
        except:
            pass
            
        # Add default subtopics for any products that might be missing them
        config_changed = False
        for product in products_in_sheet:
            if product not in st.session_state.cfg:
                st.session_state.cfg[product] = DEFAULT_SUBTOPICS.copy()
                config_changed = True
                
        if config_changed:
            write_config(ws_config, st.session_state.cfg)

        # Initialize user role in session state
        if 'user_role' not in st.session_state:
            st.session_state.user_role = ""

        # Login system
        if not login_system(ws_users):
            st.info("Please login to access the system")
            return

        # Navigation based on user role
        if st.session_state.user_role == "Admin":
            admin_ui(ws_config, ws_users)
        elif st.session_state.user_role == "Production":
            production_ui(ws_config, ws_history)
        elif st.session_state.user_role == "Quality":
            quality_ui(ws_config, ws_quality_history, ws_quality_config)
        elif st.session_state.user_role == "Downtime":
            downtime_ui()
        else:
            # Default to production if role not specified
            production_ui(ws_config, ws_history)

    except Exception as e:
        st.error(f"Application error: {str(e)}")
if __name__ == "__main__":
    main()



