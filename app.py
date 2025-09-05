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
    """Authenticate and return Google Sheets client."""
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
    """Open a Google Sheet."""
    client = get_gs_client()
    if client:
        try:
            return client.open(sheet_name)
        except Exception as e:
            st.error(f"Error opening Google Sheet: {str(e)}")
            return None
    return None

def read_sheet(sheet, worksheet_name):
    """Read a specific worksheet into a DataFrame."""
    try:
        worksheet = sheet.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error reading worksheet '{worksheet_name}': {str(e)}")
        return pd.DataFrame()

# ------------------ LOCAL SAVE ------------------
def save_locally(data):
    """Save data temporarily in session state."""
    if "local_storage" not in st.session_state:
        st.session_state.local_storage = []
    st.session_state.local_storage.append(data)
    st.success("✅ Data saved locally!")

# ------------------ LOAD CONFIG DATA ------------------
def load_production_config(force_refresh=False):
    """Load Production Config data only when needed or manually refreshed."""
    if "production_config_df" not in st.session_state or force_refresh:
        sheet = get_gsheet_data(SHEET_NAME)
        if sheet:
            st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
            if not st.session_state.production_config_df.empty:
                st.success("✅ Production Config data loaded successfully!")
            else:
                st.error("⚠️ No data found in Production_Config sheet!")
        else:
            st.error("❌ Unable to load Google Sheet.")

# ------------------ PRODUCTION DATA ENTRY ------------------
def production_data_entry():
    """Main form for production data entry."""
    production_config_df = st.session_state.get("production_config_df", pd.DataFrame())

    if production_config_df.empty:
        st.error("⚠️ No data found in Production_Config sheet! Please refresh or check Google Sheet.")
        return

    st.subheader("Please Enter the Production Data")

    # Product dropdown
    products = production_config_df['Product'].dropna().unique().tolist()
    if not products:
        st.error("⚠️ No products available in config data!")
        return

    selected_product = st.selectbox("Select Product", products)

    # Show current date/time
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: **{now}**")

    # Filter subtopics for selected product
    subtopics_df = production_config_df[production_config_df['Product'] == selected_product]

    production_entry = {"Product": selected_product, "DateTime": now}

    for idx, row in subtopics_df.iterrows():
        subtopic = row["Subtopic"]
        if str(row.get("Dropdown or Not", "")).strip().lower() == "yes":
            options = [opt.strip() for opt in str(row.get("Dropdown Options", "")).split(",") if opt.strip()]
            production_entry[subtopic] = st.selectbox(subtopic, options, key=f"{subtopic}_{idx}")
        else:
            production_entry[subtopic] = st.text_input(subtopic, key=f"{subtopic}_{idx}")

    # Save button
    if st.button("💾 Save Locally"):
        save_locally(production_entry)

# ------------------ MAIN APP ------------------
st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)

menu = ["Home", "Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
choice = st.sidebar.selectbox("Menu", menu)

# ------------------ HOME ------------------
if choice == "Home":
    st.markdown("<h2 style='text-align: center;'>Welcome to Die Casting Production App</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center;'>Please select a section to continue</h4>", unsafe_allow_html=True)

# ------------------ PRODUCTION TEAM LOGIN ------------------
elif choice == "Production Team Login":
    st.header("🔑 Production Team Login")

    usernames = list(USER_CREDENTIALS.keys())
    selected_user = st.selectbox("Select Username", usernames)
    entered_password = st.text_input("Enter Password", type="password")

    if st.button("Login", key="login_btn"):
        actual_password = USER_CREDENTIALS.get(selected_user)
        if actual_password and entered_password == actual_password:
            st.session_state.logged_in = True
            st.session_state.current_user = selected_user
            st.success(f"Welcome, {selected_user}!")

    # If user is logged in
    if st.session_state.get("logged_in", False):
        # Load data initially if not already loaded
        if "production_config_df" not in st.session_state:
            load_production_config()

        # Manual Refresh Button
        if st.button("🔄 Refresh Production Config Data", key="refresh_btn"):
            load_production_config(force_refresh=True)

        # Show production entry form
        production_data_entry()

# ------------------ QUALITY TEAM LOGIN ------------------
elif choice == "Quality Team Login":
    st.header("🧪 Quality Team Login (Coming Soon...)")

# ------------------ DOWNTIME DATA RECORDINGS ------------------
elif choice == "Downtime Data Recordings":
    st.header("⏱️ Downtime Data Recordings (Coming Soon...)")
