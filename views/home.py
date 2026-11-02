import streamlit as st

from core import db, forms, nav

st.markdown(f"### 🚚 {db.setting('company_name', 'Transport')}")

c1, c2 = st.columns(2)
if c1.button("➕ New Trip", type="primary", use_container_width=True):
    nav.go("new_trip")
if c2.button("💸 Truck Advance", use_container_width=True):
    nav.go("truck_advance")
if st.button("🧾 Truck Settlement (POD · kat-kaat · balance)", use_container_width=True):
    nav.go("settlement")
c1, c2 = st.columns(2)
if c1.button("🏢 Party: POD & Payment", use_container_width=True):
    nav.go("party_settlement")
if c2.button("💵 Party Receipt (bank)", use_container_width=True):
    nav.go("party_receipt")
c1, c2 = st.columns(2)
if c1.button("💰 Cash / Bank Entry", use_container_width=True):
    nav.go("payments")
if c2.button("🧾 Fill GR No.", use_container_width=True):
    nav.go("documents")
if st.button("📑 Statements (Party · Pump · Owner · Trip)", use_container_width=True):
    nav.go("statements")
c1, c2 = st.columns(2)
if c1.button("📈 Dashboard", use_container_width=True):
    nav.go("dashboard")
if c2.button("📇 Masters", use_container_width=True):
    nav.go("masters")
c1, c2 = st.columns(2)
if c1.button("📊 Reports", use_container_width=True):
    nav.go("reports")
if c2.button("🧮 Hisaab Check", use_container_width=True):
    nav.go("check")

st.divider()
forms.search_box("home")
