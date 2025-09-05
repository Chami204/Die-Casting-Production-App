# app.py
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz
import os
import json

# ---------------------------- SETTINGS ----------------------------
SHEET_NAME = "Your_Google_Sheet_Name"
PRODUCTION_CONFIG_SHEET = "Production_Config"
USER_CREDENTIALS_SHEET = "User_Credentials"
LOCAL_SAVE_FILE = "local_production_data.json"

SRI_LANKA_TZ = pytz.timezone("Asia/Colombo")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ------------------------ GOOGLE SHEETS --------------------------
def get_gsheet_data(sheet_name):
    creds = Credentials.from_service_account_file("service_account.json")
    gc = gspread.authorize(creds)
    sh = gc.open(sheet_name)
    return sh

def read_sheet(sheet, worksheet_name):
    worksheet = sheet.worksheet(worksheet_name)
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

def append_to_sheet(sheet, worksheet_name, data_dict):
    worksheet = sheet.worksheet(worksheet_name)
    # Prepare row in correct order
    existing_columns = worksheet.row_values(1)
    row = []
    for col in existing_columns:
        row.append(data_dict.get(col, ""))
    worksheet.append_row(row)

# ------------------------ LOCAL SAVE -----------------------------
def save_locally(data):
    if os.path.exists(LOCAL_SAVE_FILE):
        with open(LOCAL_SAVE_FILE, "r") as f:
            existing = json.load(f)
    else:
        existing = []
    existing.append(data)
    with open(LOCAL_SAVE_FILE, "w") as f:
        json.dump(existing, f)

def load_local_data():
    if os.path.exists(LOCAL_SAVE_FILE):
        with open(LOCAL_SAVE_FILE, "r") as f:
            return json.load(f)
    else:
        return []

def clear_local_data():
    if os.path.exists(LOCAL_SAVE_FILE):
        os.remove(LOCAL_SAVE_FILE)

# ------------------------ MAIN APP -------------------------------
st.set_page_config(page_title="Production App", page_icon="🛠️", layout="centered")

# MAIN MENU
st.title("🏭 Production App")

menu = ["Production Team Login", "Quality Team Login", "Downtime Data Recordings"]
choice = st.radio("Select an option", menu, index=0)

# Load Google Sheets
sheet = get_gsheet_data(SHEET_NAME)
production_config_df = read_sheet(sheet, PRODUCTION_CONFIG_SHEET)
user_credentials_df = read_sheet(sheet, USER_CREDENTIALS_SHEET)

# -------------------- PRODUCTION TEAM LOGIN -----------------------
if choice == "Production Team Login":
    st.header("🔑 Production Team Login")
    
    usernames = user_credentials_df['username'].tolist()
    selected_user = st.selectbox("Select Username", usernames)
    entered_password = st.text_input("Enter Password", type="password")
    
    if st.button("Login"):
        # Validate password
        actual_password = user_credentials_df.loc[user_credentials_df['username'] == selected_user, 'password'].values[0]
        if entered_password == actual_password:
            st.success(f"Welcome, {selected_user}!")
            
            # ------------------ PRODUCTION DATA ENTRY ------------------
            st.subheader("Pls Enter the Production Data")
            
            # Product dropdown
            products = production_config_df['Product'].unique().tolist()
            selected_product = st.selectbox("Select Product", products)
            
            # Show current date/time
            now = datetime.now(SRI_LANKA_TZ).strftime(TIME_FORMAT)
            st.write(f"📅 Date & Time: {now}")
            
            # Filter subtopics for selected product
            subtopics_df = production_config_df[production_config_df['Product'] == selected_product]
            
            production_entry = {}
            production_entry["Product"] = selected_product
            production_entry["DateTime"] = now
            for idx, row in subtopics_df.iterrows():
                if row["Dropdown or Not"].strip().lower() == "yes":
                    options = [opt.strip() for opt in row["Dropdown Options"].split(",")]
                    production_entry[row["Subtopic"]] = st.selectbox(row["Subtopic"], options, key=row["Subtopic"])
                else:
                    production_entry[row["Subtopic"]] = st.text_input(row["Subtopic"], key=row["Subtopic"])
            
            if st.button("Save Locally"):
                save_locally(production_entry)
                st.success("✅ Data saved locally!")
            
        else:
            st.error("❌ Incorrect password!")

# ------------------- SEND DATA TO GOOGLE SHEET -------------------
if choice == "Production Team Login":
    st.markdown("---")
    st.subheader("Send Local Data to Google Sheet")
    local_data = load_local_data()
    
    if local_data:
        st.write(f"{len(local_data)} local records ready to send.")
        if st.button("Pls send the data to the Google Sheet"):
            for record in local_data:
                append_to_sheet(sheet, "Production_Data", record)
            clear_local_data()
            st.success("✅ All data sent to Google Sheet successfully!")
    else:
        st.info("No local data to send.")
