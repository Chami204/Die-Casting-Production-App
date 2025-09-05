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

QUALITY_SHARED_PASSWORD = "123"      # Same for all quality users
DOWNTIME_SHARED_PASSWORD = "1234"    # Same for all downtime users

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

    if st.button("Save Locally"):
        save_locally(entry, "prod_local_data")

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

    if st.button("Save Locally"):
        save_locally(entry, "qual_local_data")

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

    if st.button("Save Locally"):
        save_locally(entry, "downtime_local_data")

    if st.button("Logout"):
        st.session_state.downtime_logged_in = False
        st.session_state.downtime_logged_user = ""
        st.experimental_rerun()

# ------------------ APP CONFIG ------------------
st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)

menu = ["Home", "Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
choice = st.sidebar.selectbox("Menu", menu)

sheet = get_gsheet_data(SHEET_NAME)
if sheet:
    if "production_config_df" not in st.session_state:
        st.session_state.production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
    if "quality_config_df" not in st.session_state:
        st.session_state.quality_config_df = read_sheet(sheet, QUALITY_CONFIG_SHEET)
    if "downtime_config_df" not in st.session_state:
        st.session_state.downtime_config_df = read_sheet(sheet, DOWNTIME_CONFIG_SHEET)

# ------------------ HOME ------------------
if choice == "Home":
    st.markdown("<h2 style='text-align: center;'>Welcome to Die Casting Production App</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center;'>Please select a section to continue</h4>", unsafe_allow_html=True)

# ------------------ PRODUCTION LOGIN ------------------
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

# ------------------ QUALITY LOGIN ------------------
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

# ------------------ DOWNTIME LOGIN ------------------
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

