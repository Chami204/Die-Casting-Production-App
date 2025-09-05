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
HISTORY_SHEET = "History"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')

# ------------------ USER CREDENTIALS ------------------
USER_CREDENTIALS = {
    "chami": "123",
    "user2": "password",
    "user3": "abc123"
}

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
def save_locally(data):
    if "local_storage" not in st.session_state:
        st.session_state.local_storage = []
    st.session_state.local_storage.append(data)
    st.success("Data saved locally!")

# ------------------ LOAD CONFIG DATA ------------------
def load_production_config(force_refresh=False):
    """Load Production Config data. Refresh only when requested."""
    if "production_config_df" not in st.session_state or force_refresh:
        sheet = get_gsheet_data(SHEET_NAME)
        st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
        st.success("Production Config data refreshed!")

# ------------------ PRODUCTION DATA ENTRY ------------------
def production_data_entry(logged_user):
    production_config_df = st.session_state.production_config_df

    if production_config_df.empty:
        st.error("⚠️ No data found in Production_Config sheet!")
        return

    st.subheader("Please Enter the Production Data")

    # Product dropdown
    products = production_config_df['Product'].unique().tolist()
    selected_product = st.selectbox("Select Product", products)

    # Show current date/time
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    # Filter subtopics for selected product
    subtopics_df = production_config_df[production_config_df['Product'] == selected_product]

    # Initialize production entry with username
    production_entry = {"User": logged_user, "Product": selected_product, "DateTime": now}

    for idx, row in subtopics_df.iterrows():
        if str(row["Dropdown or Not"]).strip().lower() == "yes":
            options = [opt.strip() for opt in str(row["Dropdown Options"]).split(",")]
            production_entry[row["Subtopic"]] = st.selectbox(row["Subtopic"], options, key=row["Subtopic"])
        else:
            production_entry[row["Subtopic"]] = st.text_input(row["Subtopic"], key=row["Subtopic"])

    if st.button("Save Locally"):
        save_locally(production_entry)

# ------------------ SYNC TO GOOGLE SHEET ------------------
def sync_to_google_sheet():
    """Upload locally saved data to Google Sheet History sheet with dynamic column handling."""
    if "local_storage" not in st.session_state or len(st.session_state.local_storage) == 0:
        st.warning("⚠️ No locally saved data to sync.")
        return

    sheet = get_gsheet_data(SHEET_NAME)
    if not sheet:
        st.error("❌ Cannot connect to Google Sheet.")
        return

    try:
        history_ws = sheet.worksheet(HISTORY_SHEET)

        # Convert local data to DataFrame
        df_local = pd.DataFrame(st.session_state.local_storage)

        # ---- Step 1: Get current Google Sheet headers ----
        current_headers = history_ws.row_values(1)  # first row is header

        # ---- Step 2: Combine headers to ensure no missing columns ----
        updated_headers = list(current_headers)
        for col in df_local.columns:
            if col not in updated_headers:
                updated_headers.append(col)  # add new subtopics dynamically

        # ---- Step 3: If headers changed, update header row in sheet ----
        if updated_headers != current_headers:
            history_ws.update('A1', [updated_headers])
            st.info("📝 Headers updated in Google Sheet to include new subtopics!")

        # ---- Step 4: Reorder DataFrame columns to match updated headers ----
        df_local = df_local.reindex(columns=updated_headers)

        # ---- Step 5: Fill NaN to avoid JSON issues ----
        df_local = df_local.fillna("")

        # ---- Step 6: Append the data correctly ----
        rows_to_add = df_local.values.tolist()
        history_ws.append_rows(rows_to_add)
        st.success(f"✅ {len(rows_to_add)} records synced to Google Sheet!")

        # Clear local storage after successful sync
        st.session_state.local_storage = []

    except Exception as e:
        st.error(f"Error syncing data: {str(e)}")

# ------------------ MAIN APP ------------------
st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)

menu = ["Home", "Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
choice = st.sidebar.selectbox("Menu", menu)

if choice == "Home":
    st.markdown("<h2 style='text-align: center;'>Welcome to Die Casting Production App</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center;'>Please select a section to continue</h4>", unsafe_allow_html=True)

# ------------------ PRODUCTION TEAM LOGIN ------------------
elif choice == "Production Team Login":
    st.header("🔑 Production Team Login")

    usernames = list(USER_CREDENTIALS.keys())
    selected_user = st.selectbox("Select Username", usernames)
    entered_password = st.text_input("Enter Password", type="password")

    if st.button("Login"):
        actual_password = USER_CREDENTIALS.get(selected_user)
        if actual_password and entered_password == actual_password:
            st.success(f"Welcome, {selected_user}!")

            # Load production config data
            load_production_config()

            # Manual Refresh Button
            if st.button("🔄 Refresh Production Config Data"):
                load_production_config(force_refresh=True)

            # Show Production Data Entry section AFTER successful login
            production_data_entry(logged_user=selected_user)

            # Sync locally saved data to Google Sheet
            if st.button("📤 Sync Local Data to Google Sheet"):
                sync_to_google_sheet()

        else:
            st.error("❌ Incorrect password!")

# ------------------ QUALITY TEAM LOGIN ------------------
elif choice == "Quality Team Login":
    st.header("Quality Team Login (Coming Soon...)")

# ------------------ DOWNTIME DATA RECORDINGS ------------------
elif choice == "Downtime Data Recordings":
    st.header("Downtime Data Recordings (Coming Soon...)")
