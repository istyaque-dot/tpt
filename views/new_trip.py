"""New booking in the order the work actually happens:
Truck → Destination → Weight → Truck rate → Freight → Paying company → GR No. → Comment.
No st.form, so hire / freight / margin update live while typing."""

import psycopg2
import streamlit as st

from core import ai, calc, clock, db, forms, nav, smart, trips, ui

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
with st.expander("📋 Paste message / 📷 GR photo — app fills the form" + (" 🤖" if ai.configured() else ""),
                 expanded=not pf):
    msg = st.text_area("Booking message", key=f"nt_msg_{n}", height=110, label_visibility="collapsed",
                       placeholder="e.g. UP70FT7739 Kashipur to Sultanpur 2point mt 35 Rate 175 Driver no 9005899224")
    if st.button("✨ Fill from message", type="primary", use_container_width=True, disabled=not msg.strip()):
        from core import parse_msg
        n_trucks = len({parse_msg._plate_key(*m.groups()) for m in parse_msg.PLATE.finditer(msg)})
        with st.spinner("Padh raha hoon..."):
            if n_trucks >= 2:            # one message, many trucks -> one screen to save them all
                st.session_state["nt_multi"] = ai.parse_many_safe(msg, trucks_, parties, places, materials,
                                                                  default_unit=db.rate_unit(),
                                                                  single_rate_for=db.message_rate_for())
            else:
                st.session_state["nt_prefill"] = ai.parse_message_safe(msg, trucks_, parties, places, materials,
                                                                       default_unit=db.rate_unit(),
                                                                       single_rate_for=db.message_rate_for())
        st.session_state["nt_n"] = n + 1          # fresh form so the found values show up
        st.rerun()
    if ai.configured():
        gr_photo = st.file_uploader("…ya GR / bilty ki photo (AI padhega)", type=["jpg", "jpeg", "png", "webp", "pdf"],
                                    key=f"nt_grphoto_{n}")
        if gr_photo and st.button("🤖 Fill from GR photo", use_container_width=True):
            try:
                with st.spinner("AI photo padh raha hai..."):
                    d = ai.read_document(gr_photo.getvalue(), gr_photo.type)
                filled = {"notes": [], "source": "AI photo"}
                if d.get("truck_no"):
                    filled["truck_no"] = d["truck_no"]
                    hit = trips.find_truck(d["truck_no"], trucks_)
                    if hit:
                        filled["truck_id"] = hit["id"]
                for k_src, k_dst in (("from_place", "from_place"), ("to_place", "to_place"), ("material", "material"),
                                     ("gr_no", "gr_no")):
                    if d.get(k_src):
                        filled[k_dst] = d[k_src]
                if d.get("weight_ton"):
                    filled["weight"] = d["weight_ton"]
                p = ai._match_name(d.get("consignor") or "", parties) or ai._match_name(d.get("consignee") or "",
                                                                                       parties)
                if p:
                    filled["party_id"], filled["party_name"] = p["id"], p["name"]
                filled["notes"].append("Photo se bhara — rates khud likho, aur sab check karo.")
                st.session_state["nt_prefill"] = filled
                st.session_state["nt_gr_file"] = (gr_photo.name, gr_photo.getvalue(), gr_photo.type)
                st.session_state["nt_n"] = n + 1
                st.rerun()
            except ai.AIError as e:
                st.error(str(e))
if st.session_state.get("nt_multi"):
    from core import multi_ui
    multi_ui.render(st.session_state["nt_multi"], trucks_, parties, n)
    st.stop()
if pf:
    found = [f"🚚 {pf['truck_no']}" if pf.get("truck_no") else "",
             f"📍 {pf.get('from_place', '')} → {pf['to_place']}" if pf.get("to_place") else "",
             f"⚖️ {pf['weight']} T" if pf.get("weight") else "",
             f"Truck ₹{calc.rate_show(pf['truck_rate'], db.rate_unit()).normalize():f}"
             f"{calc.rate_label(db.rate_unit())[1:]}" if pf.get("truck_rate") else "",
             f"Freight ₹{calc.rate_show(pf['party_rate'], db.rate_unit()).normalize():f}"
             f"{calc.rate_label(db.rate_unit())[1:]}" if pf.get("party_rate") else "",
             f"🏢 {pf['party_name']}" if pf.get("party_name") else "",
             f"GR {pf['gr_no']}" if pf.get("gr_no") else "",
             f"Adv ₹{pf['advance']}" if pf.get("advance") else ""]
    src = {"AI": "🤖 AI ne", "AI photo": "🤖 AI ne photo se"}.get(pf.get("source"), "Message se")
    st.success(f"{src} bhara: " + " · ".join(x for x in found if x) + " — check karke Save karo.")
    for note in pf.get("notes", []):
        st.warning(note)
    if st.button("✖ Clear filled values", use_container_width=True):
        st.session_state.pop("nt_prefill", None)
        st.session_state["nt_n"] = n + 1
        st.rerun()
RU = db.rate_unit()                       # rates typed in ₹/qtl (or ₹/ton), stored per ton
SS = st.session_state


def _init(key: str, value):
    if key not in SS:
        SS[key] = value


def _rate_box(v):
    return float(calc.rate_show(v, RU)) if v else None


# ---- 1) message / photo values go into the form once ----
if pf and SS.get("nt_pf_done") != n:
    _init(K("truck"), pf.get("truck_no") or "")
    _init(K("to"), pf.get("to_place") or "")
    _init(K("wt"), float(pf["weight"]) if pf.get("weight") else None)
    _init(K("trate"), _rate_box(pf.get("truck_rate")))
    _init(K("prate"), _rate_box(pf.get("party_rate")))
    if pf.get("party_id") in pids:
        _init(K("party"), pf["party_id"])
    _init(K("gr"), pf.get("gr_no") or "")
    _init(K("note"), " · ".join(x for x in (f"{pf['points']} point" if pf.get("points") else "",
                                             f"Adv {pf['advance']}" if pf.get("advance") else "",
                                             f"Driver {pf['mobile']}" if pf.get("mobile") else "") if x))
    _init(K("from"), pf.get("from_place") or "")
    _init(K("mat"), pf.get("material") or "")
    SS["nt_pf_done"] = n
if SS.get("nt_new_party") in pids and not SS.get(K("party")):
    SS[K("party")] = SS["nt_new_party"]

# ---- 2) 🔁 copy the last trip: party, route, commission (NOT rates — they change every time) ----
history = db.query("select party_id, to_place, from_place, material, party_rate, truck_rate, commission_value, "
                   "owner_id, booking_date, tds_rate from trips where not is_cancelled order by id desc limit 500")
if history and st.button("🔁 Pichhli trip jaisa (party, route, commission copy — rate & truck khud likho)",
                         use_container_width=True):
    h = history[0]
    SS[K("to")] = h["to_place"] or ""
    SS[K("from")] = h["from_place"] or ""
    SS[K("mat")] = h["material"] or ""
    SS[K("cval")] = float(h["commission_value"] or 0) or None
    if h["party_id"] in pids:
        SS[K("party")] = h["party_id"]
    SS[K("tds")] = float(h["tds_rate"] or 0)

# ---- 3) fill empty boxes from past trips (each box at most once per form) ----
# Party / commission / from / material fill themselves. Freight & truck rate change often, so they are
# only OFFERED as a tap-to-use button next to the box — never filled silently.
auto_done = SS.setdefault(f"nt_auto_{n}", set())
cur_truck = trips.find_truck(SS.get(K("truck"), ""), trucks_) if SS.get(K("truck"), "").strip() else None
owner_of = {t["id"]: t for t in db.query("select id, owner_id from trucks")}
sug = smart.suggest(history, SS.get(K("to"), ""), SS.get(K("party")),
                    (owner_of.get(cur_truck["id"]) or {}).get("owner_id") if cur_truck else None)
hints = []
for field, key in (("party_id", K("party")), ("commission", K("cval")),
                   ("from_place", K("from")), ("material", K("mat"))):
    if field in sug and key not in auto_done and not SS.get(key):
        v = sug[field][0]
        if field == "party_id" and v not in pids:
            continue
        SS[key] = float(v) if field == "commission" else v
        auto_done.add(key)
        if field == "party_id":
            label = f"Party {pnames.get(v, '')}"
        elif field == "commission":
            label = f"Commission ₹{ui.inr(v)}"
        elif field == "from_place":
            label = f"From {v}"
        else:
            label = f"Maal {v}"
        hints.append(f"{label} ({sug[field][1]})")
if hints:
    st.info("💡 Pichhli trips se bhara: " + " · ".join(hints) + " — badalna ho to badal do.")


def _last_rate_button(field: str, key: str, label: str):
    """'Pichhli baar ₹185/qtl' — tap to copy; nothing is filled without the tap."""
    if field in sug and not SS.get(key):
        v = _rate_box(sug[field][0])
        # on_click runs before the next run, so the number box can take the value safely
        st.button(f"↩ {label} pichhli baar ₹{v:g}", key=f"{key}_last", help=sug[field][1],
                  on_click=SS.__setitem__, args=(key, v))


# 1. Truck — typed. Old truck: found by full number or last digits. New truck: created on Save.
_init(K("truck"), "")
truck_txt = st.text_input("1. Truck No. *", key=K("truck"),
                          placeholder="e.g. RJ14AB1234 (or last 4 digits of an old truck)")
truck_hit = trips.find_truck(truck_txt, trucks_) if truck_txt.strip() else None
truck_id, new_truck, new_owner = None, None, None
if truck_hit:
    truck_id = truck_hit["id"]
    st.caption(f"✅ {truck_hit['truck_no']} · Owner: {truck_hit['owner_name']}"
               + (f" · Driver: {truck_hit['driver_name']}" if truck_hit.get("driver_name") else ""))
elif truck_txt.strip():
    if trips.looks_like_truck_no(truck_txt):
        new_truck = calc.normalize_truck_no(truck_txt)
        new_owner = st.text_input(f"🆕 Naya truck {new_truck} — owner ka naam (optional)", key=K("owner"),
                                  placeholder="Khaali chhodo to truck no. hi owner ka naam ban jaayega")
    else:
        st.warning("Poora truck no. likho (jaise RJ14AB1234). Last digits se koi ek purana truck nahi mila.")

# 2. Destination — typed
to_place = st.text_input("2. Destination *", key=K("to"), placeholder="e.g. Delhi")

# 3-5. Weight and rates (live calculation)
weight = ui.amount("3. Weight (ton)", K("wt"), step=0.5, format="%.3f", help="Leave blank if not loaded yet")
step = 1.0 if RU == "QUINTAL" else 10.0
c1, c2 = st.columns(2)
with c1:
    truck_rate = calc.rate_store(ui.amount(f"4. Truck rate {calc.rate_label(RU)} *", K("trate"), step=step), RU)
    _last_rate_button("truck_rate", K("trate"), "Truck")
with c2:
    party_rate = calc.rate_store(ui.amount(f"5. Freight {calc.rate_label(RU)} *", K("prate"), step=step), RU)
    _last_rate_button("party_rate", K("prate"), "Freight")
if RU == "QUINTAL" and (truck_rate or party_rate):
    st.caption(f"= Truck ₹{ui.inr(truck_rate)}/ton · Freight ₹{ui.inr(party_rate)}/ton")
c1, c2 = st.columns(2)
with c1:
    cval = ui.amount("Commission ₹", K("cval"), step=50.0, help="Truck bhade se katne wala commission (fixed ₹)")
with c2:
    _init(K("tds"), float(db.setting("default_tds_rate", "1") or 0))
    tds_rate = calc.D(st.number_input("Party TDS %", min_value=0.0, max_value=10.0, step=0.5, key=K("tds"),
                                      help="Party freight se itna % TDS kaat kar degi"))
if weight > 0 and (truck_rate > 0 or party_rate > 0):
    hire = calc.r2(weight * truck_rate)
    freight = calc.r2(weight * party_rate)
    tds_amt = calc.trip_amounts({"truck_id": 1, "loaded_weight": weight, "party_rate": party_rate,
                                 "tds_rate": tds_rate})["party_tds"]
    with st.container(border=True):
        ui.metric_grid([("Truck hire", ui.inr(hire)), ("Party freight", ui.inr(freight)),
                        ("Truck ko milega", ui.inr(hire - cval)), ("Party se aayega", ui.inr(freight - tds_amt))])
        st.caption(f"Commission ₹{ui.inr(cval)} · TDS {tds_rate}% = ₹{ui.inr(tds_amt)} · "
                   f"Profit ₹{ui.inr(freight - hire + cval)}")

# 6. Freight paying company
c1, c2 = st.columns([3, 1])
party_id = c1.selectbox("6. Freight paid by (company) *", pids, format_func=pnames.get, key=K("party"),
                        index=None, placeholder="Type to search")
with c2:
    st.write("")
    forms.quick_add_party("nt")

# 7-8. GR + comment
gr_no = st.text_input("7. GR No. (if available)", key=K("gr"), placeholder="Can add later")
remarks = st.text_area("8. Comment / note to remember", key=K("note"), height=80,
                       placeholder="e.g. driver will call at unloading, party wants POD original")

with st.expander("More: From, material, date"):
    c1, c2 = st.columns(2)
    _init(K("from"), st.session_state.get("_last_from") or "")
    from_place = c1.text_input("From", key=K("from"), placeholder="Optional")
    material = c2.text_input("Material", key=K("mat"), placeholder="Optional")
    trip_date = st.date_input("Trip date", value=clock.today(), format="DD/MM/YYYY", key=K("date"))

if st.button("💾 Save trip", type="primary", use_container_width=True):
    errs = []
    if not truck_id and not new_truck:
        errs.append("Truck No. likho.")
    if not (to_place or "").strip():
        errs.append("Destination likho.")
    if truck_rate <= 0:
        errs.append("Truck rate likho.")
    if party_rate <= 0:
        errs.append("Freight rate likho.")
    if not party_id:
        errs.append("Freight dene wali company chuno.")
    if errs:
        ui.show_errors(errs)
    else:
        loaded = weight > 0
        try:
            tid = trips.create_trip(dict(
                booking_date=trip_date, party_id=party_id, from_place=(from_place or "").strip() or None,
                to_place=to_place.strip().title() if to_place.strip().islower() else to_place.strip(),
                material=(material or "").strip() or None,
                party_rate=party_rate, truck_id=truck_id, truck_rate=truck_rate,
                loaded_weight=weight if loaded else None, loading_date=trip_date if loaded else None,
                gr_no=gr_no, gr_date=trip_date if gr_no.strip() else None,
                freight_basis=db.setting("freight_basis", "LOADED"),
                commission_type="FIXED", commission_value=cval, tds_rate=tds_rate,
                remarks=remarks.strip() or None), new_truck_no=new_truck, new_owner=new_owner)
        except psycopg2.errors.UniqueViolation:
            st.error(f"GR No. {calc.normalize_gr(gr_no)} is already used in another trip.")
            st.stop()
        if from_place.strip():
            st.session_state["_last_from"] = from_place.strip()
        st.session_state.pop("nt_new_party", None)
        st.session_state["last_new_trip"] = tid
        grf = st.session_state.pop("nt_gr_file", None)
        if grf:
            from core import drive
            if drive.configured():
                try:
                    drive.upload(trips.get_trip(tid), "GR", grf[0], grf[1], grf[2], st.session_state.get("user", "admin"))
                except Exception as e:  # trip is saved; only the copy failed
                    st.session_state["nt_gr_err"] = f" · GR copy upload nahi hui: {e}"
        st.session_state["nt_msg_advance"] = pf.get("advance")
        st.session_state.pop("nt_prefill", None)
        st.session_state["nt_n"] = n + 1
        ui.flash(f"Trip saved: {trips.get_trip(tid)['trip_no']}" + st.session_state.pop("nt_gr_err", ""))
        st.rerun()
