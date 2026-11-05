"""Hisaab Check: re-calculates everything from scratch and compares it with what is saved in the books.

Every check returns  (title, ok: bool, explanation, rows: list[dict]).
"""
from collections import defaultdict
from datetime import timedelta

from core import calc, clock, db, trips

TOL = calc.SETTLED_TOLERANCE


def _net(lines) -> dict:
    out = defaultdict(lambda: calc.ZERO)
    for acc, dr, cr in lines:
        out[acc] += calc.D(dr) - calc.D(cr)
    return {k: v for k, v in out.items() if v != 0}


# ---------- one trip ----------

def trip_check(t: dict) -> list[dict]:
    """Rows: what the formula says vs what the ledger has, for one trip."""
    rows = []
    led = db.query("select account_id, coalesce(sum(debit - credit), 0) net from v_ledger "
                   "where trip_id = %s group by account_id", (t["id"],))
    led = {r["account_id"]: calc.D(r["net"]) for r in led}

    def row(item, formula, expected, actual):
        rows.append({"Item": item, "Formula": formula, "Should be": float(expected), "In books": float(actual),
                     "OK": "✅" if abs(expected - actual) < calc.Decimal("0.01") else "❌"})

    w = t["billing_weight"]
    RU = db.rate_unit()
    row("Party bill (freight + demurrage)", f"{calc.rate_text(w, t['party_rate'], RU)} + {t['party_demurrage']}",
        t["party_freight"] + t["party_demurrage"],
        sum((calc.D(r["debit"]) for r in db.query(
            "select debit from v_ledger where trip_id=%s and v_type='TRIP' and account_id=%s",
            (t["id"], t["party_id"]))), calc.ZERO))
    if t.get("owner_id"):
        row("Truck hire + demurrage", f"{calc.rate_text(w, t['truck_rate'] or 0, RU)} + {t['truck_demurrage']}",
            t["truck_hire"] + t["truck_demurrage"],
            sum((calc.D(r["credit"]) for r in db.query(
                "select credit from v_ledger where trip_id=%s and v_type='TRIP' and account_id=%s",
                (t["id"], t["owner_id"]))), calc.ZERO))
        formula = ("hire + demurrage − paid − diesel − commission − shortage/damage = "
                   f"{t['truck_hire']} + {t['truck_demurrage']} − {t['truck_paid']} − {t['diesel']} − "
                   f"{t['commission']} − {t['truck_shortage']}")
        row("Truck balance (owner)", formula, t["truck_balance"], -led.get(t["owner_id"], calc.ZERO))
    row("Party balance", f"freight + demurrage − received − TDS − shortage = {t['party_freight']} + "
        f"{t['party_demurrage']} − {t['party_received']} − {t['party_tds']} − {t['party_shortage']}",
        t["party_balance"],
        led.get(t["party_id"], calc.ZERO))
    row("Profit", "margin + commission − party short + truck short + party dem − truck dem", t["net_profit"],
        -sum((v for a, v in led.items() if a in _income_expense_ids()), calc.ZERO))
    return rows


_IE = None


def _income_expense_ids() -> set:
    global _IE
    if _IE is None:
        _IE = {r["id"] for r in db.query("select id from accounts where acc_type in ('INCOME','EXPENSE')")}
    return _IE


# ---------- whole system ----------

def run_all() -> list[tuple]:
    global _IE
    _IE = None
    results = []
    all_trips = trips.load_trips("not t.is_cancelled", None, "t.id")
    sys_acc = db.system_accounts()

    # 1. every entry balanced
    bad = db.query("select v.id, v.v_date, v.v_type, v.amount, sum(e.debit) dr, sum(e.credit) cr "
                   "from vouchers v join ledger_entries e on e.voucher_id = v.id "
                   "group by v.id having abs(sum(e.debit) - sum(e.credit)) > 0.005")
    results.append(("Every entry: Debit = Credit", not bad,
                    "Double-entry rule. Each saved entry must have equal debit and credit.", bad))

    # 2. trip bills match today's formula
    stored = defaultdict(list)
    for r in db.query("select v.trip_id, e.account_id, e.debit, e.credit from ledger_entries e "
                      "join vouchers v on v.id = e.voucher_id where v.v_type = 'TRIP' and not v.is_cancelled"):
        stored[r["trip_id"]].append((r["account_id"], r["debit"], r["credit"]))
    mism = []
    for t in all_trips:
        exp = _net(calc.trip_posting_lines(t, t, sys_acc))
        got = _net(stored.get(t["id"], []))
        if exp != got:
            mism.append({"Trip": t["trip_no"], "Truck": t.get("truck_no"), "id": t["id"],
                         "Freight (formula)": float(t["party_freight"]), "Hire (formula)": float(t["truck_hire"])})
    results.append(("Trip bills match the formula", not mism,
                    "Freight, hire, commission and shortage in the books are re-calculated from trip details.", mism))

    # 3. balance paid before POD
    rows = db.query("select v.id, v.v_date, v.amount, t.trip_no, t.gr_no from vouchers v join trips t on t.id=v.trip_id "
                    "where v.v_type='PAYMENT' and v.purpose='BALANCE' and not v.is_cancelled and not t.pod_received")
    results.append(("No truck balance paid before POD", not rows,
                    "Balance payment is allowed only after POD (POD may have been unticked later).", rows))

    # 4. overpaid trucks
    rows = [{"Trip": t["trip_no"], "Truck": t["truck_no"], "Owner": t["owner_name"],
             "Truck balance": float(t["truck_balance"])}
            for t in all_trips if calc.is_loaded(t) and t["truck_balance"] < -TOL]
    results.append(("No truck paid more than its hire", not rows,
                    "Negative truck balance = owner got extra money and must return / adjust it.", rows))

    # 5. party received more than freight
    rows = [{"Trip": t["trip_no"], "Party": t["party_name"], "Party balance": float(t["party_balance"])}
            for t in all_trips if calc.is_loaded(t) and t["party_balance"] < -TOL]
    results.append(("No party paid more than freight", not rows,
                    "Negative party balance = extra received (advance for next trip or a mistake).", rows))

    # 6. missing rates
    rows = [{"Trip": t["trip_no"], "Truck": t.get("truck_no"), "Party rate": float(t["party_rate"] or 0),
             "Truck rate": float(t["truck_rate"] or 0)}
            for t in all_trips if calc.is_loaded(t) and (not t["party_rate"] or not t["truck_rate"])]
    results.append(("Loaded trips have both rates", not rows, "A loaded trip with rate 0 makes a zero bill.", rows))

    # 7. same truck on two running trips
    running = defaultdict(list)
    for t in all_trips:
        if t.get("truck_id") and t["status"] in ("Truck Assigned", "Loaded"):
            running[t["truck_no"]].append(t["trip_no"])
    rows = [{"Truck": k, "Trips": ", ".join(v)} for k, v in running.items() if len(v) > 1]
    results.append(("No truck on two running trips at once", not rows,
                    "Usually means the wrong truck was selected in one trip.", rows))

    # 8. cash never negative
    cash = sys_acc.get("CASH")
    rows = []
    if cash:
        ob = calc.D(db.one("select opening_balance from accounts where id=%s", (cash,))["opening_balance"])
        run = ob
        for r in db.query("select v_date, sum(debit - credit) net from v_ledger where account_id=%s "
                          "group by v_date order by v_date", (cash,)):
            run += calc.D(r["net"])
            if run < -TOL:
                rows.append({"Date": r["v_date"], "Cash closing": float(run)})
    results.append(("Cash in hand never negative", not rows,
                    "Negative cash means a receipt was missed or a payment was entered from the wrong account.", rows))

    # 9. owner / party ledgers vs trip balances
    for acc_type, key, sign, label in (("OWNER", "owner_id", -1, "Truck owner"), ("PARTY", "party_id", 1, "Party")):
        per = defaultdict(lambda: calc.ZERO)
        for t in all_trips:
            if t.get(key):
                per[t[key]] += t["truck_balance" if acc_type == "OWNER" else "party_balance"]
        rows = []
        for r in db.query("select a.id, a.name, a.opening_balance + coalesce(sum(l.debit - l.credit), 0) bal, "
                          "coalesce(sum(l.debit - l.credit) filter (where l.trip_id is null), 0) non_trip, "
                          "a.opening_balance ob "
                          "from accounts a left join v_ledger l on l.account_id = a.id "
                          "where a.acc_type = %s group by a.id", (acc_type,)):
            ledger_bal = calc.D(r["bal"]) * sign
            trip_sum = per.get(r["id"], calc.ZERO)
            other = (calc.D(r["ob"]) + calc.D(r["non_trip"])) * sign
            if abs(ledger_bal - trip_sum - other) > TOL:
                rows.append({"Name": r["name"], "Ledger": float(ledger_bal), "Sum of trips": float(trip_sum),
                             "Opening + non-trip": float(other)})
        results.append((f"{label} ledger = sum of its trips (+ opening & non-trip entries)", not rows,
                        "Ledger balance is checked against trip-wise balances.", rows))

    # 10. reminders (not errors)
    old = clock.today() - timedelta(days=15)
    rows = [{"Trip": t["trip_no"], "Truck": t["truck_no"], "Loaded": t["loading_date"]}
            for t in all_trips if t["status"] in ("Loaded", "Unloaded") and t.get("loading_date") and t["loading_date"] < old]
    results.append(("POD pending more than 15 days", not rows, "Reminder only.", rows))
    return results
