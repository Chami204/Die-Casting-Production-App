FIXED_SUBTOPICS = [
    "Input number of pcs",
    "Input time",
    "Output number of pcs",
    "Output time",
    "Num of pcs to rework",
    "Number of rejects"
]

# Ensure history sheet has proper headers
def ensure_history_headers(ws_history):
    headers = ws_history.row_values(1)
    if not headers or headers[0] != "EntryID":
        headers = ["EntryID", "Timestamp", "Product"] + FIXED_SUBTOPICS + ["Comments"]
        ws_history.clear()
        ws_history.update("A1", [headers])
        ws_history.freeze(rows=1)
    return headers

# User UI
def user_ui(cfg: dict, ws_history):
    st.subheader("User • Enter Data")
    if not cfg:
        st.info("No products available yet. Ask Admin to create a product in Admin mode.")
        return

    ensure_history_headers(ws_history)

    product = st.selectbox("Select Main Product", sorted(cfg.keys()))
    if not product:
        return

    st.write("Fill **all fields** below:")
    values = {}

    # Only allow numeric input for number of pcs fields
    values["Input number of pcs"] = st.number_input("Input number of pcs", min_value=0, step=1)
    values["Input time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values["Output number of pcs"] = st.number_input("Output number of pcs", min_value=0, step=1)
    values["Output time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values["Num of pcs to rework"] = st.number_input("Num of pcs to rework", min_value=0, step=1)
    values["Number of rejects"] = st.number_input("Number of rejects", min_value=0, step=1)
    comments = st.text_area("Comments")

    if st.button("Submit"):
        entry_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "EntryID": entry_id,
            "Timestamp": timestamp,
            "Product": product,
            **values,
            "Comments": comments
        }
        # Append in order of headers
        headers = ws_history.row_values(1)
        row = [record.get(h, "") for h in headers]
        ws_history.append_row(row, value_input_option="USER_ENTERED")
        st.success(f"Saved! EntryID: {entry_id}")

    # Display recent entries
    all_records = ws_history.get_all_records()
    if all_records:
        df = pd.DataFrame(all_records)
        df = df[df["Product"] == product].sort_values(by="Timestamp", ascending=False).head(30)
        st.subheader("Recent Entries (for this product)")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No entries yet.")
