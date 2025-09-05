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
        creds_dict = st.secrets["gcp_service_account"]
        creds_dict["private_key"] = creds_dict["private_key"].replace('\\n', '\n')
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
        except gspread.SpreadsheetNotFound:
            st.error(f"Spreadsheet '{sheet_name}' not found. Make sure the service account has access.")
            return None
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
        combined_df = combined_df.fillna("")
        worksheet.clear()
        worksheet.update([combined_df.columns.values.tolist()] + combined_df.values.tolist())
        st.success(f"✅ {history_sheet_name} synced successfully!")
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
def data_entry(section, config_df, logged_user, local_key, history_sheet_name, include_product=True, planned_item=None):
    if config_df.empty:
        st.error(f"⚠️ {section} config not loaded!")
        return
    st.subheader(f"Please Enter the {section} Data")
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    entry = {"User": logged_user, "DateTime": now}

    # Product selection
    if include_product:
        selected_product = st.selectbox(
            f"Select Product ({section})",
            config_df['Product'].unique(),
            key=f"{section}_product"
        )
        entry["Planned Item"] = selected_product
    elif planned_item:
        entry["Planned Item"] = planned_item

    # Columns for data entry
    if section.lower() == "downtime":
        subtopic_columns = [col for col in config_df.columns if col != "Product"]
    else:
        subtopic_columns = config_df["Subtopic"].tolist()

    for idx, col_name in enumerate(subtopic_columns):
        widget_key = f"{section}_{col_name}_{idx}"  # Unique key per column
        if section.lower() != "downtime" and str(config_df.loc[config_df['Subtopic'] == col_name, "Dropdown or Not"].values[0]).strip().lower() == "yes":
            options = str(config_df.loc[config_df['Subtopic'] == col_name, "Dropdown Options"].values[0]).split(",")
            entry[col_name] = st.selectbox(col_name, [opt.strip() for opt in options], key=widget_key)
        else:
            entry[col_name] = st.text_input(col_name, key=widget_key)

    # Buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button(f"💾 Save Locally ({section})", key=f"save_{section}"):
            save_locally(local_key, entry)
    with col2:
        if st.button(f"📤 Sync to Google Sheet ({section})", key=f"sync_{section}"):
            sync_local_data_to_sheet(local_key, history_sheet_name)
    with col3:
        if st.button(f"🔓 Logout ({section})", key=f"logout_{section}"):
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
            st.experimental_rerun()

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
    if st.button("💾 Sync All Local Data", key="sync_all_home"):
        sync_all_local_data()

# ------------------ PRODUCTION TEAM LOGIN ------------------
elif choice == "Production Team Login":
    if "prod_logged_in" not in st.session_state:
        st.session_state.prod_logged_in = False
        st.session_state.logged_user = ""

    if not st.session_state.prod_logged_in:
        usernames = list(USER_CREDENTIALS.keys())
        selected_user = st.selectbox("Select Username", usernames, key="prod_user_select")
        entered_password = st.text_input("Enter Password", type="password", key="prod_password_input")
        if st.button("Login", key="prod_login_button"):
            actual_password = USER_CREDENTIALS.get(selected_user)
            if actual_password and entered_password == actual_password:
                st.session_state.prod_logged_in = True
                st.session_state.logged_user = selected_user
                st.success(f"Welcome, {selected_user}!")
            else:
                st.error("❌ Incorrect password!")
    else:
        config_df = load_config(SHEET_NAME, PRODUCTION_CONFIG_SHEET)
        if st.button("🔄 Refresh Production Config Data", key="refresh_prod_config"):
            config_df = load_config(SHEET_NAME, PRODUCTION_CONFIG_SHEET, force_refresh=True)
        data_entry("Production", config_df, st.session_state.logged_user, "prod_local_data", "Production_History", include_product=True)

# ------------------ QUALITY TEAM LOGIN ------------------
elif choice == "Quality Team Login":
    if "qual_logged_in" not in st.session_state:
        st.session_state.qual_logged_in = False
        st.session_state.qual_logged_user = ""

    if not st.session_state.qual_logged_in:
        entered_user = st.text_input("Enter Username", key="qual_user_input")
        entered_password = st.text_input("Enter Password", type="password", key="qual_password_input")
        if st.button("Login", key="qual_login_button"):
            if entered_password == QUALITY_SHARED_PASSWORD and entered_user.strip():
                st.session_state.qual_logged_in = True
                st.session_state.qual_logged_user = entered_user.strip()
                st.success(f"Welcome, {entered_user.strip()}!")
            else:
                st.error("❌ Incorrect password!")
    else:
        config_df = load_config(SHEET_NAME, QUALITY_CONFIG_SHEET)
        if st.button("🔄 Refresh Quality Config Data", key="refresh_qual_config"):
            config_df = load_config(SHEET_NAME, QUALITY_CONFIG_SHEET, force_refresh=True)
        data_entry("Quality", config_df, st.session_state.qual_logged_user, "qual_local_data", "Quality_History", include_product=True)

# ------------------ DOWNTIME DATA RECORDINGS ------------------
elif choice == "Downtime Data Recordings":
    if "downtime_logged_in" not in st.session_state:
        st.session_state.downtime_logged_in = False
        st.session_state.downtime_logged_user = ""

    if not st.session_state.downtime_logged_in:
        entered_user = st.text_input("Enter Username", key="dt_user_input")
        entered_password = st.text_input("Enter Password", type="password", key="dt_password_input")
        if st.button("Login", key="dt_login_button"):
            if entered_password == DOWNTIME_SHARED_PASSWORD and entered_user.strip():
                st.session_state.downtime_logged_in = True
                st.session_state.downtime_logged_user = entered_user.strip()
                st.success(f"Welcome, {entered_user.strip()}!")
            else:
                st.error("❌ Incorrect password!")
    else:
        downtime_config_df = load_config(SHEET_NAME, DOWNTIME_CONFIG_SHEET)
        prod_config_df = load_config(SHEET_NAME, PRODUCTION_CONFIG_SHEET)
        planned_item = None
        if not prod_config_df.empty:
            planned_item = st.selectbox("Select Planned Item", prod_config_df['Product'].unique(), key="dt_planned_item")
        if st.button("🔄 Refresh Downtime Config Data", key="refresh_dt_config"):
            downtime_config_df = load_config(SHEET_NAME, DOWNTIME_CONFIG_SHEET, force_refresh=True)
        data_entry("Downtime", downtime_config_df, st.session_state.downtime_logged_user, "downtime_local_data", "Downtime_History", include_product=False, planned_item=planned_item)
