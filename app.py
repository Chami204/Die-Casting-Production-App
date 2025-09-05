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
QUALITY_SHARED_PASSWORD = "123"
DOWNTIME_SHARED_PASSWORD = "1234"

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
def save_locally(storage_key, data):
    if storage_key not in st.session_state:
        st.session_state[storage_key] = []
    st.session_state[storage_key].append(data)
    st.success("Data saved locally!")

# ------------------ PRODUCTION DATA ENTRY ------------------
def production_data_entry(logged_user):
    df = st.session_state.production_config_df
    if df.empty:
        st.error("⚠️ Production_Config not loaded!")
        return

    st.subheader("Please Enter the Production Data")
    products = df['Product'].unique().tolist()
    selected_product = st.selectbox("Select Product", products, key=f"prod_product_{logged_user}")
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    entry = {"User": logged_user, "Product": selected_product, "DateTime": now}
    subtopics_df = df[df['Product'] == selected_product]
    for idx, row in subtopics_df.iterrows():
        if str(row["Dropdown or Not"]).strip().lower() == "yes":
            options = [opt.strip() for opt in str(row["Dropdown Options"]).split(",")]
            entry[row["Subtopic"]] = st.selectbox(row["Subtopic"], options, key=f"prod_{row['Subtopic']}_{logged_user}")
        else:
            entry[row["Subtopic"]] = st.text_input(row["Subtopic"], key=f"prod_{row['Subtopic']}_{logged_user}")

    if st.button("Save Locally", key=f"prod_save_{logged_user}"):
        save_locally("prod_local_storage", entry)

def sync_production_to_google_sheet():
    storage_key = "prod_local_storage"
    if storage_key not in st.session_state or len(st.session_state[storage_key]) == 0:
        st.warning("No local production data to sync!")
        return
    sheet = get_gsheet_data(SHEET_NAME)
    if sheet is None:
        st.error("Cannot connect to Google Sheet.")
        return
    try:
        worksheet_name = "Production_History"
        try:
            worksheet = sheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=worksheet_name, rows="1000", cols="50")

        # Collect all column headers dynamically
        all_keys = set()
        for entry in st.session_state[storage_key]:
            all_keys.update(entry.keys())
        all_keys = list(all_keys)
        if "User" in all_keys:
            all_keys.remove("User")
        all_keys = ["User"] + all_keys

        worksheet_values = worksheet.get_all_values()
        if worksheet_values:
            worksheet_header = worksheet_values[0]
            for key in all_keys:
                if key not in worksheet_header:
                    worksheet.update_cell(1, len(worksheet_header) + 1, key)
                    worksheet_header.append(key)
        else:
            worksheet.append_row(all_keys)

        for entry in st.session_state[storage_key]:
            row = [entry.get(key, "") for key in all_keys]
            worksheet.append_row(row)
        st.success(f"✅ Synced {len(st.session_state[storage_key])} production records to Google Sheet.")
        st.session_state[storage_key] = []
    except Exception as e:
        st.error(f"Error syncing production data: {str(e)}")

# ------------------ QUALITY DATA ENTRY ------------------
def quality_data_entry(logged_user):
    df = st.session_state.quality_config_df
    if df.empty:
        st.error("⚠️ Quality_Config not loaded!")
        return

    st.subheader("Please Enter the Quality Data")
    products = st.session_state.production_config_df['Product'].unique().tolist()
    selected_product = st.selectbox("Select Product", products, key=f"qual_product_{logged_user}")
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    entry = {"User": logged_user, "Product": selected_product, "DateTime": now}
    subtopics_df = df[df['Product'] == selected_product] if 'Product' in df.columns else df
    for idx, row in subtopics_df.iterrows():
        if str(row.get("Dropdown or Not", "")).strip().lower() == "yes":
            options = [opt.strip() for opt in str(row.get("Dropdown Options", "")).split(",")]
            entry[row["Subtopic"]] = st.selectbox(row["Subtopic"], options, key=f"qual_{row['Subtopic']}_{logged_user}")
        else:
            entry[row["Subtopic"]] = st.text_input(row["Subtopic"], key=f"qual_{row['Subtopic']}_{logged_user}")

    if st.button("Save Locally", key=f"qual_save_{logged_user}"):
        save_locally("qual_local_storage", entry)

def sync_quality_to_google_sheet():
    storage_key = "qual_local_storage"
    if storage_key not in st.session_state or len(st.session_state[storage_key]) == 0:
        st.warning("No local quality data to sync!")
        return
    sheet = get_gsheet_data(SHEET_NAME)
    if sheet is None:
        st.error("Cannot connect to Google Sheet.")
        return
    try:
        worksheet_name = "Quality_History"
        try:
            worksheet = sheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=worksheet_name, rows="1000", cols="50")

        all_keys = set()
        for entry in st.session_state[storage_key]:
            all_keys.update(entry.keys())
        all_keys = list(all_keys)
        if "User" in all_keys:
            all_keys.remove("User")
        all_keys = ["User"] + all_keys

        worksheet_values = worksheet.get_all_values()
        if worksheet_values:
            worksheet_header = worksheet_values[0]
            for key in all_keys:
                if key not in worksheet_header:
                    worksheet.update_cell(1, len(worksheet_header) + 1, key)
                    worksheet_header.append(key)
        else:
            worksheet.append_row(all_keys)

        for entry in st.session_state[storage_key]:
            row = [entry.get(key, "") for key in all_keys]
            worksheet.append_row(row)
        st.success(f"✅ Synced {len(st.session_state[storage_key])} quality records to Google Sheet.")
        st.session_state[storage_key] = []
    except Exception as e:
        st.error(f"Error syncing quality data: {str(e)}")

# ------------------ DOWNTIME DATA ENTRY ------------------
def downtime_data_entry(logged_user):
    if "downtime_config_df" not in st.session_state or "production_config_df" not in st.session_state:
        st.error("⚠️ Downtime_Config or Production_Config not loaded!")
        return
    df = st.session_state.downtime_config_df
    if df.empty:
        st.error("⚠️ Downtime_Config is empty!")
        return

    st.subheader("Please Enter the Downtime Data")
    products = st.session_state.production_config_df['Product'].unique().tolist()
    selected_product = st.selectbox("Select Planned Item", products, key=f"downtime_product_{logged_user}")
    now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
    st.write(f"📅 Date & Time: {now}")

    entry = {"User": logged_user, "Planned Item": selected_product, "DateTime": now}
    for col in df.columns:
        options = df[col].dropna().tolist()
        if options:
            entry[col] = st.selectbox(col, options, key=f"downtime_{col}_{logged_user}")
        else:
            entry[col] = st.text_input(col, key=f"downtime_{col}_{logged_user}")

    if st.button("Save Locally", key=f"downtime_save_{logged_user}"):
        save_locally("downtime_local_storage", entry)

def sync_downtime_to_google_sheet():
    storage_key = "downtime_local_storage"
    if storage_key not in st.session_state or len(st.session_state[storage_key]) == 0:
        st.warning("No local downtime data to sync!")
        return
    sheet = get_gsheet_data(SHEET_NAME)
    if sheet is None:
        st.error("Cannot connect to Google Sheet.")
        return
    try:
        worksheet_name = "Downtime_History"
        try:
            worksheet = sheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=worksheet_name, rows="1000", cols="50")

        all_keys = set()
        for entry in st.session_state[storage_key]:
            all_keys.update(entry.keys())
        all_keys = list(all_keys)
        if "User" in all_keys:
            all_keys.remove("User")
        all_keys = ["User"] + all_keys

        worksheet_values = worksheet.get_all_values()
        if worksheet_values:
            worksheet_header = worksheet_values[0]
            for key in all_keys:
                if key not in worksheet_header:
                    worksheet.update_cell(1, len(worksheet_header) + 1, key)
                    worksheet_header.append(key)
        else:
            worksheet.append_row(all_keys)

        for entry in st.session_state[storage_key]:
            row = [entry.get(key, "") for key in all_keys]
            worksheet.append_row(row)
        st.success(f"✅ Synced {len(st.session_state[storage_key])} downtime records to Google Sheet.")
        st.session_state[storage_key] = []
    except Exception as e:
        st.error(f"Error syncing downtime data: {str(e)}")

# ------------------ MAIN APP ------------------
st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)
menu = ["Home", "Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
choice = st.sidebar.selectbox("Menu", menu)

sheet = get_gsheet_data(SHEET_NAME)

# Load initial config sheets
if sheet:
    if "production_config_df" not in st.session_state:
        st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
    if "quality_config_df" not in st.session_state:
        st.session_state.quality_config_df = read_sheet(sheet, QUALITY_CONFIG_SHEET)
    if "downtime_config_df" not in st.session_state:
        st.session_state.downtime_config_df = read_sheet(sheet, DOWNTIME_CONFIG_SHEET)

# ------------------ MENU ------------------
if choice == "Home":
    st.markdown("<h2 style='text-align: center;'>Welcome to Die Casting Production App</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center;'>Please select a section to continue</h4>", unsafe_allow_html=True)

# ------------------ PRODUCTION TEAM LOGIN ------------------
elif choice == "Production Team Login":
    if "prod_logged_in" not in st.session_state:
        st.session_state.prod_logged_in = False
        st.session_state.logged_user = ""
    if not st.session_state.prod_logged_in:
        with st.form(key="prod_login_form"):
            selected_user = st.selectbox("Select Username", list(USER_CREDENTIALS.keys()))
            entered_password = st.text_input("Enter Password", type="password")
            submitted = st.form_submit_button("Login")
            logout = st.form_submit_button("Logout")
        if submitted:
            actual_password = USER_CREDENTIALS.get(selected_user)
            if actual_password and entered_password == actual_password:
                st.session_state.prod_logged_in = True
                st.session_state.logged_user = selected_user
                st.success(f"Welcome, {selected_user}!")
            else:
                st.error("❌ Incorrect password!")
        if logout:
            st.session_state.prod_logged_in = False
            st.session_state.logged_user = ""
    else:
        if st.button("🔄 Refresh Production Config Data"):
            st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
            st.success("Production Config refreshed!")
        production_data_entry(st.session_state.logged_user)
        if st.button("📤 Sync Production Data to Google Sheet"):
            sync_production_to_google_sheet()

# ------------------ QUALITY TEAM LOGIN ------------------
elif choice == "Quality Team Login":
    if "qual_logged_in" not in st.session_state:
        st.session_state.qual_logged_in = False
        st.session_state.qual_logged_user = ""
    if not st.session_state.qual_logged_in:
        with st.form(key="qual_login_form"):
            entered_user = st.text_input("Enter your name")
            entered_password = st.text_input("Enter Password", type="password")
            submitted = st.form_submit_button("Login")
            logout = st.form_submit_button("Logout")
        if submitted:
            if entered_password == QUALITY_SHARED_PASSWORD and entered_user.strip() != "":
                st.session_state.qual_logged_in = True
                st.session_state.qual_logged_user = entered_user.strip()
                st.success(f"Welcome, {st.session_state.qual_logged_user}!")
            else:
                st.error("❌ Incorrect password or empty username!")
        if logout:
            st.session_state.qual_logged_in = False
            st.session_state.qual_logged_user = ""
    else:
        if st.button("🔄 Refresh Quality Config Data"):
            st.session_state.quality_config_df = read_sheet(sheet, QUALITY_CONFIG_SHEET)
            st.success("Quality Config refreshed!")
        quality_data_entry(st.session_state.qual_logged_user)
        if st.button("📤 Sync Quality Data to Google Sheet"):
            sync_quality_to_google_sheet()

# ------------------ DOWNTIME DATA RECORDINGS ------------------
elif choice == "Downtime Data Recordings":
    if "downtime_logged_in" not in st.session_state:
        st.session_state.downtime_logged_in = False
        st.session_state.downtime_logged_user = ""
    if not st.session_state.downtime_logged_in:
        with st.form(key="downtime_login_form"):
            entered_user = st.text_input("Enter your name")
            entered_password = st.text_input("Enter Password", type="password")
            submitted = st.form_submit_button("Login")
            logout = st.form_submit_button("Logout")
        if submitted:
            if entered_password == DOWNTIME_SHARED_PASSWORD and entered_user.strip() != "":
                st.session_state.downtime_logged_in = True
                st.session_state.downtime_logged_user = entered_user.strip()
                st.success(f"Welcome, {st.session_state.downtime_logged_user}!")
            else:
                st.error("❌ Incorrect password or empty username!")
        if logout:
            st.session_state.downtime_logged_in = False
            st.session_state.downtime_logged_user = ""
    else:
        if st.button("🔄 Refresh Downtime Config Data"):
            st.session_state.downtime_config_df = read_sheet(sheet, DOWNTIME_CONFIG_SHEET)
            st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
            st.success("Downtime and Production Config refreshed!")
        downtime_data_entry(st.session_state.downtime_logged_user)
        if st.button("📤 Sync Downtime Data to Google Sheet"):
            sync_downtime_to_google_sheet()

