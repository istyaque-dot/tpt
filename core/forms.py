"""Entry forms + popups, shared by Home, Trips and Payments. Built for phone use:
max 2 fields per row, empty number boxes, last-used cash/bank and pump remembered."""

import psycopg2
import streamlit as st

from core import calc, clock, db, drive, nav, trips, ui


def _money_account(key: str):
    accs = db.money_accounts()
    if not accs:
        st.warning("Add Cash/Bank in Masters.")
        return None
    ids = [a["id"] for a in accs]
    names = {a["id"]: a["name"] for a in accs}
    return st.selectbox("Cash / Bank", ids, format_func=names.get, key=key,
                        index=ui.remembered("money", ids))


def _done(msg: str, money_acc=None, pump=None):
    if money_acc:
        ui.remember("money", money_acc)
    if pump:
        ui.remember("pump", pump)
    ui.flash(msg)
    st.rerun()


# ---------- Single-trip entry forms ----------

def party_receipt_single(trip: dict, key: str):
    st.markdown(f"**{trip['party_name']}** · balance ₹ {ui.inr(trip['party_balance'])}")
    with st.form(key, clear_on_submit=True):
        amount = ui.amount("Amount ₹", f"{key}_amt")
        c1, c2 = st.columns(2)
        with c1:
            acc = _money_account(f"{key}_acc")
        v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        purpose = st.radio("Type", ["ADVANCE", "BALANCE"], horizontal=True,
                           index=0 if not calc.is_loaded(trip) else 1, format_func=str.title)
        ref = st.text_input("Ref / UTR (optional)")
        if st.form_submit_button("Save receipt", type="primary"):
            if amount <= 0 or not acc:
                st.error("Enter amount.")
                return
            with db.tx() as cur:
                trips.add_voucher(cur, v_date=v_date, v_type="RECEIPT", purpose=purpose, trip_id=trip["id"],
                                  amount=amount, dr_account=acc, cr_account=trip["party_id"], ref_no=ref,
                                  narration=f"{purpose.title()} from party {trip['trip_no']}")
            _done(f"Receipt ₹{ui.inr(amount)} saved for {trip['trip_no']}", money_acc=acc)


def truck_payment_single(trip: dict, key: str):
    if not trip.get("truck_id"):
        st.info("Assign a truck first.")
        return
    st.markdown(f"**{trip['truck_no']}** · {trip['owner_name']} · balance ₹ {ui.inr(trip['truck_balance'])}")
    with st.form(key, clear_on_submit=True):
        amount = ui.amount("Amount ₹", f"{key}_amt")
        c1, c2 = st.columns(2)
        with c1:
            acc = _money_account(f"{key}_acc")
        v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        purpose = st.radio("Type", ["ADVANCE", "BALANCE"], horizontal=True,
                           index=1 if trip.get("pod_received") else 0, format_func=str.title)
        ref = st.text_input("Ref / UTR (optional)")
        allow_over = st.checkbox("Allow more than balance")
        if st.form_submit_button("Save payment", type="primary"):
            errs = calc.check_truck_payment(trip, trip, purpose, amount,
                                            db.setting_bool("require_gr_for_truck_balance"), allow_over)
            if not acc:
                errs.append("Select cash/bank.")
            if errs:
                ui.show_errors(errs)
                return
            with db.tx() as cur:
                trips.add_voucher(cur, v_date=v_date, v_type="PAYMENT", purpose=purpose, trip_id=trip["id"],
                                  amount=amount, dr_account=trip["owner_id"], cr_account=acc, ref_no=ref,
                                  narration=f"Truck {purpose.lower()} {trip['truck_no']} {trip['trip_no']}")
            _done(f"Truck payment ₹{ui.inr(amount)} saved for {trip['truck_no']}", money_acc=acc)


def diesel_single(trip: dict, key: str):
    if not trip.get("truck_id"):
        st.info("Assign a truck first.")
        return
    pumps = db.accounts("PUMP")
    if not pumps:
        st.warning("Add a petrol pump in Masters.")
        return
    st.markdown(f"**{trip['truck_no']}** · diesel is deducted from truck hire")
    pids = [p["id"] for p in pumps]
    pnames = {p["id"]: p["name"] for p in pumps}
    with st.form(key, clear_on_submit=True):
        amount = ui.amount("Amount ₹", f"{key}_amt", help="Leave blank to use Litres × Rate")
        c1, c2 = st.columns(2)
        pump = c1.selectbox("Pump", pids, format_func=pnames.get, index=ui.remembered("pump", pids))
        v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        c1, c2 = st.columns(2)
        with c1:
            litres = ui.amount("Litres", f"{key}_l", step=1.0)
        with c2:
            rate = ui.amount("Rate", f"{key}_r", step=0.1)
        ref = st.text_input("Pump slip No. (optional)")
        if st.form_submit_button("Save diesel", type="primary"):
            amt = amount if amount > 0 else calc.r2(litres * rate)
            if amt <= 0 or not pump:
                st.error("Enter amount (or litres and rate).")
                return
            with db.tx() as cur:
                trips.add_voucher(cur, v_date=v_date, v_type="DIESEL", purpose="DIESEL", trip_id=trip["id"],
                                  amount=amt, dr_account=trip["owner_id"], cr_account=pump,
                                  litres=litres or None, rate=rate or None, ref_no=ref,
                                  narration=f"Diesel {trip['truck_no']} {trip['trip_no']}")
            _done(f"Diesel ₹{ui.inr(amt)} saved for {trip['truck_no']}", pump=pump)


# ---------- Popups (dialogs) ----------

@st.dialog("💸 Truck payment")
def truck_payment_dialog(trip_id: int):
    truck_payment_single(trips.get_trip(trip_id), f"dlg_tp_{trip_id}")


@st.dialog("⛽ Diesel")
def diesel_dialog(trip_id: int):
    diesel_single(trips.get_trip(trip_id), f"dlg_ds_{trip_id}")


@st.dialog("💵 Party receipt")
def party_receipt_dialog(trip_id: int):
    party_receipt_single(trips.get_trip(trip_id), f"dlg_pr_{trip_id}")


@st.dialog("🧾 GR No.")
def gr_dialog(trip_id: int):
    t = trips.get_trip(trip_id)
    st.markdown(ui.trip_summary_md(t))
    with st.form(f"dlg_gr_{trip_id}"):
        gr = st.text_input("GR No.", value=t["gr_no"] or "")
        gr_date = st.date_input("GR date", value=t["gr_date"] or clock.today(), format="DD/MM/YYYY")
        if st.form_submit_button("Save GR", type="primary", use_container_width=True):
            try:
                trips.update_trip(trip_id, {"gr_no": gr, "gr_date": gr_date if gr.strip() else None})
                _done(f"GR {calc.normalize_gr(gr)} saved for {t['trip_no']}")
            except psycopg2.errors.UniqueViolation:
                st.error(f"GR No. {calc.normalize_gr(gr)} is already used in another trip.")


@st.dialog("📄 Upload GR / POD")
def upload_dialog(trip_id: int):
    t = trips.get_trip(trip_id)
    st.markdown(ui.trip_summary_md(t))
    documents_block(t, f"dlg_up_{trip_id}", show_list=False)


# ---------- Trip card (search results) ----------

def trip_card(t: dict, key: str):
    with st.container(border=True):
        st.markdown(ui.trip_summary_md(t))
        c1, c2 = st.columns(2)
        if c1.button("Open", key=f"{key}_open", use_container_width=True):
            nav.open_trip(t["id"])
        if not t["is_cancelled"]:
            with c2.popover("➕ Entry", use_container_width=True):
                if st.button("📑 Trip statement", key=f"{key}_stm", use_container_width=True):
                    nav.go("statements", stm_kind="🧾 Trip", stm_trip_id=t["id"])
                if st.button("🧾 Settle truck", key=f"{key}_st", use_container_width=True,
                             disabled=not calc.is_loaded(t)):
                    nav.go("settlement", settle_trip_id=t["id"])
                if st.button("🏢 Party settle / POD given", key=f"{key}_ps", use_container_width=True,
                             disabled=not calc.is_loaded(t)):
                    nav.go("party_settlement", psettle_id=t["id"])
                if st.button("💸 Truck payment", key=f"{key}_tp", use_container_width=True,
                             disabled=not t.get("truck_id")):
                    truck_payment_dialog(t["id"])
                if st.button("⛽ Diesel", key=f"{key}_ds", use_container_width=True,
                             disabled=not t.get("truck_id")):
                    diesel_dialog(t["id"])
                if st.button("💵 Party receipt", key=f"{key}_pr", use_container_width=True):
                    party_receipt_dialog(t["id"])
                if st.button("🧾 GR No." + (" (edit)" if t.get("gr_no") else ""), key=f"{key}_gr",
                             use_container_width=True):
                    gr_dialog(t["id"])
                if st.button("📄 Upload GR / POD", key=f"{key}_up", use_container_width=True):
                    upload_dialog(t["id"])


def search_box(key: str, quick_default="All open", limit=30):
    """Search field + quick filter chips + result cards."""
    q = st.text_input("🔎 Search", key=f"{key}_q", placeholder="Truck no. (last 4 digits), GR No., Trip No., party",
                      label_visibility="collapsed")
    opts = list(trips.QUICK_FILTERS)
    quick = st.pills("Show", opts, default=quick_default, key=f"{key}_quick",
                     label_visibility="collapsed") or "All"
    rows = trips.find_trips(q, quick, limit)
    st.caption(f"{len(rows)} trip(s)" + (" — showing latest" if len(rows) >= limit else ""))
    for t in rows:
        trip_card(t, f"{key}_{t['id']}")
    return rows


# ---------- Quick add (so a phone user never has to leave the booking screen) ----------

def quick_add_party(key: str):
    with st.popover("➕ New party", use_container_width=True):
        with st.form(f"{key}_qp", clear_on_submit=True):
            name = st.text_input("Party name *")
            mobile = st.text_input("Mobile")
            if st.form_submit_button("Add party", type="primary"):
                if not name.strip():
                    st.error("Name required.")
                    return
                try:
                    r = db.execute("insert into accounts (name, acc_type, mobile) values (%s,'PARTY',%s) returning id",
                                   (name.strip(), mobile.strip() or None))
                    st.session_state[f"{key}_new_party"] = r["id"]
                    _done(f"Party {name.strip()} added")
                except psycopg2.errors.UniqueViolation:
                    st.error("This party already exists.")


def quick_add_truck(key: str):
    with st.popover("➕ New truck", use_container_width=True):
        owners = db.accounts("OWNER")
        oids = [o["id"] for o in owners]
        onames = {o["id"]: o["name"] for o in owners}
        with st.form(f"{key}_qt", clear_on_submit=True):
            truck_no = st.text_input("Truck No. *", placeholder="RJ14AB1234")
            owner = st.selectbox("Owner (existing)", oids, format_func=onames.get, index=None,
                                 placeholder="Select owner")
            new_owner = st.text_input("…or new owner name")
            c1, c2 = st.columns(2)
            dname = c1.text_input("Driver name")
            dmob = c2.text_input("Driver mobile")
            if st.form_submit_button("Add truck", type="primary"):
                tn = calc.normalize_truck_no(truck_no)
                if not tn or not (owner or new_owner.strip()):
                    st.error("Truck No. and owner are required.")
                    return
                try:
                    with db.tx() as cur:
                        if not owner:
                            cur.execute("insert into accounts (name, acc_type) values (%s, 'OWNER') "
                                        "on conflict (acc_type, name) do update set active = true returning id",
                                        (new_owner.strip(),))
                            owner = cur.fetchone()["id"]
                        cur.execute("insert into trucks (truck_no, owner_id, driver_name, driver_mobile) "
                                    "values (%s,%s,%s,%s) returning id", (tn, owner, dname or None, dmob or None))
                        st.session_state[f"{key}_new_truck"] = cur.fetchone()["id"]
                    _done(f"Truck {tn} added")
                except psycopg2.errors.UniqueViolation:
                    st.error("This truck number already exists.")


# ---------- Documents ----------

def documents_block(trip: dict, key: str, show_list: bool = True):
    if show_list:
        docs = db.query("select * from trip_documents where trip_id=%s and not is_deleted order by uploaded_at",
                        (trip["id"],))
        for d in docs:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{d['doc_type']}** · [{d['file_name']}]({d['drive_link']})  \n"
                        f"{d['uploaded_at']:%d/%m/%Y} · {(d['size_bytes'] or 0) // 1024} KB")
            if c2.button("🗑", key=f"{key}_del_{d['id']}", help="Delete this file"):
                st.session_state[f"{key}_confirm_del"] = d["id"]
        if not docs:
            st.caption("No documents yet.")
        did = st.session_state.get(f"{key}_confirm_del")
        if did:
            with st.form(f"{key}_delform"):
                reason = st.text_input("Reason for deleting the file *")
                if st.form_submit_button("Confirm delete"):
                    if not reason.strip():
                        st.error("Reason is required.")
                    else:
                        drive.trash(did, reason.strip())
                        st.session_state.pop(f"{key}_confirm_del", None)
                        st.rerun()

    if not drive.configured():
        st.warning("Google Drive is not connected yet. See README → Google Drive setup.")
        return

    upload_widget(trip, key)


def upload_widget(trip: dict, key: str, doc_type: str | None = None, label: str | None = None):
    """File picker (phone camera or gallery) + Upload button. doc_type fixed -> no type choice shown."""
    if not drive.configured():
        st.warning("Google Drive is not connected yet. See README → Google Drive setup.")
        return
    if doc_type is None:
        doc_type = st.radio("Document", ["POD", "GR", "OTHER"], horizontal=True, key=f"{key}_type")
    n = st.session_state.get(f"{key}_n", 0)   # changes after each upload so the picker clears
    files = st.file_uploader(label or f"{doc_type} photo / PDF (camera or gallery, many at once)",
                             accept_multiple_files=True,
                             type=["jpg", "jpeg", "png", "pdf", "webp"], key=f"{key}_files_{n}")
    if st.button(f"⬆ Upload {doc_type}", type="primary", key=f"{key}_upload", disabled=not files,
                 use_container_width=True):
        with st.spinner("Uploading to Google Drive..."):
            for f in files:
                drive.upload(trip, doc_type, f.name or "photo.jpg", f.getvalue(), f.type or "image/jpeg",
                             st.session_state.get("user", "admin"))
        msg = f"{len(files)} file(s) uploaded to {trip['trip_no']}"
        if doc_type == "POD" and not trip.get("pod_received") and db.setting_bool("pod_upload_marks_received"):
            trips.update_trip(trip["id"], {"pod_received": True, "pod_date": clock.today()})
            msg += " · POD marked received"
        st.session_state[f"{key}_n"] = n + 1
        _done(msg)
