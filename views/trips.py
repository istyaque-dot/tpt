
import pandas as pd
import psycopg2
import streamlit as st

from core import calc, checks, clock, db, forms, nav, trips, ui

tid = st.session_state.get("open_trip_id")
t = trips.get_trip(tid) if tid else None

# ====================== SEARCH (no trip open) ======================
if not t:
    st.markdown("### 🚚 Trips")
    if st.button("➕ New Trip", type="primary", use_container_width=True):
        nav.go("new_trip")
    forms.search_box("trips")
    st.stop()

# ====================== ONE TRIP ======================
lk = t["locks"]
dis = t["is_cancelled"]

c1, c2 = st.columns([1, 3])
if c1.button("← Back", use_container_width=True):
    st.session_state.pop("open_trip_id", None)
    st.rerun()
c2.markdown(f"### {t['trip_no']} · {ui.STATUS_ICON.get(t['status'], '')} {t['status']}")

with st.container(border=True):
    st.markdown(ui.trip_summary_md(t))
    ui.metric_grid([("Truck balance", ui.inr(t["truck_balance"])), ("Party balance", ui.inr(t["party_balance"]))])

if t["is_cancelled"]:
    st.error(f"Cancelled: {t['cancel_reason']}")
if calc.D(t["truck_balance"]) < -calc.SETTLED_TOLERANCE:
    st.warning("Truck balance is negative — the owner has been paid extra and owes us.")

NEXT = {
    "Booked": "Next: select truck & weight (✏️ Edit trip)",
    "Truck Assigned": "Next: enter weight (✏️ Edit trip)",
    "Loaded": "Next: GR No." if not t.get("gr_no") else "Next: POD received",
    "Unloaded": "Next: POD received",
    "POD Received": "Next: pay truck balance / receive party balance",
    "Truck Settled": "Next: receive party balance",
    "Party Settled": "Next: pay truck balance",
}
if not dis and NEXT.get(t["status"]):
    st.info(NEXT[t["status"]])

# ---------- quick actions ----------
if not dis:
    c1, c2 = st.columns(2)
    if c1.button("💸 Truck payment", use_container_width=True, disabled=not t.get("truck_id")):
        forms.truck_payment_dialog(t["id"])
    if c2.button("⛽ Diesel", use_container_width=True, disabled=not t.get("truck_id")):
        forms.diesel_dialog(t["id"])
    c1, c2 = st.columns(2)
    if c1.button("💵 Party receipt", use_container_width=True):
        forms.party_receipt_dialog(t["id"])
    if c2.button("🧾 GR No." + (" ✓" if t.get("gr_no") else ""), use_container_width=True):
        forms.gr_dialog(t["id"])
    c1, c2 = st.columns(2)
    if c1.button("🧾 Settle truck (POD, kat-kaat, balance)", use_container_width=True,
                 disabled=not calc.is_loaded(t), type="primary" if t["pod_received"] else "secondary"):
        nav.go("settlement", settle_trip_id=t["id"])
    if c2.button("⬆ Upload GR/POD", use_container_width=True):
        forms.upload_dialog(t["id"])
    if st.button("📑 Trip statement (advance, diesel, payments — PDF / WhatsApp)", use_container_width=True):
        nav.go("statements", stm_kind="🧾 Trip", stm_trip_id=t["id"])
    if st.button("🏢 Party settlement (POD given, shortage, demurrage, receive)", use_container_width=True,
                 disabled=not calc.is_loaded(t)):
        nav.go("party_settlement", psettle_id=t["id"])

if lk["truck"] or lk["party"]:
    st.caption("🔒 Settled parts are locked. To change them, cancel the settlement entry first.")


def num(label, key, value, step=10.0, fmt=None, disabled=False):
    kw = {"format": fmt} if fmt else {}
    v = st.number_input(label, min_value=0.0, step=step, key=key, disabled=disabled, placeholder="0",
                        value=float(value) if value not in (None, 0) else None, **kw)
    return calc.D(v)


# ---------- EDIT (same order as New Trip) ----------
with st.expander("✏️ Edit trip details", expanded=t["status"] in ("Booked", "Truck Assigned")):
    if not dis and not lk["truck"]:
        forms.quick_add_truck(f"tr_{t['id']}")
    trucks_ = db.query("select t.id, t.truck_no, a.name owner_name from trucks t "
                       "join accounts a on a.id=t.owner_id where t.active or t.id=%s order by t.truck_no",
                       (t["truck_id"],))
    tl = {r["id"]: f"{r['truck_no']} — {r['owner_name']}" for r in trucks_}
    tids = list(tl)
    new_t = st.session_state.get(f"tr_{t['id']}_new_truck")
    cur_truck = new_t if new_t in tids else t["truck_id"]
    parties = db.accounts("PARTY")
    pids = [p["id"] for p in parties]
    pn = {p["id"]: p["name"] for p in parties}
    places, materials = db.lookups("PLACE"), db.lookups("MATERIAL")
    for v in (t["from_place"], t["to_place"]):
        if v and v not in places:
            places.append(v)
    if t["material"] and t["material"] not in materials:
        materials.append(t["material"])

    d_truck, d_party, d_wt = dis or lk["truck"], dis or lk["party"], dis or lk["weights"]
    with st.form(f"edit_{t['id']}"):
        truck_id = st.selectbox("1. Truck No.", tids, format_func=tl.get, disabled=d_truck,
                                index=tids.index(cur_truck) if cur_truck in tids else None,
                                placeholder="Type last digits")
        to_place = st.selectbox("2. Destination", places, accept_new_options=True, disabled=d_party,
                                index=places.index(t["to_place"]) if t["to_place"] in places else None)
        c1, c2 = st.columns(2)
        with c1:
            weight = num("3. Loaded weight (T)", f"e_wt_{t['id']}", t["loaded_weight"], 0.5, "%.3f", d_wt)
        loading_date = c2.date_input("Loading date", value=t["loading_date"] or t["booking_date"],
                                     format="DD/MM/YYYY", disabled=d_wt)
        c1, c2 = st.columns(2)
        with c1:
            truck_rate = num("4. Truck rate ₹/ton", f"e_tr_{t['id']}", t["truck_rate"], disabled=d_truck)
        with c2:
            party_rate = num("5. Freight ₹/ton", f"e_pr_{t['id']}", t["party_rate"], disabled=d_party)
        party_id = st.selectbox("6. Freight paid by (company)", pids, format_func=pn.get, disabled=d_party,
                                index=pids.index(t["party_id"]) if t["party_id"] in pids else None)
        c1, c2 = st.columns(2)
        gr_no = c1.text_input("7. GR No.", value=t["gr_no"] or "", disabled=dis)
        gr_date = c2.date_input("GR date", value=t["gr_date"], format="DD/MM/YYYY", disabled=dis)
        remarks = st.text_area("8. Comment", value=t["remarks"] or "", height=80, disabled=dis)

        st.markdown("**Unloading, shortage, POD**")
        c1, c2 = st.columns(2)
        with c1:
            unloaded = num("Unloaded weight (T)", f"e_uw_{t['id']}", t["unloaded_weight"], 0.5, "%.3f", d_wt)
        unloading_date = c2.date_input("Unloading date", value=t["unloading_date"], format="DD/MM/YYYY",
                                       disabled=d_wt)
        c1, c2 = st.columns(2)
        with c1:
            p_short = num("Shortage cut by party ₹", f"e_ps_{t['id']}", t["party_shortage_amt"], 100.0,
                          disabled=d_party)
        with c2:
            t_short = num("Shortage cut from truck ₹", f"e_ts_{t['id']}", t["truck_shortage_amt"], 100.0,
                          disabled=d_truck)
        c1, c2 = st.columns(2)
        pod = c1.checkbox("POD received", value=t["pod_received"], disabled=d_truck)
        pod_date = c2.date_input("POD date", value=t["pod_date"], format="DD/MM/YYYY", disabled=d_truck)

        st.markdown("**More**")
        c1, c2 = st.columns(2)
        from_place = c1.selectbox("From", places, accept_new_options=True, disabled=d_party, placeholder="Optional",
                                  index=places.index(t["from_place"]) if t["from_place"] in places else None)
        material = c2.selectbox("Material", materials, accept_new_options=True, disabled=d_party,
                                placeholder="Optional",
                                index=materials.index(t["material"]) if t["material"] in materials else None)
        c1, c2 = st.columns(2)
        booking_date = c1.date_input("Trip date", value=t["booking_date"], format="DD/MM/YYYY", disabled=d_party)
        basis = c2.selectbox("Freight on", ["LOADED", "UNLOADED"], format_func=lambda x: f"{x.title()} wt",
                             index=0 if t["freight_basis"] == "LOADED" else 1, disabled=d_wt)
        c1, c2 = st.columns(2)
        ctype = c1.selectbox("Commission", ["FIXED", "PERCENT"], index=0 if t["commission_type"] == "FIXED" else 1,
                             format_func=lambda x: "Fixed ₹" if x == "FIXED" else "% of hire", disabled=d_truck)
        cval = c2.number_input("Commission value", min_value=0.0, step=10.0, disabled=d_truck,
                               value=float(t["commission_value"] or 0))

        if st.form_submit_button("💾 Save changes", type="primary", disabled=dis, use_container_width=True):
            errs = []
            if not d_truck:
                if truck_id and truck_rate <= 0:
                    errs.append("Enter truck rate.")
                if not truck_id and t["voucher_count"]:
                    errs.append("This trip has payment entries; truck cannot be removed.")
            if not d_wt:
                if weight > 0 and not (truck_id or t["truck_id"]):
                    errs.append("Select a truck before entering weight.")
                if unloaded > 0 and weight <= 0:
                    errs.append("Enter loaded weight before unloaded weight.")
            if not d_party and not (to_place or "").strip():
                errs.append("Destination is required.")
            if errs:
                ui.show_errors(errs)
            else:
                data = {"gr_no": gr_no, "gr_date": (gr_date or clock.today()) if gr_no.strip() else None,
                        "remarks": remarks.strip() or None}
                if not d_truck:
                    data.update(truck_id=truck_id, truck_rate=truck_rate or None, commission_type=ctype,
                                commission_value=cval, truck_shortage_amt=t_short, pod_received=pod,
                                pod_date=(pod_date or clock.today()) if pod else None)
                if not d_party:
                    data.update(party_id=party_id, to_place=to_place.strip(),
                                from_place=(from_place or "").strip() or None, party_rate=party_rate,
                                material=(material or "").strip() or None, booking_date=booking_date,
                                party_shortage_amt=p_short)
                if not d_wt:
                    data.update(loaded_weight=weight or None,
                                loading_date=(loading_date or booking_date) if weight > 0 else None,
                                unloaded_weight=unloaded or None, unloading_date=unloading_date,
                                freight_basis=basis)
                try:
                    trips.update_trip(t["id"], data)
                    st.session_state.pop(f"tr_{t['id']}_new_truck", None)
                    ui.flash("Trip updated")
                    st.rerun()
                except psycopg2.errors.UniqueViolation:
                    st.error(f"GR No. {calc.normalize_gr(gr_no)} is already used in another trip.")
                except ValueError as e:
                    st.error(str(e))

    st.markdown("**📎 GR copy**" + (f" — {int(t['gr_docs'])} uploaded" if t["gr_docs"] else ""))
    forms.upload_widget(t, f"e_grup_{t['id']}", "GR", "GR copy photo / PDF (camera or gallery)")

# ---------- Hisaab check ----------
with st.expander("🧮 Hisaab check (formula vs books)"):
    rows = checks.trip_check(t)
    all_ok = all(r["OK"] == "✅" for r in rows)
    (st.success if all_ok else st.error)(
        "Sab sahi hai — formula aur books match karte hain." if all_ok
        else "Mismatch mila. 'Hisaab Check' page par trip bill dobara banao, ya entries dekho.")
    ui.show_table(pd.DataFrame(rows), f"tchk_{t['id']}", money_cols=["Should be", "In books"])
    st.caption(f"Billing weight {t['billing_weight']} T ({t['freight_basis'].title()} basis) · "
               f"shortage weight {t['shortage_weight']} T · commission "
               f"{'₹' + str(t['commission_value']) if t['commission_type'] == 'FIXED' else str(t['commission_value']) + '% of hire'}")

# ---------- Entries ----------
with st.expander("📒 Entries of this trip"):
    vrows = db.query(trips.VOUCHER_LIST_SQL + " where v.trip_id=%s and v.v_type <> 'TRIP' order by v.v_date, v.id",
                     (t["id"],))
    if not vrows:
        st.caption("No entries yet.")
    for v in vrows:
        c1, c2 = st.columns([4, 1])
        strike = "~~" if v["is_cancelled"] else ""
        c1.markdown(f"{strike}{v['v_date']:%d/%m} · {v['v_type'].title()} {(v['purpose'] or '').title()} · "
                    f"**₹{ui.inr(v['amount'])}** · {v['credit_account'] if v['v_type'] != 'RECEIPT' else v['debit_account']}"
                    f"{strike}" + (f"  \n_cancelled: {v['cancel_reason']}_" if v["is_cancelled"] else ""))
        if not v["is_cancelled"]:
            with c2.popover("✖"):
                with st.form(f"vc_{v['id']}"):
                    reason = st.text_input("Why cancel? *")
                    if st.form_submit_button("Cancel entry"):
                        if not reason.strip():
                            st.error("Reason is required.")
                        else:
                            trips.cancel_voucher(v["id"], reason.strip())
                            ui.flash("Entry cancelled")
                            st.rerun()

# ---------- Documents ----------
with st.expander(f"📄 GR / POD copies ({int(t['all_docs'])})"):
    forms.documents_block(t, f"docs_{t['id']}")

# ---------- Cancel trip ----------
if not dis:
    with st.expander("❌ Cancel this trip"):
        ok, msg = calc.can_cancel_trip(t, int(t["voucher_count"]))
        if not ok:
            st.caption(msg)
        else:
            with st.form(f"cancel_{t['id']}"):
                reason = st.text_input("Reason *")
                if st.form_submit_button("Cancel trip"):
                    if not reason.strip():
                        st.error("Reason is required.")
                    else:
                        trips.cancel_trip(t["id"], reason.strip())
                        ui.flash("Trip cancelled")
                        st.rerun()
