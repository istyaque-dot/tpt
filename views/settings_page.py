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
    unit = st.radio("Rate kis hisaab se likhte ho", ["QUINTAL", "TON"], horizontal=True,
                    index=0 if (s.get("rate_unit", "QUINTAL") or "QUINTAL").upper() == "QUINTAL" else 1,
                    format_func=lambda x: "₹ per quintal" if x == "QUINTAL" else "₹ per ton",
                    help="Sirf likhne/dikhane ka tareeka. Hisaab andar per ton hi rehta hai (1 ton = 10 quintal), "
                         "isliye badalne se purani trips ka paisa nahi badalta.")
    mrf = st.radio("Paste kiye message mein rate kiska hota hai", ["TRUCK", "PARTY"], horizontal=True,
                   index=0 if (s.get("message_rate_for", "TRUCK") or "TRUCK").upper() == "TRUCK" else 1,
                   format_func=lambda x: "Truck ka bhada" if x == "TRUCK" else "Party freight")
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
        for k, v in {"company_name": company, "default_tds_rate": tds, "rate_unit": unit,
                     "message_rate_for": mrf, "freight_basis": basis,
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
st.subheader("🤖 AI (Google Gemini)")
from core import ai  # noqa: E402
if ai.configured():
    st.caption("AI juda hai: message padhna, GR/POD photo padhna, scanned POD ko GR-wise kaatna. "
               "AI kabhi khud Save nahi karta. Free plan mein Google data ko apne AI sudhaarne mein use kar sakta hai.")
    if st.button("Test AI"):
        try:
            st.success(f"AI chal raha hai: {ai.test()}")
        except ai.AIError as e:
            st.error(str(e))
else:
    st.info("AI band hai. aistudio.google.com → Get API key → Streamlit Secrets mein sabse upar "
            "`GEMINI_API_KEY = \"...\"` daalo. Bina AI ke bhi app purane tareeke se chalti rahegi.")

st.divider()
st.subheader("📃 Bill details")
st.caption("Party ke freight bill (Party: POD & Payment → Bill banao) par ye chhapega.")
with st.form("bill_settings"):
    addr = st.text_area("Pata (address)", value=s.get("company_address", ""), height=70)
    c1, c2 = st.columns(2)
    gstin = c1.text_input("Aapka GSTIN", value=s.get("company_gstin", ""))
    pan = c2.text_input("PAN", value=s.get("company_pan", ""))
    c1, c2 = st.columns(2)
    mob = c1.text_input("Mobile", value=s.get("company_mobile", ""))
    sac = c2.text_input("SAC code", value=s.get("bill_sac", "996791"), help="GTA (road goods transport): 996791")
    bank = st.text_area("Bank details (bill ke neeche)", value=s.get("company_bank", ""), height=70,
                        placeholder="A/c name, A/c no., IFSC, Bank")
    from core import bills as _bills  # noqa: E402
    modes = list(_bills.GST_MODES)
    cur_mode = (s.get("bill_gst_mode", "NONE") or "NONE").upper()
    c1, c2 = st.columns(2)
    gmode = c1.selectbox("GST (default)", modes, index=modes.index(cur_mode) if cur_mode in modes else 0,
                         format_func=_bills.GST_MODES.get)
    grate = c2.number_input("GST % (default)", min_value=0.0, max_value=28.0, step=1.0,
                            value=float(s.get("bill_gst_rate", "5") or 5))
    st.caption("GST kaunsa lagega ye apne CA se pakka kar lo — app sirf aapki choice ke hisaab se bill banata hai.")
    if st.form_submit_button("Save bill details", type="primary"):
        for k, v in {"company_address": addr.strip(), "company_gstin": gstin.strip().upper(),
                     "company_pan": pan.strip().upper(), "company_mobile": mob.strip(), "bill_sac": sac.strip(),
                     "company_bank": bank.strip(), "bill_gst_mode": gmode, "bill_gst_rate": grate}.items():
            db.save_setting(k, v)
        st.success("Saved.")

st.divider()
st.subheader("💾 Backup")
from core import backup  # noqa: E402
last = db.setting("last_auto_backup", "") or ""
if drive.configured():
    st.caption("Roz pehli baar app kholne par saari tables ka zip Google Drive → "
               f"{s.get('drive_root_folder_name', 'Transport Docs')}/Backups mein apne aap jaata hai "
               f"(aakhri {backup.KEEP} rakhe jaate hain).")
    if "FAILED" in last:
        st.error(f"Aakhri auto backup fail: {last}")
    elif last:
        st.success(f"Aakhri auto backup: {last}")
    if st.button("☁️ Abhi Drive par backup karo", use_container_width=True):
        try:
            with st.spinner("Backup ho raha hai..."):
                name = backup.file_name()
                backup.to_drive(backup.make_zip(), name)
            db.save_setting("last_auto_backup", f"{clock.today()} {clock.now():%H:%M} ok {name}")
            st.success(f"Drive par save: {name}")
        except Exception as e:
            st.error(f"Backup nahi hua: {e}")
else:
    st.warning("Auto backup ke liye Google Drive jodo (README). Tab tak hafte mein ek baar neeche se download karo.")
if st.button("Prepare backup (download)", use_container_width=True):
    st.download_button("⬇ Download backup zip", backup.make_zip(), file_name=backup.file_name(),
                       mime="application/zip", use_container_width=True)

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
