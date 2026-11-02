import streamlit as st

from core import clock, db, drive

st.markdown("### ⚙️ Settings")
s = db.get_settings()

with st.form("settings"):
    company = st.text_input("Company name", value=s.get("company_name", ""))
    st.markdown("**Defaults for new trips** (old trips keep their own values)")
    tds = st.number_input("Party TDS % (party freight se kaatti hai)", min_value=0.0, max_value=10.0, step=0.5,
                          value=float(s.get("default_tds_rate", "1") or 0),
                          help="Har nayi trip mein ye % pehle se bhara aayega; trip mein badal sakte ho.")
    st.caption("Commission har trip mein haath se ₹ mein likha jaata hai.")
    basis = st.selectbox("Freight & hire charged on", ["LOADED", "UNLOADED"],
                         index=0 if s.get("freight_basis", "LOADED") == "LOADED" else 1,
                         format_func=lambda x: f"{x.title()} weight")
    st.markdown("**Rules**")
    req_gr = st.checkbox("GR No. must be filled before truck balance payment",
                         value=s.get("require_gr_for_truck_balance") == "true")
    pod_auto = st.checkbox("Uploading a POD copy marks the trip 'POD received'",
                           value=s.get("pod_upload_marks_received") == "true")
    root = st.text_input("Google Drive main folder name", value=s.get("drive_root_folder_name", "Transport Docs"),
                         help="Change this only before the first upload.")
    if st.form_submit_button("Save settings", type="primary"):
        for k, v in {"company_name": company, "default_tds_rate": tds, "freight_basis": basis,
                     "require_gr_for_truck_balance": str(req_gr).lower(),
                     "pod_upload_marks_received": str(pod_auto).lower(),
                     "drive_root_folder_name": root.strip() or "Transport Docs"}.items():
            db.save_setting(k, v)
        st.success("Saved.")

st.divider()
st.subheader("Google Drive")
if drive.configured():
    if st.button("Test Drive connection"):
        try:
            fid = drive.test_connection()
            st.success(f"Connected. Main folder: https://drive.google.com/drive/folders/{fid}")
        except Exception as e:
            st.error(f"Drive error: {e}")
else:
    st.warning("Not connected. Add [google_drive] keys in Streamlit secrets (see README).")

st.divider()
st.subheader("Backup")
st.caption("Download everything (all tables) as one zip of CSV files. Keep a copy every week on your computer / "
           "Google Drive — the free Supabase plan has no automatic restore.")
if st.button("Prepare backup", use_container_width=True):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tbl in ("settings", "accounts", "trucks", "lookups", "trips", "vouchers", "ledger_entries",
                    "trip_documents", "audit_log"):
            try:
                z.writestr(f"{tbl}.csv", db.df(f"select * from {tbl} order by 1").to_csv(index=False))
            except Exception as e:  # table may not exist on an old database
                z.writestr(f"{tbl}_ERROR.txt", str(e))
    st.download_button("⬇ Download backup zip", buf.getvalue(),
                       file_name=f"transport_backup_{clock.today()}.zip", mime="application/zip",
                       use_container_width=True)

st.divider()
st.subheader("Edit history")
st.caption("Who created, changed or cancelled what — latest first.")
try:
    log = db.query("select at, username, entity, entity_id, action, details from audit_log "
                   "order by id desc limit 200")
except Exception:
    log = []
    st.info("Run the latest schema.sql once to start keeping edit history.")
if log:
    import pandas as pd
    st.dataframe(pd.DataFrame([{"When": r["at"].astimezone(clock.IST).strftime("%d/%m %H:%M"), "User": r["username"],
                                "What": f"{r['entity']} #{r['entity_id']}", "Action": r["action"],
                                "Details": str(r["details"])[:200]} for r in log]),
                 hide_index=True, use_container_width=True)
