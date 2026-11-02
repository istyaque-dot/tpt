from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import calc, clock, db, trips, ui

st.markdown("### 📊 Reports & Ledgers")

TYPE_LABEL = {"CASH": "Cash", "BANK": "Bank", "PARTY": "Party", "OWNER": "Truck Owner", "PUMP": "Petrol Pump",
              "INCOME": "Income", "EXPENSE": "Expense"}


def balances(acc_types, as_on: date) -> list[dict]:
    return db.query(
        "select a.id, a.name, a.acc_type, a.mobile, "
        "       a.opening_balance + coalesce(sum(l.debit - l.credit), 0) as balance "
        "from accounts a left join v_ledger l on l.account_id = a.id and l.v_date <= %s "
        "where a.acc_type = any(%s) group by a.id order by a.name", (as_on, list(acc_types)))


def ledger(account_id: int, d_from: date, d_to: date):
    acc = db.one("select * from accounts where id=%s", (account_id,))
    before = db.one("select coalesce(sum(debit - credit), 0) s from v_ledger where account_id=%s and v_date < %s",
                    (account_id, d_from))["s"]
    opening = calc.D(acc["opening_balance"]) + calc.D(before)
    rows = db.query("select v_date, voucher_id, v_type, purpose, trip_no, gr_no, ref_no, narration, litres, "
                    "debit, credit, batch_no from v_ledger where account_id=%s and v_date between %s and %s "
                    "order by v_date, voucher_id, id", (account_id, d_from, d_to))
    run = opening
    for r in rows:
        run += calc.D(r["debit"]) - calc.D(r["credit"])
        r["balance"] = ui.drcr(run)
    return acc, opening, rows, run


def date_range(key, days=30):
    c1, c2 = st.columns(2)
    a = c1.date_input("From", value=clock.today() - timedelta(days=days), format="DD/MM/YYYY", key=f"{key}_f")
    b = c2.date_input("To", value=clock.today(), format="DD/MM/YYYY", key=f"{key}_t")
    return a, b


SECTIONS = ["Profit & Loss", "Trip Register", "Ledger", "Cash / Bank Book", "Party Outstanding",
            "Owner Payable", "Pump Payable", "Trip Profit", "Pending POD / GR", "Trial Balance"]
# only the chosen report is loaded (tabs used to load all ten every time)
sel = st.pills("Report", SECTIONS, default="Profit & Loss", key="rep_sel", label_visibility="collapsed") \
    or "Profit & Loss"

# ---------- Profit & Loss (trips + office expenses) ----------
if sel == "Profit & Loss":
    d_from, d_to = date_range("pnl", 30)
    rows = db.query(
        "select a.acc_type, a.name, coalesce(sum(l.credit - l.debit), 0) amt from v_ledger l "
        "join accounts a on a.id = l.account_id where a.acc_type in ('INCOME','EXPENSE') "
        "and l.v_date between %s and %s group by a.acc_type, a.name order by a.acc_type desc, a.name",
        (d_from, d_to))
    inc = [r for r in rows if r["acc_type"] == "INCOME" and r["amt"]]
    exp = [r for r in rows if r["acc_type"] == "EXPENSE" and r["amt"]]
    ti = sum((calc.D(r["amt"]) for r in inc), calc.ZERO)
    te = sum((-calc.D(r["amt"]) for r in exp), calc.ZERO)
    ui.metric_grid([("Income", ui.inr(ti)), ("Expenses", ui.inr(te)), ("Net profit", ui.inr(ti - te))], per_row=3)
    st.caption("Lorry hire, demurrage paid, shortage and office expenses are expenses; freight, commission, "
               "demurrage charged and shortage recovery are income.")
    df = pd.DataFrame([{"Head": r["name"], "Income": float(r["amt"]), "Expense": 0.0} for r in inc]
                      + [{"Head": r["name"], "Income": 0.0, "Expense": float(-r["amt"])} for r in exp],
                      columns=["Head", "Income", "Expense"])
    ui.show_table(df, "pnl", money_cols=["Income", "Expense"], download_name=f"profit_loss_{d_from}_{d_to}")

# ---------- Trip register ----------
if sel == "Trip Register":
    d_from, d_to = date_range("reg", 60)
    c1, c2 = st.columns(2)
    status_f = c1.multiselect("Status", calc.STATUS_ORDER, key="reg_status")
    party_f = c2.text_input("Party / truck contains", key="reg_txt")
    rows = trips.load_trips("t.booking_date between %s and %s", (d_from, d_to))
    if status_f:
        rows = [r for r in rows if r["status"] in status_f]
    if party_f.strip():
        s = party_f.strip().upper()
        k = calc.normalize_truck_no(s)
        rows = [r for r in rows if s in (r.get("party_name") or "").upper() or (k and k in (r.get("truck_no") or ""))]
    st.caption(f"{len(rows)} trips")
    df = ui.money_df(rows, {
        "trip_no": "Trip", "booking_date": "Booked", "gr_no": "GR No.", "truck_no": "Truck",
        "party_name": "Party", "from_place": "From", "to_place": "To", "billing_weight": "Weight",
        "party_freight": "Party Freight", "party_balance": "Party Bal", "truck_hire": "Truck Hire",
        "truck_balance": "Truck Bal", "net_profit": "Profit", "status": "Status"})
    ui.show_table(df, "trip_register", money_cols=["Party Freight", "Party Bal", "Truck Hire", "Truck Bal", "Profit"],
                  download_name="trip_register")

# ---------- Ledger ----------
if sel == "Ledger":
    c1, c2 = st.columns([1, 2])
    acc_type = c1.selectbox("Account type", list(TYPE_LABEL), format_func=TYPE_LABEL.get, index=2)
    with c2:
        acc_id = ui.pick_account("Account", db.accounts(acc_type, active_only=False), "lg_acc")
    d_from, d_to = date_range("lg", 90)
    if acc_id:
        acc, opening, rows, closing = ledger(acc_id, d_from, d_to)
        ui.metric_grid([("Opening", ui.drcr(opening)), ("Closing", ui.drcr(closing))])
        st.caption({"PARTY": "Dr = party owes us", "OWNER": "Cr = we owe owner",
                    "PUMP": "Cr = we owe pump"}.get(acc["acc_type"], ""))
        df = ui.money_df(rows, {"v_date": "Date", "voucher_id": "No.", "v_type": "Type", "purpose": "For",
                                "trip_no": "Trip", "gr_no": "GR No.", "ref_no": "Ref", "narration": "Narration",
                                "litres": "Litres", "debit": "Debit", "credit": "Credit", "balance": "Balance"})
        ui.show_table(df, "ledger", money_cols=["Debit", "Credit"],
                      download_name=f"ledger_{acc['name']}_{d_from}_{d_to}")

# ---------- Cash / Bank book ----------
if sel == "Cash / Bank Book":
    acc_id = ui.pick_account("Cash / Bank account", db.money_accounts(), "cb_acc", index=0)
    d_from, d_to = date_range("cb", 7)
    if acc_id:
        acc, opening, rows, closing = ledger(acc_id, d_from, d_to)
        days = {}
        for r in rows:
            d = days.setdefault(r["v_date"], {"in": calc.ZERO, "out": calc.ZERO})
            d["in"] += calc.D(r["debit"])
            d["out"] += calc.D(r["credit"])
        summary, bal = [], opening
        for d in sorted(days):
            o = bal
            bal = o + days[d]["in"] - days[d]["out"]
            summary.append({"Date": d, "Opening": float(o), "Received": float(days[d]["in"]),
                            "Paid": float(days[d]["out"]), "Closing": float(bal)})
        ui.metric_grid([("Opening", ui.inr(opening)), ("Closing", ui.inr(closing))])
        st.markdown("**Day-wise**")
        ui.show_table(pd.DataFrame(summary), "cb_days", money_cols=["Opening", "Received", "Paid", "Closing"])
        st.markdown("**Details**")
        if st.toggle("One line per bank entry (like bank statement)", value=True, key="cb_group"):
            rows = calc.group_batches(rows)
            run = opening
            for r in rows:
                run += calc.D(r["debit"]) - calc.D(r["credit"])
                r["balance"] = ui.drcr(run)
        df = ui.money_df(rows, {"v_date": "Date", "voucher_id": "No.", "v_type": "Type", "trip_no": "Trip",
                                "ref_no": "Ref", "narration": "Narration", "debit": "Received",
                                "credit": "Paid", "balance": "Balance"})
        ui.show_table(df, "cb_detail", money_cols=["Received", "Paid"],
                      download_name=f"{acc['name']}_book_{d_from}_{d_to}")

# ---------- Outstanding lists ----------
for label, acc_type, sign, col in (("Party Outstanding", "PARTY", 1, "Receivable"),
                                   ("Owner Payable", "OWNER", -1, "Payable"),
                                   ("Pump Payable", "PUMP", -1, "Payable")):
    if sel == label:
        as_on = st.date_input("As on", value=clock.today(), format="DD/MM/YYYY", key=f"os_{acc_type}")
        hide_zero = st.checkbox("Hide zero balances", value=True, key=f"os_z_{acc_type}")
        rows = balances([acc_type], as_on)
        for r in rows:
            r[col] = float(calc.D(r["balance"]) * sign)
        if hide_zero:
            rows = [r for r in rows if abs(r[col]) >= 0.5]
        total = sum(r[col] for r in rows)
        st.metric(f"Total {col.lower()}", ui.inr(total))
        df = pd.DataFrame([{"Name": r["name"], "Mobile": r["mobile"], col: r[col]} for r in rows])
        ui.show_table(df, f"os_tbl_{acc_type}", money_cols=[col], download_name=f"{acc_type.lower()}_outstanding")
        st.caption("Negative = advance (the other side owes). For details open the Ledger tab.")

# ---------- Trip profit ----------
if sel == "Trip Profit":
    d_from, d_to = date_range("tpf", 30)
    rows = trips.load_trips("not t.is_cancelled and t.loading_date between %s and %s", (d_from, d_to),
                            "t.loading_date, t.id")
    tot = {k: sum((calc.D(r[k]) for r in rows), calc.ZERO)
           for k in ("party_freight", "truck_hire", "margin", "commission", "party_shortage", "truck_shortage",
                     "net_profit")}
    ui.metric_grid([("Trips", len(rows)), ("Party freight", ui.inr(tot["party_freight"])),
                    ("Truck hire", ui.inr(tot["truck_hire"])), ("Net profit", ui.inr(tot["net_profit"]))])
    df = ui.money_df(rows, {"trip_no": "Trip", "loading_date": "Loaded", "gr_no": "GR No.", "truck_no": "Truck",
                            "party_name": "Party", "billing_weight": "Weight", "party_freight": "Freight",
                            "truck_hire": "Hire", "margin": "Margin", "commission": "Commission",
                            "party_shortage": "Party short", "truck_shortage": "Truck short",
                            "net_profit": "Net profit", "status": "Status"})
    ui.show_table(df, "trip_profit", money_cols=["Freight", "Hire", "Margin", "Commission", "Party short",
                                                 "Truck short", "Net profit"],
                  download_name=f"trip_profit_{d_from}_{d_to}")

# ---------- Pending POD / GR ----------
if sel == "Pending POD / GR":
    rows = trips.load_trips("not t.is_cancelled and t.loaded_weight is not null and not t.pod_received",
                            None, "t.loading_date")
    for r in rows:
        r["days"] = (clock.today() - r["loading_date"]).days if r.get("loading_date") else None
    st.markdown(f"**Pending POD — {len(rows)} trips**")
    ui.show_table(ui.money_df(rows, {"trip_no": "Trip", "loading_date": "Loaded", "days": "Days",
                                     "gr_no": "GR No.", "truck_no": "Truck", "owner_name": "Owner",
                                     "party_name": "Party", "to_place": "To", "truck_balance": "Truck bal"}),
                  "pending_pod", money_cols=["Truck bal"], download_name="pending_pod")
    rows = trips.load_trips("not t.is_cancelled and t.gr_no is null", None, "t.booking_date")
    st.markdown(f"**Pending GR No. — {len(rows)} trips**")
    ui.show_table(ui.money_df(rows, {"trip_no": "Trip", "booking_date": "Booked", "truck_no": "Truck",
                                     "party_name": "Party", "from_place": "From", "to_place": "To",
                                     "status": "Status"}), "pending_gr", download_name="pending_gr")

# ---------- Trial balance ----------
if sel == "Trial Balance":
    as_on = st.date_input("As on", value=clock.today(), format="DD/MM/YYYY", key="tb_on")
    rows = balances(list(TYPE_LABEL), as_on)
    data = [{"Type": TYPE_LABEL[r["acc_type"]], "Account": r["name"],
             "Debit": float(max(calc.D(r["balance"]), calc.ZERO)),
             "Credit": float(max(-calc.D(r["balance"]), calc.ZERO))}
            for r in rows if abs(calc.D(r["balance"])) >= calc.Decimal("0.01")]
    df = pd.DataFrame(data, columns=["Type", "Account", "Debit", "Credit"])
    dr, cr = df["Debit"].sum(), df["Credit"].sum()
    ui.metric_grid([("Total Debit", ui.inr(dr)), ("Total Credit", ui.inr(cr)), ("Difference", ui.inr(dr - cr))])
    st.caption("Difference is only from opening balances (e.g. capital not entered). All entries are double-entry.")
    ui.show_table(df.sort_values(["Type", "Account"]), "trial", money_cols=["Debit", "Credit"],
                  download_name="trial_balance")
