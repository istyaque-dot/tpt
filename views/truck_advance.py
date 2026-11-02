"""Truck Advance: pick a truck → see owner/driver, its running trips, what was already given → give advance."""

import pandas as pd
import streamlit as st

from core import calc, clock, db, nav, trips, ui

st.markdown("### 💸 Truck Advance")

trucks_ = db.query("select t.id, t.truck_no, t.driver_name, t.driver_mobile, t.owner_id, "
                   "a.name owner_name, a.mobile owner_mobile, a.bank_details "
                   "from trucks t join accounts a on a.id = t.owner_id order by t.truck_no")
tinfo = {t["id"]: t for t in trucks_}
pre = st.session_state.get("adv_truck_id")
ids = list(tinfo)
truck_id = st.selectbox("Truck No.", ids, format_func=lambda i: tinfo[i]["truck_no"], placeholder="Type last digits",
                        index=ids.index(pre) if pre in ids else None, key="adv_truck")
if not truck_id:
    st.stop()
st.session_state["adv_truck_id"] = truck_id
tk = tinfo[truck_id]

# ---------- truck details ----------
with st.container(border=True):
    st.markdown(f"**{tk['truck_no']}**  \n"
                f"Owner: **{tk['owner_name']}**" + (f" · 📞 {tk['owner_mobile']}" if tk["owner_mobile"] else "")
                + (f"  \nDriver: {tk['driver_name'] or '—'}" + (f" · 📞 {tk['driver_mobile']}" if tk["driver_mobile"] else ""))
                + (f"  \nBank: {tk['bank_details']}" if tk["bank_details"] else ""))

# trips of this truck that are not settled yet
open_trips = [t for t in trips.load_trips("not t.is_cancelled and t.truck_id = %s", (truck_id,), "t.id desc")
              if not calc.truck_settled(t, t)]
hire = sum((t["truck_hire"] for t in open_trips), calc.ZERO)
given = sum((t["truck_paid"] + t["diesel"] for t in open_trips), calc.ZERO)
bal = sum((t["truck_balance"] for t in open_trips), calc.ZERO)
ui.metric_grid([("Running trips", len(open_trips)), ("Hire", ui.inr(hire)),
                ("Already given (cash+diesel)", ui.inr(given)), ("Balance", ui.inr(bal))])

if not open_trips:
    st.info("No running trip for this truck. Create a trip first.")
    if st.button("➕ New Trip", type="primary", use_container_width=True):
        nav.go("new_trip")
    st.stop()

# ---------- give advance ----------
st.markdown("#### Give advance / payment")
labels = {t["id"]: f"{t['trip_no']} · {calc.route(t)} · bal ₹{ui.inr(t['truck_balance'])}"
          + (" · POD ✓" if t["pod_received"] else "") for t in open_trips}
tids = list(labels)
with st.form("adv_form", clear_on_submit=True):
    trip_id = st.selectbox("Trip", tids, format_func=labels.get, index=0)
    amount = ui.amount("Amount ₹", "adv_amt")
    c1, c2 = st.columns(2)
    accs = db.money_accounts()
    aids = [a["id"] for a in accs]
    anames = {a["id"]: a["name"] for a in accs}
    acc = c1.selectbox("Cash / Bank", aids, format_func=anames.get, index=ui.remembered("money", aids))
    v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
    purpose = st.radio("Type", ["ADVANCE", "BALANCE"], horizontal=True, format_func=str.title)
    c1, c2 = st.columns(2)
    ref = c1.text_input("Ref / UTR (optional)")
    note = c2.text_input("Note (optional)", placeholder="e.g. given to driver")
    allow_over = st.checkbox("Allow more than balance")
    if st.form_submit_button("💾 Save", type="primary", use_container_width=True):
        t = next(x for x in open_trips if x["id"] == trip_id)
        errs = calc.check_truck_payment(t, t, purpose, amount, db.setting_bool("require_gr_for_truck_balance"),
                                        allow_over)
        if not acc:
            errs.append("Select cash/bank.")
        if errs:
            ui.show_errors(errs)
        else:
            with db.tx() as cur:
                trips.add_voucher(cur, v_date=v_date, v_type="PAYMENT", purpose=purpose, trip_id=trip_id,
                                  amount=amount, dr_account=tk["owner_id"], cr_account=acc, ref_no=ref,
                                  narration=note.strip() or f"Truck {purpose.lower()} {tk['truck_no']} {t['trip_no']}")
            ui.remember("money", acc)
            ui.flash(f"₹{ui.inr(amount)} {purpose.lower()} saved for {tk['truck_no']}")
            st.rerun()

# ---------- running trips ----------
st.markdown("#### Running trips")
for t in open_trips:
    with st.container(border=True):
        st.markdown(f"**{t['trip_no']}** · {calc.route(t)} · {t['billing_weight']} T · "
                    f"{ui.STATUS_ICON.get(t['status'], '')} {t['status']}  \n"
                    f"Hire ₹{ui.inr(t['truck_hire'])}"
                    + (f" + demurrage ₹{ui.inr(t['truck_demurrage'])}" if t["truck_demurrage"] else "")
                    + f" − paid ₹{ui.inr(t['truck_paid'])} − diesel ₹{ui.inr(t['diesel'])}"
                    f" − comm ₹{ui.inr(t['commission'])} − short ₹{ui.inr(t['truck_shortage'])} = "
                    f"**₹{ui.inr(t['truck_balance'])}**")
        if st.button("Open trip", key=f"adv_open_{t['id']}", use_container_width=True):
            nav.open_trip(t["id"])

# ---------- history ----------
st.markdown("#### Advances & diesel given (last 50)")
hist = db.query(trips.VOUCHER_LIST_SQL + " join trucks tk on tk.id = t.truck_id "
                "where tk.id = %s and v.v_type in ('PAYMENT','DIESEL') order by v.v_date desc, v.id desc limit 50",
                (truck_id,))
df = pd.DataFrame([{"Date": h["v_date"], "Trip": h["trip_no"], "Type": f"{h['v_type'].title()} {(h['purpose'] or '').title()}",
                    "Amount": float(h["amount"]), "From": h["credit_account"], "Note": h["narration"],
                    "Cancelled": "yes" if h["is_cancelled"] else ""} for h in hist])
ui.show_table(df, "adv_hist", money_cols=["Amount"])
