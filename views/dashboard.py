from collections import Counter
from datetime import timedelta

import streamlit as st

from core import calc, clock, db, trips, ui

st.markdown("### 📈 Dashboard")
today = clock.today()

bal = db.query(
    "select a.acc_type, a.name, a.opening_balance + coalesce(sum(l.debit - l.credit), 0) as balance "
    "from accounts a left join v_ledger l on l.account_id = a.id "
    "where a.acc_type in ('CASH','BANK','PARTY','OWNER','PUMP') group by a.id")


def total(t, sign=1):
    return sum((calc.D(r["balance"]) * sign for r in bal if r["acc_type"] == t), calc.ZERO)


ui.metric_grid([("Cash in hand", ui.inr(total("CASH"))), ("Bank balance", ui.inr(total("BANK"))),
                ("Party receivable", ui.inr(total("PARTY"))), ("Owner payable", ui.inr(total("OWNER", -1))),
                ("Pump payable", ui.inr(total("PUMP", -1)))])

month_start = today.replace(day=1)
since = min(month_start, today - timedelta(days=120))
active = trips.load_trips("not t.is_cancelled and (t.booking_date >= %s or not t.pod_received or t.gr_no is null)",
                          (since,))
month = [t for t in active if t.get("loading_date") and t["loading_date"] >= month_start]
st.subheader(f"This month ({today:%B %Y})")
ui.metric_grid([("Trips loaded", len(month)),
                ("Party freight", ui.inr(sum((t["party_freight"] for t in month), calc.ZERO))),
                ("Truck hire", ui.inr(sum((t["truck_hire"] for t in month), calc.ZERO))),
                ("Net profit", ui.inr(sum((t["net_profit"] for t in month), calc.ZERO)))])

st.subheader("Open & recent trips by status")
counts = Counter(t["status"] for t in active)
ui.metric_grid([(s_, counts.get(s_, 0)) for s_ in calc.STATUS_ORDER if s_ != "Cancelled"], per_row=4)

c1, c2 = st.columns(2)
with c1:
    pend = [t for t in active if t["status"] in ("Loaded", "Unloaded")]
    st.markdown(f"**Waiting for POD: {len(pend)}**")
    old = sorted(pend, key=lambda t: t.get("loading_date") or today)[:10]
    ui.show_table(ui.money_df([{**t, "days": (today - t["loading_date"]).days if t.get("loading_date") else None}
                               for t in old],
                              {"trip_no": "Trip", "truck_no": "Truck", "party_name": "Party", "days": "Days"}),
                  "dash_pod")
with c2:
    nogr = [t for t in active if not t.get("gr_no") and t["truck_id"]]
    st.markdown(f"**GR No. pending: {len(nogr)}**")
    ui.show_table(ui.money_df(nogr[:10], {"trip_no": "Trip", "truck_no": "Truck", "party_name": "Party",
                                          "booking_date": "Booked"}), "dash_gr")
