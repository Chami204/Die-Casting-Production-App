import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

# ------------------ Settings ------------------
APP_TITLE = "Die Casting Production"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SRI_LANKA_TZ = pytz.timezone('Asia/Colombo')

# ------------------ Hardcoded User Credentials ------------------
USER_CREDENTIALS = {
    "chami": "123",
    "user1": "user123",
    "user2": "user456"
}

# Example Excel file path (replace with actual path or Google Sheet connector)
EXCEL_FILE = "FlowApp_Data.xlsx"

# ------------------ Utility Functions ------------------
def load_production_data():
    """Load production data from Excel."""
    try:
        df = pd.read_excel(EXCEL_FILE)
        return df
    except FileNotFoundError:
        st.warning("Excel file not found. Creating a new one.")
        df = pd.DataFrame(columns=["Date", "Machine", "Product", "Quantity"])
        df.to_excel(EXCEL_FILE, index=False)
        return df

def save_production_data(df):
    """Save production data to Excel."""
    df.to_excel(EXCEL_FILE, index=False)

# ------------------ Login Section ------------------
def login():
    st.title(APP_TITLE)
    st.subheader("Login to Continue")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
            st.success(f"Welcome {username}!")
            st.experimental_rerun()
        else:
            st.error("Invalid username or password")

# ------------------ Admin Section ------------------
def admin_section():
    st.subheader("Admin Dashboard")
    st.info("Admin can view or directly edit production data here.")

    # Load data
    df = load_production_data()

    # Display editable data table
    edited_df = st.data_editor(df, num_rows="dynamic")

    # Save button
    if st.button("Save Changes"):
        save_production_data(edited_df)
        st.success("Changes saved successfully!")

# ------------------ Production Data Entry Section ------------------
def production_data_entry():
    st.subheader("Production Data Entry")

    # Initialize session state for data cache
    if "production_df" not in st.session_state:
        st.session_state.production_df = load_production_data()

    # Manual Refresh Button
    if st.button("🔄 Refresh Data from Excel"):
        st.session_state.production_df = load_production_data()
        st.success("Data refreshed successfully!")

    # Data Entry Form
    with st.form("production_form", clear_on_submit=True):
        date = st.date_input("Date", datetime.now().date())
        machine = st.text_input("Machine")
        product = st.text_input("Product")
        quantity = st.number_input("Quantity", min_value=0, step=1)

        submitted = st.form_submit_button("Add Record")

        if submitted:
            new_data = pd.DataFrame([{
                "Date": date,
                "Machine": machine,
                "Product": product,
                "Quantity": quantity
            }])
            st.session_state.production_df = pd.concat(
                [st.session_state.production_df, new_data],
                ignore_index=True
            )
            save_production_data(st.session_state.production_df)
            st.success("Record added successfully!")

    st.markdown("### Current Production Data")
    st.dataframe(st.session_state.production_df)

# ------------------ Logout ------------------
def logout():
    st.session_state.clear()
    st.experimental_rerun()

# ------------------ Main App ------------------
def main():
    if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
        login()
    else:
        st.sidebar.title(f"Welcome, {st.session_state['username']}")
        menu = ["Production Data Entry", "Admin Dashboard", "Logout"]

        choice = st.sidebar.radio("Navigation", menu)

        if choice == "Production Data Entry":
            production_data_entry()
        elif choice == "Admin Dashboard":
            if st.session_state["username"] == "admin":
                admin_section()
            else:
                st.error("Access denied. Admins only.")
        elif choice == "Logout":
            logout()

# ------------------ Run App ------------------
if __name__ == "__main__":
    main()
