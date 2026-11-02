"""Party Receipt: party pays into bank (one transfer), split truck-wise over its trips.

Logic
- Bank Dr / Party Cr for every truck line (each line is linked to its trip, so trip-wise party balance is right).
- All lines of one bank credit share one batch_no -> Bank Book shows ONE line = bank statement.
- Left-over amount = 'on account' advance (party ledger only, not linked to a trip).
- Line clears the trip's balance -> BALANCE, otherwise ADVANCE.
"""
import uuid

import pandas as pd
import streamlit as st

from core import calc, clock, db, trips, ui

st.markdown("### 💵 Party Receipt (truck-wise)")

parties = db.accounts("PARTY")
pids = [p["id"] for p in parties]
pn = {p["id"]: p["name"] for p in parties}
party = st.selectbox("Party (company)", pids, format_func=pn.get, index=None, placeholder="Type to search",
                     key="pa_party")
if not party:
    st.stop()

open_trips = trips.load_trips("not t.is_cancelled and t.party_id = %s", (party,), "t.id")
open_trips = [t for t in open_trips if not calc.party_settled(t, t)]
due = sum((t["party_balance"] for t in open_trips if t["party_balance"] > 0), calc.ZERO)
led = db.one("select a.opening_balance + coalesce(sum(l.debit - l.credit), 0) bal from accounts a "
             "left join v_ledger l on l.account_id = a.id where a.id = %s group by a.id", (party,))
ui.metric_grid([("Trucks pending", len(open_trips)), ("Trip-wise due", ui.inr(due)),
                ("Ledger balance", ui.drcr(led["bal"] if led else 0))])

# ---------- 1. what came in the bank ----------
st.markdown("#### 1. Bank mein kitna aaya")
total = ui.amount("Amount received ₹", "pa_total")
accs = db.money_accounts()
banks_first = sorted(accs, key=lambda a: 0 if a["acc_type"] == "BANK" else 1)
aids = [a["id"] for a in banks_first]
an = {a["id"]: a["name"] for a in banks_first}
c1, c2 = st.columns(2)
acc = c1.selectbox("Into", aids, format_func=an.get, index=ui.remembered("party_bank", aids), key="pa_acc")
v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY", key="pa_date")
ref = st.text_input("UTR / Ref No.", key="pa_ref", placeholder="From bank SMS / statement")

# ---------- 2. split truck-wise ----------
st.markdown("#### 2. Truck-wise baanto")
if not open_trips:
    st.info("No pending trip for this party. The full amount will go 'on account'.")
q = st.text_input("Filter truck / trip / GR", key="pa_q", placeholder="Last digits of truck")
shown = open_trips
if q.strip():
    k = calc.normalize_truck_no(q)
    shown = [t for t in open_trips if k in (t.get("truck_no") or "") or k in t["trip_no"].replace("-", "")
             or k in calc.normalize_truck_no(t.get("gr_no") or "")]

fill_key = f"pa_fill_{party}"
n = st.session_state.get("pa_n", 0)
c1, c2 = st.columns(2)
if c1.button("⚡ Auto-fill (oldest first)", use_container_width=True, disabled=total <= 0):
    st.session_state[fill_key] = {k_: float(v) for k_, v in calc.auto_allocate(total, open_trips).items()}
    st.session_state["pa_n"] = n + 1
    st.rerun()
if c2.button("Clear", use_container_width=True):
    st.session_state.pop(fill_key, None)
    st.session_state["pa_n"] = n + 1
    st.rerun()

prefill = st.session_state.get(fill_key, {})
df = pd.DataFrame([{
    "id": t["id"], "Amount": prefill.get(t["id"], float("nan")), "Truck": t.get("truck_no") or "—",
    "Trip": t["trip_no"], "GR": t.get("gr_no") or "", "Balance": float(t["party_balance"]),
    "Freight": float(t["party_freight"]), "Received": float(t["party_received"]), "Status": t["status"],
} for t in shown])
alloc = {}
if not df.empty:
    ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"pa_ed_{party}_{n}",
                        disabled=[c for c in df.columns if c != "Amount"],
                        column_config={"id": None,
                                       "Amount": st.column_config.NumberColumn("Amount ₹", min_value=0.0,
                                                                               format="%.2f"),
                                       "Balance": st.column_config.NumberColumn(format="%.2f"),
                                       "Freight": st.column_config.NumberColumn(format="%.2f"),
                                       "Received": st.column_config.NumberColumn(format="%.2f")})
    for _, r in ed.iterrows():
        if pd.notna(r["Amount"]) and r["Amount"] > 0:
            alloc[int(r["id"])] = calc.r2(calc.D(r["Amount"]))
# keep amounts typed for trips hidden by the filter
for tid_, v in prefill.items():
    if tid_ not in {t["id"] for t in shown} and v:
        alloc.setdefault(tid_, calc.r2(calc.D(v)))

sm = calc.split_summary(total, alloc.values())
with st.container(border=True):
    ui.metric_grid([("Received", ui.inr(sm["total"])), ("Truck-wise", ui.inr(sm["allocated"])),
                    ("On account", ui.inr(sm["on_account"]))], per_row=3)
    by_id = {t["id"]: t for t in open_trips}
    extra = [by_id[i]["trip_no"] for i, a in alloc.items() if i in by_id and a > by_id[i]["party_balance"] + calc.SETTLED_TOLERANCE]
    if sm["over"]:
        st.error("Truck-wise total is more than the amount received.")
    if extra:
        st.warning(f"More than balance in: {', '.join(extra)} (allowed — shows as party advance on that trip).")
    if sm["on_account"] > 0 and sm["total"] > 0:
        st.caption("On-account amount stays in the party ledger as advance (not linked to any truck).")

if st.button("💾 Save receipt", type="primary", use_container_width=True,
             disabled=sm["total"] <= 0 or sm["over"] or not acc):
    batch = "R" + uuid.uuid4().hex[:10].upper()
    with db.tx() as cur:
        for tid_, amt in alloc.items():
            t = by_id[tid_]
            trips.add_voucher(cur, v_date=v_date, v_type="RECEIPT", purpose=calc.receipt_purpose(t, amt),
                              trip_id=tid_, amount=amt, dr_account=acc, cr_account=party, ref_no=ref,
                              batch_no=batch,
                              narration=f"{pn[party]} · {t.get('truck_no') or ''} · {t['trip_no']}")
        if sm["on_account"] > 0:
            trips.add_voucher(cur, v_date=v_date, v_type="RECEIPT", purpose="ON_ACCOUNT", amount=sm["on_account"],
                              dr_account=acc, cr_account=party, ref_no=ref, batch_no=batch,
                              narration=f"{pn[party]} · on account")
    ui.remember("party_bank", acc)
    for k_ in ("pa_total", "pa_ref", "pa_q", fill_key):
        st.session_state.pop(k_, None)
    st.session_state["pa_n"] = n + 1
    ui.flash(f"₹{ui.inr(sm['total'])} received from {pn[party]} — {len(alloc)} truck(s)"
             + (f", ₹{ui.inr(sm['on_account'])} on account" if sm["on_account"] > 0 else ""))
    st.rerun()

# ---------- history ----------
st.markdown("#### Recent receipts")
hist = db.query(
    "select coalesce(v.batch_no, 'V' || v.id) grp, min(v.v_date) d, sum(v.amount) amt, max(v.ref_no) ref, "
    "string_agg(coalesce(tk.truck_no, 'on account') || ' ₹' || v.amount, ', ' order by v.id) split, "
    "bool_or(v.is_cancelled) cancelled "
    "from vouchers v join ledger_entries e on e.voucher_id = v.id and e.account_id = %s and e.credit > 0 "
    "left join trips t on t.id = v.trip_id left join trucks tk on tk.id = t.truck_id "
    "where v.v_type = 'RECEIPT' group by 1 order by 2 desc, 1 desc limit 20", (party,))
for h in hist:
    strike = "~~" if h["cancelled"] else ""
    st.markdown(f"{strike}**{h['d']:%d/%m/%Y} · ₹{ui.inr(h['amt'])}**"
                + (f" · UTR {h['ref']}" if h["ref"] else "") + f"{strike}  \n{h['split']}")
if not hist:
    st.caption("No receipts yet.")
