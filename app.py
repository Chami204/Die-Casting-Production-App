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

QUALITY_SHARED_PASSWORD = "12"
DOWNTIME_SHARED_PASSWORD = "123"

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
        try:
            return client.open(sheet_name)
        except Exception as e:
            st.error(f"Error opening sheet '{sheet_name}': {e}")
            return None
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
def save_locally(section, data):
    key = f"{section}_local_data"
    if key not in st.session_state:
        st.session_state[key] = []
    st.session_state[key].append(data)
    st.success("Data saved locally!")

# ------------------ SYNC TO GOOGLE SHEET ------------------
def sync_local_data_to_sheet(local_key, history_sheet_name):
    sheet = get_gsheet_data(SHEET_NAME)
    if not sheet:
        st.error("Google Sheet not found.")
        return
    df_local = pd.DataFrame(st.session_state.get(local_key, []))
    if df_local.empty:
        st.info("No local data to sync.")
        return

    try:
        # Check if sheet exists, else create
        try:
            worksheet = sheet.worksheet(history_sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=history_sheet_name, rows="100", cols="50")

        existing_df = pd.DataFrame(worksheet.get_all_records())
        combined_df = pd.concat([existing_df, df_local], ignore_index=True)

        # Remove NaN and ensure JSON compliance
        combined_df = combined_df.fillna("")

        worksheet.clear()
        worksheet.update([combined_df.columns.values.tolist()] + combined_df.values.tolist())
        st.success(f"✅ {history_sheet_name} synced successfully!")
        # Clear local storage
        st.session_state[local_key] = []
    except Exception as e:
        st.error(f"Error syncing data: {e}")

# ------------------ LOAD CONFIG DATA ------------------
def load_config(sheet_name, config_sheet, force_refresh=False):
    key = f"{config_sheet}_df"
    if key not in st.session_state or force_refresh:
        sheet = get_gsheet_data(sheet_name)
        st.session_state[key] = read_sheet(sheet, config_sheet)
        st.success(f"{config_sheet} data loaded!")
    return st.session_state.get(key, pd.DataFrame())

# ------------------ DATA ENTRY ------------------
def data_entry(section, config_df, logged_user, local_key, history_sheet_name, include_product=True):
    if config_df.empty:
        st.error(f"⚠️ {section} config not loaded!")
        return

    st.subheader(f"Please Enter the {section} Data")
    
    # For Downtime, include_product=False, we add Planned Item manually
    if include_product:
        products = config_df['Product'].unique().tolist()
        selected_product = st.selectbox("Select Product", products)
    else:
        planned_items = st.session_state.get("prod_config_df", pd.DataFrame())
        if not planned_items.empty:
            selected_product = st.selectbox("Select Planned Item", planned_items['Product'].unique())
        else:
            st.error("⚠️ Production_Config not loaded! Cannot select Planned Item.")
            return

    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    # Create entry dictionary
    entry = {"User": logged_user}
    if include_product or section.lower() == "downtime":
        entry["Planned Item"] = selected_product
    entry["DateTime"] = now

    # Determine columns to use for data entry
    if section.lower() == "downtime":
        subtopic_columns = config_df.columns.tolist()  # all columns
    else:
        subtopic_columns = config_df["Subtopic"].tolist()

    for col_name in subtopic_columns:
        # Check if column has dropdown options
        if section.lower() != "downtime" and str(config_df.loc[config_df['Subtopic'] == col_name, "Dropdown or Not"].values[0]).strip().lower() == "yes":
            options = str(config_df.loc[config_df['Subtopic'] == col_name, "Dropdown Options"].values[0]).split(",")
            entry[col_name] = st.selectbox(col_name, [opt.strip() for opt in options], key=f"{section}_{col_name}")
        else:
            entry[col_name] = st.text_input(col_name, key=f"{section}_{col_name}")

    # Buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button(f"💾 Save Locally ({section})"):
            save_locally(local_key, entry)
    with col2:
        if st.button(f"📤 Sync to Google Sheet ({section})"):
            sync_local_data_to_sheet(local_key, history_sheet_name)
    with col3:
        if st.button(f"🔓 Logout ({section})"):
            # Reset login flags
            if section.lower() == "production":
                st.session_state.prod_logged_in = False
                st.session_state.logged_user = ""
            elif section.lower() == "quality":
                st.session_state.qual_logged_in = False
                st.session_state.qual_logged_user = ""
            elif section.lower() == "downtime":
                st.session_state.downtime_logged_in = False
                st.session_state.downtime_logged_user = ""
            st.info("You have been logged out.")
            return


# ------------------ SYNC ALL LOCAL DATA ------------------
def sync_all_local_data():
    synced_sections = []
    sections = [
        ("prod_local_data", "Production_History"),
        ("qual_local_data", "Quality_History"),
        ("downtime_local_data", "Downtime_History")
    ]
    for local_key, sheet_name in sections:
        if local_key in st.session_state and st.session_state[local_key]:
            sync_local_data_to_sheet(local_key, sheet_name)
            synced_sections.append(sheet_name.replace("_History", ""))
    if not synced_sections:
        st.info("No local data to sync.")
    else:
        st.success(f"✅ Synced data for: {', '.join(synced_sections)}")

# ------------------ MAIN APP ------------------
st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)

menu = ["Home", "Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
choice = st.sidebar.selectbox("Menu", menu)

# ------------------ HOME PAGE ------------------
if choice == "Home":
    st.markdown("<h2 style='text-align: center;'>Welcome to Die Casting Production App</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center;'>Please select a section to continue</h4>", unsafe_allow_html=True)
    st.markdown("---")
    st.header("⚡ Sync Any Unsynced Local Data")
    if st.button("💾 Sync All Local Data"):
        sync_all_local_data()

# ------------------ PRODUCTION TEAM LOGIN ------------------
elif choice == "Production Team Login":
    if "prod_logged_in" not in st.session_state:
        st.session_state.prod_logged_in = False
        st.session_state.logged_user = ""

    if not st.session_state.prod_logged_in:
        usernames = list(USER_CREDENTIALS.keys())
        selected_user = st.selectbox("Select Username", usernames)
        entered_password = st.text_input("Enter Password", type="password")
        if st.button("Login"):
            actual_password = USER_CREDENTIALS.get(selected_user)
            if actual_password and entered_password == actual_password:
                st.session_state.prod_logged_in = True
                st.session_state.logged_user = selected_user
                st.success(f"Welcome, {selected_user}!")
            else:
                st.error("❌ Incorrect password!")
    else:
        config_df = load_config(SHEET_NAME, PRODUCTION_CONFIG_SHEET)
        # Manual refresh
        if st.button("🔄 Refresh Production Config Data"):
            config_df = load_config(SHEET_NAME, PRODUCTION_CONFIG_SHEET, force_refresh=True)
        data_entry("Production", config_df, st.session_state.logged_user, "prod_local_data", "Production_History", include_product=True)

# ------------------ QUALITY TEAM LOGIN ------------------
elif choice == "Quality Team Login":
    if "qual_logged_in" not in st.session_state:
        st.session_state.qual_logged_in = False
        st.session_state.qual_logged_user = ""

    if not st.session_state.qual_logged_in:
        entered_user = st.text_input("Enter Username")
        entered_password = st.text_input("Enter Password", type="password")
        if st.button("Login"):
            if entered_password == QUALITY_SHARED_PASSWORD and entered_user.strip():
                st.session_state.qual_logged_in = True
                st.session_state.qual_logged_user = entered_user.strip()
                st.success(f"Welcome, {entered_user.strip()}!")
            else:
                st.error("❌ Incorrect password!")
    else:
        config_df = load_config(SHEET_NAME, QUALITY_CONFIG_SHEET)
        if st.button("🔄 Refresh Quality Config Data"):
            config_df = load_config(SHEET_NAME, QUALITY_CONFIG_SHEET, force_refresh=True)
        data_entry("Quality", config_df, st.session_state.qual_logged_user, "qual_local_data", "Quality_History", include_product=True)

# ------------------ DOWNTIME DATA RECORDINGS ------------------
elif choice == "Downtime Data Recordings":
    if "downtime_logged_in" not in st.session_state:
        st.session_state.downtime_logged_in = False
        st.session_state.downtime_logged_user = ""

    if not st.session_state.downtime_logged_in:
        entered_user = st.text_input("Enter Username")
        entered_password = st.text_input("Enter Password", type="password")
        if st.button("Login"):
            if entered_password == DOWNTIME_SHARED_PASSWORD and entered_user.strip():
                st.session_state.downtime_logged_in = True
                st.session_state.downtime_logged_user = entered_user.strip()
                st.success(f"Welcome, {entered_user.strip()}!")
            else:
                st.error("❌ Incorrect password!")
    else:
        # Load downtime config and production products for "Planned Item"
        downtime_config_df = load_config(SHEET_NAME, DOWNTIME_CONFIG_SHEET)
        prod_config_df = load_config(SHEET_NAME, PRODUCTION_CONFIG_SHEET)
        # Create a temporary column 'Product' from Production_Config
        if not downtime_config_df.empty and not prod_config_df.empty:
            downtime_config_df = downtime_config_df.copy()
            downtime_config_df["Product"] = st.selectbox("Select Planned Item", prod_config_df['Product'].unique())
        if st.button("🔄 Refresh Downtime Config Data"):
            downtime_config_df = load_config(SHEET_NAME, DOWNTIME_CONFIG_SHEET, force_refresh=True)
        data_entry("Downtime", downtime_config_df, st.session_state.downtime_logged_user, "downtime_local_data", "Downtime_History", include_product=False)

