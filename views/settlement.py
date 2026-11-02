"""Truck Settlement: find trip → POD → shortage/damage cut, demurrage → see final hisaab → pay balance."""

import streamlit as st

from core import calc, clock, db, forms, nav, trips, ui

st.markdown("### 🧾 Truck Settlement")

sid = st.session_state.get("settle_trip_id")
t = trips.get_trip(sid) if sid else None

# ====================== find the trip ======================
if not t:
    q = st.text_input("🔎 Truck no. / GR / Trip", key="st_q", placeholder="Last digits of truck, GR No. or Trip No.",
                      label_visibility="collapsed")
    rows = trips.find_trips(q, "Truck to pay", 200)
    rows.sort(key=lambda r: (not r["pod_received"], r.get("loading_date") or clock.today()))
    st.caption(f"{len(rows)} trip(s) with truck balance pending — POD received ones first")
    for r in rows[:40]:
        with st.container(border=True):
            st.markdown(ui.trip_summary_md(r))
            if st.button("Settle →", key=f"st_go_{r['id']}", type="primary" if r["pod_received"] else "secondary",
                         use_container_width=True):
                st.session_state["settle_trip_id"] = r["id"]
                st.rerun()
    st.stop()

# ====================== one trip ======================
c1, c2 = st.columns([1, 3])
if c1.button("← Back", use_container_width=True):
    st.session_state.pop("settle_trip_id", None)
    st.rerun()
c2.markdown(f"**{t['trip_no']} · {t.get('truck_no') or ''}**  \n{t['owner_name'] or ''}")

with st.container(border=True):
    st.markdown(ui.trip_summary_md(t))

if not t.get("truck_id") or not calc.is_loaded(t):
    st.warning("Truck and loaded weight are needed first.")
    if st.button("✏️ Edit trip", use_container_width=True):
        nav.open_trip(t["id"])
    st.stop()

locked = t["locks"]["truck"]
if locked:
    st.success("✅ This truck is already settled. To change anything, cancel the balance payment first "
               "(trip → Entries).")

# ---------- 1. POD ----------
st.markdown("#### 1. POD")
if t["pod_received"]:
    st.success(f"✅ POD received{(' on ' + t['pod_date'].strftime('%d/%m/%Y')) if t.get('pod_date') else ''}"
               f" · {int(t['pod_docs'])} copy uploaded")
    with st.expander("Upload more POD pages"):
        forms.upload_widget(t, f"st_pod_more_{t['id']}", "POD")
else:
    st.warning("Balance can be paid only after POD.")
    forms.upload_widget(t, f"st_pod_{t['id']}", "POD", "POD photo / PDF (camera or gallery)")
    if st.button("POD original received (no copy now)", use_container_width=True, key=f"st_podtick_{t['id']}"):
        trips.update_trip(t["id"], {"pod_received": True, "pod_date": clock.today()})
        ui.flash("POD marked received")
        st.rerun()

# ---------- 2. adjustments (live) ----------
st.markdown("#### 2. Kat-kaat / Demurrage")


def num(label, field, step=100.0, fmt=None, disabled=False, help=None):
    v = t.get(field)
    kw = {"format": fmt} if fmt else {}
    out = st.number_input(label, min_value=0.0, step=step, key=f"st_{field}_{t['id']}", disabled=disabled,
                          value=float(v) if v not in (None, 0) else None, placeholder="0", help=help, **kw)
    return calc.D(out)


c1, c2 = st.columns(2)
with c1:
    unloaded = num("Unloaded weight (T)", "unloaded_weight", 0.5, "%.3f", locked or t["locks"]["weights"])
with c2:
    st.metric("Shortage weight", f"{max(calc.D(t['loaded_weight']) - unloaded, calc.ZERO) if unloaded else 0} T")
c1, c2 = st.columns(2)
with c1:
    t_short = num("Shortage / damage cut from truck ₹", "truck_shortage_amt", disabled=locked)
with c2:
    t_dem = num("Demurrage to truck ₹", "truck_demurrage_amt", disabled=locked,
                help="Extra paid to truck for waiting (detention)")
c1, c2 = st.columns(2)
with c1:
    days = st.number_input("Demurrage days", min_value=0, step=1, key=f"st_days_{t['id']}", disabled=locked,
                           value=int(t["demurrage_days"]) if t.get("demurrage_days") else None, placeholder="0")
with c2:
    p_dem = num("Demurrage charged to party ₹", "party_demurrage_amt", disabled=locked or t["locks"]["party"],
                help="Leave blank if party does not pay demurrage")
p_short = num("Shortage cut by party ₹", "party_shortage_amt", disabled=locked or t["locks"]["party"])

changes = {}
if not locked and not t["locks"]["weights"] and unloaded != calc.D(t["unloaded_weight"]):
    changes["unloaded_weight"] = unloaded or None
    if unloaded and not t.get("unloading_date"):
        changes["unloading_date"] = clock.today()
if not locked:
    for f, v in (("truck_shortage_amt", t_short), ("truck_demurrage_amt", t_dem)):
        if v != calc.D(t.get(f)):
            changes[f] = v
    if (days or None) != t.get("demurrage_days"):
        changes["demurrage_days"] = days or None
    if not t["locks"]["party"]:
        for f, v in (("party_demurrage_amt", p_dem), ("party_shortage_amt", p_short)):
            if v != calc.D(t.get(f)):
                changes[f] = v

preview = dict(t, **changes)
a = calc.trip_amounts(preview)

# ---------- 3. final hisaab ----------
st.markdown("#### 3. Final hisaab")
lines = [("Truck hire", f"{a['billing_weight']} T × ₹{t['truck_rate']}", a["truck_hire"], "+"),
         ("Demurrage", f"{days} day(s)" if days else "", a["truck_demurrage"], "+"),
         ("Advance paid", "", a["truck_paid"], "−"),
         ("Diesel", "", a["diesel"], "−"),
         ("Commission", f"{t['commission_value']}%" if t["commission_type"] == "PERCENT" else "", a["commission"], "−"),
         ("Shortage / damage", "", a["truck_shortage"], "−")]
with st.container(border=True):
    for name, note, amt, sign in lines:
        if amt or name in ("Truck hire", "Advance paid"):
            c1, c2 = st.columns([3, 2])
            c1.markdown(f"{name}" + (f"  \n<small>{note}</small>" if note else ""), unsafe_allow_html=True)
            c2.markdown(f"<div style='text-align:right'>{sign} ₹{ui.inr(amt)}</div>", unsafe_allow_html=True)
    st.divider()
    c1, c2 = st.columns([3, 2])
    c1.markdown("**Balance payable**")
    c2.markdown(f"<div style='text-align:right;font-size:1.3rem'><b>₹{ui.inr(a['truck_balance'])}</b></div>",
                unsafe_allow_html=True)
    if changes:
        st.caption("✏️ Changes above are not saved yet.")
if a["truck_balance"] < -calc.SETTLED_TOLERANCE:
    st.warning("Negative: the truck owner has been paid extra and must return this amount.")

if changes and st.button("💾 Save kat-kaat / demurrage", use_container_width=True):
    trips.update_trip(t["id"], changes)
    ui.flash("Saved")
    st.rerun()

# ---------- 4. pay balance ----------
if not locked:
    st.markdown("#### 4. Balance payment")
    bal = a["truck_balance"]
    accs = db.money_accounts()
    aids = [x["id"] for x in accs]
    an = {x["id"]: x["name"] for x in accs}
    with st.form(f"st_pay_{t['id']}"):
        amount = st.number_input("Amount ₹", min_value=0.0, step=100.0,
                                 value=float(bal) if bal > 0 else None, placeholder="0")
        c1, c2 = st.columns(2)
        acc = c1.selectbox("From", aids, format_func=an.get, index=ui.remembered("money", aids))
        v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        ref = st.text_input("UTR / Ref (optional)")
        allow_over = st.checkbox("Allow more than balance")
        go = st.form_submit_button("💸 Save" + (" changes &" if changes else "") + " pay balance", type="primary",
                                   use_container_width=True)
    if go:
        amt = calc.D(amount)
        errs = calc.check_truck_payment(preview, a, "BALANCE", amt, db.setting_bool("require_gr_for_truck_balance"),
                                        allow_over)
        if not acc:
            errs.append("Select cash/bank.")
        if errs:
            ui.show_errors(errs)
        else:
            if changes:
                trips.update_trip(t["id"], changes)
            with db.tx() as cur:
                trips.add_voucher(cur, v_date=v_date, v_type="PAYMENT", purpose="BALANCE", trip_id=t["id"],
                                  amount=amt, dr_account=t["owner_id"], cr_account=acc, ref_no=ref,
                                  narration=f"Truck balance {t['truck_no']} {t['trip_no']}")
            ui.remember("money", acc)
            ui.flash(f"Balance ₹{ui.inr(amt)} paid to {t['owner_name']} ({t['truck_no']})")
            st.rerun()

# ---------- 5. share ----------
with st.expander("📤 Settlement text (copy to WhatsApp)"):
    txt = [f"Truck {t['truck_no']} · {t['trip_no']}" + (f" · GR {t['gr_no']}" if t.get("gr_no") else ""),
           f"{calc.route(t)} · {a['billing_weight']} T"]
    for name, note, amt, sign in lines:
        if amt or name in ("Truck hire", "Advance paid"):
            txt.append(f"{name}: {sign} {ui.inr(amt)}" + (f" ({note})" if note else ""))
    txt.append(f"Balance: {ui.inr(a['truck_balance'])}")
    st.code("\n".join(txt), language=None)

if st.button("✏️ Open full trip", use_container_width=True):
    nav.open_trip(t["id"])
