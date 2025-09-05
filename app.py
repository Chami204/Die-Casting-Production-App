import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')

# Default user credentials (hardcoded)
USER_CREDENTIALS = {
    "chami": "123",
    "user1": "user123",
    "user2": "user456"
}

# Example Excel file path
EXCEL_FILE = "FlowApp_Data.xlsx"

# ------------------ Utility Functions ------------------
def load_production_data():
    """Load production data from the Excel sheet."""
    try:
        df = pd.read_excel(EXCEL_FILE)
        return df
    except FileNotFoundError:
        st.warning("Excel file not found. Creating a new one.")
        df = pd.DataFrame(columns=["Date", "Machine", "Product", "Quantity"])
        df.to_excel(EXCEL_FILE, index=False)
        return df

def save_production_data(df):
    """Save production data to the Excel sheet."""
    df.to_excel(EXCEL_FILE, index=False)

# ------------------ Login ------------------
def login():
    st.title(APP_TITLE)
    st.subheader("Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
            st.success(f"Welcome {username}!")
        else:
            st.error("Invalid username or password")

# ------------------ Production Data Entry ------------------
def production_data_entry():
    st.subheader("Production Data Entry")

    # Initialize session state to keep section open
    if "keep_open" not in st.session_state:
        st.session_state.keep_open = True

    # Manual refresh button
    if st.button("🔄 Refresh Data from Excel"):
        st.session_state.production_df = load_production_data()
        st.success("Data refreshed successfully!")

    # Load production data into session state if not already loaded
    if "production_df" not in st.session_state:
        st.session_state.production_df = load_production_data()

    # Data entry form
    with st.form("production_form", clear_on_submit=True):
        date = st.date_input("Date", datetime.now().date())
        machine = st.text_input("Machine")
        product = st.text_input("Product")
        quantity = st.number_input("Quantity", min_value=0)

        submitted = st.form_submit_button("Add Record")

        if submitted:
            new_data = pd.DataFrame([{
                "Date": date,
                "Machine": machine,
                "Product": product,
                "Quantity": quantity
            }])

            st.session_state.production_df = pd.concat([st.session_state.production_df, new_data], ignore_index=True)
            save_production_data(st.session_state.production_df)
            st.success("Record added successfully!")

    # Display current data
    st.dataframe(st.session_state.production_df)

# ------------------ Main App ------------------
def main():
    if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
        login()
    else:
        st.sidebar.title("Navigation")
        page = st.sidebar.radio("Go to", ["Production Data Entry", "Logout"])

        if page == "Production Data Entry":
            production_data_entry()
        elif page == "Logout":
            st.session_state.clear()
            st.experimental_rerun()

# ------------------ Run App ------------------
if __name__ == "__main__":
    main()
