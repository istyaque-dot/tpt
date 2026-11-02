import streamlit as st

st.set_page_config(page_title="Transport Accounts", page_icon="🚚", layout="wide",
                   initial_sidebar_state="collapsed")

from core import db, nav, ui  # noqa: E402

ui.mobile_css()

if not ui.login_gate():
    st.stop()

P = {
    "home": st.Page("views/home.py", title="Home", icon="🏠", default=True),
    "new_trip": st.Page("views/new_trip.py", title="New Trip", icon="➕"),
    "truck_advance": st.Page("views/truck_advance.py", title="Truck Advance", icon="💸"),
    "party_receipt": st.Page("views/party_receipt.py", title="Party Receipt", icon="💵"),
    "settlement": st.Page("views/settlement.py", title="Truck Settlement", icon="🧾"),
    "trips": st.Page("views/trips.py", title="Trips", icon="🚚"),
    "party_settlement": st.Page("views/party_settlement.py", title="Party: POD & Payment", icon="🏢"),
    "payments": st.Page("views/payments.py", title="Cash / Bank Entry", icon="💰"),
    "documents": st.Page("views/documents.py", title="GR / POD Documents", icon="📄"),
    "dashboard": st.Page("views/dashboard.py", title="Dashboard", icon="📈"),
    "statements": st.Page("views/statements.py", title="Statements", icon="📑"),
    "reports": st.Page("views/reports.py", title="Reports & Ledgers", icon="📊"),
    "check": st.Page("views/check.py", title="Hisaab Check", icon="🧮"),
    "masters": st.Page("views/masters.py", title="Masters", icon="📇"),
    "settings": st.Page("views/settings_page.py", title="Settings", icon="⚙️"),
}
nav.PAGES.clear()
nav.PAGES.update(P)

with st.sidebar:
    st.caption(db.setting("company_name", "My Transport"))
    if st.session_state.get("remember"):
        st.caption("🔒 Remembered on this phone. Add this page to Home screen now — the icon will open "
                   "without a password. Do not share this link.")
    if st.button("Logout", use_container_width=True):
        ui.logout()
        st.rerun()

page = st.navigation({
    "Daily work": [P["home"], P["new_trip"], P["truck_advance"], P["settlement"], P["party_settlement"], P["party_receipt"],
                   P["trips"], P["payments"], P["documents"]],
    "Books": [P["statements"], P["dashboard"], P["reports"], P["check"]],
    "Setup": [P["masters"], P["settings"]],
})
ui.show_flash()
page.run()
