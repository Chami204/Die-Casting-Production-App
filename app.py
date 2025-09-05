import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz

# ------------------ SETTINGS ------------------
APP_TITLE = "Die Casting Production"
SHEET_NAME = "FlowApp_Data"  # Replace with your Google Sheet name
PRODUCTION_CONFIG_SHEET = "Production_Config"
QUALITY_CONFIG_SHEET = "Quality_Config"
DOWNTIME_CONFIG_SHEET = "Downtime_Config"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')

# ------------------ USER CREDENTIALS ------------------
USER_CREDENTIALS = {
    "user1": "12",
    "user2": "123",
    "user3": "1234"
}

QUALITY_SHARED_PASSWORD = "12"      # Same for all quality users
DOWNTIME_SHARED_PASSWORD = "123"    # Same for all downtime users

# ------------------ GOOGLE SHEET CONNECTION ------------------
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

def get_gsheet_data(sheet_name):
    client = get_gs_client()
    if client:
        return client.open(sheet_name)
    else:
        return None

def read_sheet(sheet, worksheet_name):
    try:
        worksheet = sheet.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error reading worksheet '{worksheet_name}': {str(e)}")
        return pd.DataFrame()

# ------------------ LOCAL SAVE ------------------
def save_locally(data, storage_key):
    if storage_key not in st.session_state:
        st.session_state[storage_key] = []
    st.session_state[storage_key].append(data)
    st.success("Data saved locally!")

# ------------------ SYNC FUNCTION ------------------
def sync_local_data_to_sheet(local_key, history_sheet_name):
    if local_key not in st.session_state or len(st.session_state[local_key]) == 0:
        st.warning("No local data to sync!")
        return

    client = get_gs_client()
    if not client:
        st.error("Cannot connect to Google Sheets!")
        return

    try:
        ws = client.open(SHEET_NAME).worksheet(history_sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Worksheet '{history_sheet_name}' not found!")
        return

    # Get existing sheet headers
    existing_cols = ws.row_values(1) if ws.row_values(1) else []

    # Collect all keys from local data
    all_keys = set(existing_cols)
    for entry in st.session_state[local_key]:
        all_keys.update(entry.keys())
    all_keys = list(all_keys)

    # Update header row if new columns exist
    if existing_cols != all_keys:
        ws.update('1:1', [all_keys])

    # Prepare data rows
    rows_to_append = []
    for entry in st.session_state[local_key]:
        row = [entry.get(col, "") for col in all_keys]
        rows_to_append.append(row)

    # Append data
    ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    # Clear local storage
    st.session_state[local_key] = []
    st.success(f"✅ {len(rows_to_append)} records synced to {history_sheet_name}!")

# ------------------ DATA ENTRY FUNCTIONS ------------------
def production_data_entry(logged_user):
    df = st.session_state.production_config_df
    if df.empty:
        st.error("⚠️ Production_Config not loaded!")
        return

    st.subheader("Please Enter the Production Data")
    products = df['Product'].unique().tolist()
    selected_product = st.selectbox("Select Product", products)
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    subtopics_df = df[df['Product'] == selected_product]
    entry = {"User": logged_user, "Product": selected_product, "DateTime": now}

    for _, row in subtopics_df.iterrows():
        if str(row["Dropdown or Not"]).strip().lower() == "yes":
            options = [opt.strip() for opt in str(row["Dropdown Options"]).split(",")]
            entry[row["Subtopic"]] = st.selectbox(row["Subtopic"], options, key=row["Subtopic"])
        else:
            entry[row["Subtopic"]] = st.text_input(row["Subtopic"], key=row["Subtopic"])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Locally"):
            save_locally(entry, "prod_local_data")
    with col2:
        if st.button("💾 Sync Production Data"):
            sync_local_data_to_sheet("prod_local_data", "Production_History")

    if st.button("Logout"):
        st.session_state.prod_logged_in = False
        st.session_state.logged_user = ""
        st.experimental_rerun()

def quality_data_entry(logged_user):
    df = st.session_state.quality_config_df
    if df.empty:
        st.error("⚠️ Quality_Config not loaded!")
        return

    st.subheader("Please Enter the Quality Data")
    products = st.session_state.production_config_df['Product'].unique().tolist()
    selected_product = st.selectbox("Select Product", products)
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    subtopics_df = df[df['Product'] == selected_product]
    entry = {"User": logged_user, "Product": selected_product, "DateTime": now}

    for _, row in subtopics_df.iterrows():
        if str(row["Dropdown or Not"]).strip().lower() == "yes":
            options = [opt.strip() for opt in str(row["Dropdown Options"]).split(",")]
            entry[row["Subtopic"]] = st.selectbox(row["Subtopic"], options, key=f"qual_{row['Subtopic']}")
        else:
            entry[row["Subtopic"]] = st.text_input(row["Subtopic"], key=f"qual_{row['Subtopic']}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Locally"):
            save_locally(entry, "qual_local_data")
    with col2:
        if st.button("💾 Sync Quality Data"):
            sync_local_data_to_sheet("qual_local_data", "Quality_History")

    if st.button("Logout"):
        st.session_state.qual_logged_in = False
        st.session_state.qual_logged_user = ""
        st.experimental_rerun()

def downtime_data_entry(logged_user):
    df = st.session_state.downtime_config_df
    prod_df = st.session_state.production_config_df
    if df.empty or prod_df.empty:
        st.error("⚠️ Downtime_Config or Production_Config not loaded!")
        return

    st.subheader("Please Enter the Downtime Data")
    planned_items = prod_df['Product'].unique().tolist()
    selected_item = st.selectbox("Planned Item", planned_items)
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    entry = {"User": logged_user, "Planned Item": selected_item, "DateTime": now}

    for col in df.columns:
        if str(df[col].iloc[0]).strip().lower() == "yes":
            options = [opt.strip() for opt in str(df[col].iloc[1]).split(",")]
            entry[col] = st.selectbox(col, options, key=f"downtime_{col}")
        else:
            entry[col] = st.text_input(col, key=f"downtime_{col}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Locally"):
            save_locally(entry, "downtime_local_data")
    with col2:
        if st.button("💾 Sync Downtime Data"):
            sync_local_data_to_sheet("downtime_local_data", "Downtime_History")

    if st.button("Logout"):
        st.session_state.downtime_logged_in = False
        st.session_state.downtime_logged_user = ""
        st.experimental_rerun()

# ------------------ APP CONFIG ------------------
st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)

# Initialize session state variables if they don't exist
if "prod_logged_in" not in st.session_state:
    st.session_state.prod_logged_in = False
if "qual_logged_in" not in st.session_state:
    st.session_state.qual_logged_in = False
if "downtime_logged_in" not in st.session_state:
    st.session_state.downtime_logged_in = False
if "logged_user" not in st.session_state:
    st.session_state.logged_user = ""
if "qual_logged_user" not in st.session_state:
    st.session_state.qual_logged_user = ""
if "downtime_logged_user" not in st.session_state:
    st.session_state.downtime_logged_user = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = "Home"

sheet = get_gsheet_data(SHEET_NAME)
if sheet:
    if "production_config_df" not in st.session_state:
        st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
    if "quality_config_df" not in st.session_state:
        st.session_state.quality_config_df = read_sheet(sheet, QUALITY_CONFIG_SHEET)
    if "downtime_config_df" not in st.session_state:
        st.session_state.downtime_config_df = read_sheet(sheet, DOWNTIME_CONFIG_SHEET)

# Create sidebar menu
menu = ["Home", "Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
if not st.session_state.prod_logged_in and not st.session_state.qual_logged_in and not st.session_state.downtime_logged_in:
    choice = st.sidebar.selectbox("Menu", menu, index=menu.index(st.session_state.current_page) if st.session_state.current_page in menu else 0)
    st.session_state.current_page = choice
else:
    # If logged in, show a different sidebar or hide it
    st.sidebar.write("You are currently logged in")
    if st.sidebar.button("Return to Home"):
        st.session_state.prod_logged_in = False
        st.session_state.qual_logged_in = False
        st.session_state.downtime_logged_in = False
        st.session_state.current_page = "Home"
        st.experimental_rerun()

# Check if user is logged in to any section and show appropriate content
if st.session_state.prod_logged_in:
    production_data_entry(st.session_state.logged_user)
elif st.session_state.qual_logged_in:
    quality_data_entry(st.session_state.qual_logged_user)
elif st.session_state.downtime_logged_in:
    downtime_data_entry(st.session_state.downtime_logged_user)
else:
    # Only show the menu if no one is logged in
    # ------------------ HOME ------------------
    if st.session_state.current_page == "Home":
        st.markdown("<h2 style='text-align: center;'>Welcome to Die Casting Production App</h2>", unsafe_allow_html=True)
        st.markdown("<h4 style='text-align: center;'>Please select a section to continue</h4>", unsafe_allow_html=True)

    # ------------------ PRODUCTION TEAM LOGIN ------------------
    elif st.session_state.current_page == "Production Team Login":
        st.header("🔑 Production Team Login")
        usernames = list(USER_CREDENTIALS.keys())
        selected_user = st.selectbox("Select Username", usernames)
        entered_password = st.text_input("Enter Password", type="password")

        if st.button("Login"):
            actual_password = USER_CREDENTIALS.get(selected_user)
            if actual_password and entered_password == actual_password:
                st.session_state.prod_logged_in = True
                st.session_state.logged_user = selected_user
                st.success(f"Welcome, {selected_user}!")
                st.experimental_rerun()
            else:
                st.error("❌ Incorrect password!")

    # ------------------ QUALITY TEAM LOGIN ------------------
    elif st.session_state.current_page == "Quality Team Login":
        st.header("🔑 Quality Team Login")
        entered_user = st.text_input("Enter Your Name")
        entered_pass = st.text_input("Enter Password", type="password")

        if st.button("Login"):
            if entered_pass == QUALITY_SHARED_PASSWORD:
                st.session_state.qual_logged_in = True
                st.session_state.qual_logged_user = entered_user
                st.success(f"Welcome, {entered_user}!")
                st.experimental_rerun()
            else:
                st.error("❌ Incorrect password!")

    # ------------------ DOWNTIME DATA RECORDINGS ------------------
    elif st.session_state.current_page == "Downtime Data Recordings":
        st.header("🔑 Downtime Team Login")
        entered_user = st.text_input("Enter Your Name")
        entered_pass = st.text_input("Enter Password", type="password")

        if st.button("Login"):
            if entered_pass == DOWNTIME_SHARED_PASSWORD:
                st.session_state.downtime_logged_in = True
                st.session_state.downtime_logged_user = entered_user
                st.success(f"Welcome, {entered_user}!")
                st.experimental_rerun()
            else:
                st.error("❌ Incorrect password!")
