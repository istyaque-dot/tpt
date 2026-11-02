"""New booking in the order the work actually happens:
Truck → Destination → Weight → Truck rate → Freight → Paying company → GR No. → Comment.
No st.form, so hire / freight / margin update live while typing."""

import psycopg2
import streamlit as st

from core import calc, clock, db, forms, nav, parse_msg, trips, ui

st.markdown("### ➕ New Trip")

# ---------- just-saved trip ----------
last = st.session_state.get("last_new_trip")
if last:
    t = trips.get_trip(last)
    if t:
        with st.container(border=True):
            st.success("Trip saved")
            st.markdown(ui.trip_summary_md(t))
            c1, c2 = st.columns(2)
            if c1.button("Open trip", use_container_width=True):
                st.session_state.pop("last_new_trip", None)
                nav.open_trip(t["id"])
            if c2.button("💸 Truck advance", use_container_width=True):
                forms.truck_payment_dialog(t["id"])
            if st.session_state.get("nt_msg_advance"):
                st.caption(f"Message mein advance ₹{ui.inr(st.session_state['nt_msg_advance'])} likha tha.")
            with st.expander("📎 Upload GR copy now"):
                forms.upload_widget(t, f"nt_gr_{t['id']}", "GR", "GR copy photo / PDF")

n = st.session_state.get("nt_n", 0)          # bump after save -> all fields clear
K = lambda name: f"nt_{name}_{n}"             # noqa: E731

trucks_ = db.query("select t.id, t.truck_no, t.driver_name, a.name owner_name from trucks t "
                   "join accounts a on a.id=t.owner_id where t.active order by t.truck_no")
tids = [t["id"] for t in trucks_]
tinfo = {t["id"]: t for t in trucks_}
parties = db.accounts("PARTY")
pids = [p["id"] for p in parties]
pnames = {p["id"]: p["name"] for p in parties}
places, materials = db.lookups("PLACE"), db.lookups("MATERIAL")

# ---------- paste a WhatsApp / SMS message -> fill the form ----------
pf = st.session_state.get("nt_prefill") or {}
with st.expander("📋 Paste message — app fills the form", expanded=not pf):
    msg = st.text_area("Booking message", key=f"nt_msg_{n}", height=110, label_visibility="collapsed",
                       placeholder="e.g. RJ14AB1234 Jaipur se Delhi 25 ton party rate 1200 gaadi bhada 1100 "
                                   "ABC Cement GR 4521 adv 10000")
    if st.button("✨ Fill from message", type="primary", use_container_width=True, disabled=not msg.strip()):
        st.session_state["nt_prefill"] = parse_msg.parse(msg, trucks_, parties, places, materials)
        st.session_state["nt_n"] = n + 1          # fresh form so the found values show up
        st.rerun()
if pf:
    found = [f"🚚 {pf['truck_no']}" if pf.get("truck_no") else "",
             f"📍 {pf.get('from_place', '')} → {pf['to_place']}" if pf.get("to_place") else "",
             f"⚖️ {pf['weight']} T" if pf.get("weight") else "",
             f"Truck ₹{pf['truck_rate']}" if pf.get("truck_rate") else "",
             f"Freight ₹{pf['party_rate']}" if pf.get("party_rate") else "",
             f"🏢 {pf['party_name']}" if pf.get("party_name") else "",
             f"GR {pf['gr_no']}" if pf.get("gr_no") else "",
             f"Adv ₹{pf['advance']}" if pf.get("advance") else ""]
    st.success("Message se bhara: " + " · ".join(x for x in found if x) + " — check karke Save karo.")
    for note in pf.get("notes", []):
        st.warning(note)
    if st.button("✖ Clear filled values", use_container_width=True):
        st.session_state.pop("nt_prefill", None)
        st.session_state["nt_n"] = n + 1
        st.rerun()
for k in ("to_place", "from_place"):
    if pf.get(k) and pf[k] not in places:
        places.append(pf[k])
if pf.get("material") and pf["material"] not in materials:
    materials.append(pf["material"])


def _idx(options, value):
    return options.index(value) if value in options else None


# 1. Truck
c1, c2 = st.columns([3, 1])
new_t = st.session_state.get("nt_new_truck") or pf.get("truck_id")
truck_id = c1.selectbox("1. Truck No. *", tids, format_func=lambda i: tinfo[i]["truck_no"], key=K("truck"),
                        index=tids.index(new_t) if new_t in tids else None, placeholder="Type last digits")
with c2:
    st.write("")
    forms.quick_add_truck("nt")
if truck_id:
    st.caption(f"Owner: {tinfo[truck_id]['owner_name']}"
               + (f" · Driver: {tinfo[truck_id]['driver_name']}" if tinfo[truck_id]["driver_name"] else ""))

# 2. Destination
to_place = st.selectbox("2. Destination *", places, index=_idx(places, pf.get("to_place")),
                        accept_new_options=True, key=K("to"), placeholder="Select or type new")

# 3-5. Weight and rates (live calculation)
weight = ui.amount("3. Weight (ton)", K("wt"), value=float(pf["weight"]) if pf.get("weight") else None,
                   step=0.5, format="%.3f", help="Leave blank if not loaded yet")
c1, c2 = st.columns(2)
with c1:
    truck_rate = ui.amount("4. Truck rate ₹/ton *", K("trate"), step=10.0,
                           value=float(pf["truck_rate"]) if pf.get("truck_rate") else None)
with c2:
    party_rate = ui.amount("5. Freight ₹/ton *", K("prate"), step=10.0,
                           value=float(pf["party_rate"]) if pf.get("party_rate") else None)
if weight > 0 and (truck_rate > 0 or party_rate > 0):
    hire = calc.r2(weight * truck_rate)
    freight = calc.r2(weight * party_rate)
    with st.container(border=True):
        ui.metric_grid([("Truck hire", ui.inr(hire)), ("Party freight", ui.inr(freight))])
        st.caption(f"Margin ₹ {ui.inr(freight - hire)}  (before commission)")

# 6. Freight paying company
c1, c2 = st.columns([3, 1])
new_p = st.session_state.get("nt_new_party") or pf.get("party_id")
party_id = c1.selectbox("6. Freight paid by (company) *", pids, format_func=pnames.get, key=K("party"),
                        index=pids.index(new_p) if new_p in pids else None, placeholder="Type to search")
with c2:
    st.write("")
    forms.quick_add_party("nt")

# 7-8. GR + comment
gr_no = st.text_input("7. GR No. (if available)", key=K("gr"), placeholder="Can add later",
                      value=pf.get("gr_no") or "")
_note = " · ".join(x for x in (f"Adv {pf['advance']}" if pf.get("advance") else "",
                               f"Driver {pf['mobile']}" if pf.get("mobile") else "") if x)
remarks = st.text_area("8. Comment / note to remember", key=K("note"), height=80, value=_note,
                       placeholder="e.g. driver will call at unloading, party wants POD original")

with st.expander("More: From, material, date, commission"):
    c1, c2 = st.columns(2)
    last_from = pf.get("from_place") or st.session_state.get("_last_from")
    from_place = c1.selectbox("From", places, accept_new_options=True, key=K("from"), placeholder="Optional",
                              index=places.index(last_from) if last_from in places else None)
    material = c2.selectbox("Material", materials, index=_idx(materials, pf.get("material")),
                            accept_new_options=True, key=K("mat"),
                            placeholder="Optional")
    c1, c2 = st.columns(2)
    trip_date = c1.date_input("Trip date", value=clock.today(), format="DD/MM/YYYY", key=K("date"))
    ctype = c2.selectbox("Commission", ["FIXED", "PERCENT"], key=K("ctype"),
                         index=0 if db.setting("default_commission_type") == "FIXED" else 1,
                         format_func=lambda x: "Fixed ₹" if x == "FIXED" else "% of hire")
    cval = st.number_input("Commission value", min_value=0.0, step=10.0, key=K("cval"),
                           value=float(db.setting("default_commission_value", "0") or 0))

if st.button("💾 Save trip", type="primary", use_container_width=True):
    errs = []
    if not truck_id:
        errs.append("Select truck.")
    if not (to_place or "").strip():
        errs.append("Enter destination.")
    if truck_rate <= 0:
        errs.append("Enter truck rate.")
    if party_rate <= 0:
        errs.append("Enter freight rate.")
    if not party_id:
        errs.append("Select the company paying freight.")
    if errs:
        ui.show_errors(errs)
    else:
        loaded = weight > 0
        try:
            tid = trips.create_trip(dict(
                booking_date=trip_date, party_id=party_id, from_place=(from_place or "").strip() or None,
                to_place=to_place.strip(), material=(material or "").strip() or None,
                party_rate=party_rate, truck_id=truck_id, truck_rate=truck_rate,
                loaded_weight=weight if loaded else None, loading_date=trip_date if loaded else None,
                gr_no=gr_no, gr_date=trip_date if gr_no.strip() else None,
                freight_basis=db.setting("freight_basis", "LOADED"),
                commission_type=ctype, commission_value=cval, remarks=remarks.strip() or None))
        except psycopg2.errors.UniqueViolation:
            st.error(f"GR No. {calc.normalize_gr(gr_no)} is already used in another trip.")
            st.stop()
        if from_place:
            st.session_state["_last_from"] = from_place.strip()
        for k in ("nt_new_party", "nt_new_truck"):
            st.session_state.pop(k, None)
        st.session_state["last_new_trip"] = tid
        st.session_state["nt_msg_advance"] = pf.get("advance")
        st.session_state.pop("nt_prefill", None)
        st.session_state["nt_n"] = n + 1
        ui.flash(f"Trip saved: {trips.get_trip(tid)['trip_no']}")
        st.rerun()
