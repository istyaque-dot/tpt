"""Run: python -m pytest tests  (or: python tests/test_calc.py)"""
import os
import sys
from decimal import Decimal as Dec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import calc  # noqa: E402

SYS = {"FREIGHT_INCOME": 101, "LORRY_HIRE": 102, "COMMISSION_INCOME": 103,
       "SHORTAGE_EXP": 104, "SHORTAGE_REC": 105, "DEMURRAGE_EXP": 106, "DEMURRAGE_INC": 107, "TDS_REC": 108}


def base_trip(**kw):
    t = dict(party_id=1, owner_id=2, truck_id=7, party_rate=Dec("1200"), truck_rate=Dec("1100"),
             loaded_weight=Dec("25.500"), unloaded_weight=None, freight_basis="LOADED",
             commission_type="FIXED", commission_value=Dec("500"),
             party_shortage_amt=0, truck_shortage_amt=0, pod_received=False, is_cancelled=False,
             party_received=0, truck_paid=0, diesel=0, gr_no=None)
    t.update(kw)
    return t


def test_freight_and_hire_loaded_basis():
    a = calc.trip_amounts(base_trip())
    assert a["party_freight"] == Dec("30600.00")
    assert a["truck_hire"] == Dec("28050.00")
    assert a["margin"] == Dec("2550.00")
    assert a["commission"] == Dec("500.00")
    assert a["truck_balance"] == Dec("27550.00")
    assert a["net_profit"] == Dec("3050.00")


def test_unloaded_basis_uses_unloaded_when_present():
    t = base_trip(freight_basis="UNLOADED")
    assert calc.trip_amounts(t)["party_freight"] == Dec("30600.00")      # falls back to loaded
    t["unloaded_weight"] = Dec("25.200")
    a = calc.trip_amounts(t)
    assert a["party_freight"] == Dec("30240.00")
    assert a["shortage_weight"] == Dec("0.300")


def test_percent_commission():
    a = calc.trip_amounts(base_trip(commission_type="PERCENT", commission_value=Dec("2.5")))
    assert a["commission"] == Dec("701.25")    # 2.5% of 28050


def test_truck_balance_with_advance_diesel_shortage():
    t = base_trip(truck_paid=Dec("10000"), diesel=Dec("8000.50"), truck_shortage_amt=Dec("600"))
    a = calc.trip_amounts(t)
    assert a["truck_balance"] == Dec("28050") - Dec("10000") - Dec("8000.50") - Dec("500") - Dec("600")


def test_party_balance():
    a = calc.trip_amounts(base_trip(party_received=Dec("20000"), party_shortage_amt=Dec("900")))
    assert a["party_balance"] == Dec("9700.00")


def test_not_loaded_has_no_amounts_but_advance_shows():
    t = base_trip(loaded_weight=None, party_received=Dec("5000"))
    a = calc.trip_amounts(t)
    assert a["party_freight"] == 0 and a["commission"] == 0
    assert a["party_balance"] == Dec("-5000.00")
    assert calc.trip_status(t, a) == "Truck Assigned"


def test_status_flow():
    t = base_trip(truck_id=None, loaded_weight=None)
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Booked"
    t = base_trip()
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Loaded"
    t = base_trip(unloaded_weight=Dec("25"))
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Unloaded"
    t = base_trip(pod_received=True)
    assert calc.trip_status(t, calc.trip_amounts(t)) == "POD Received"
    t = base_trip(pod_received=True, truck_paid=Dec("27550"))
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Truck Settled"
    t = base_trip(pod_received=True, truck_paid=Dec("27550"), party_received=Dec("30600"))
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Closed"
    t = base_trip(party_received=Dec("30600"))     # party paid, POD not yet
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Loaded"
    t = base_trip(pod_received=True, party_received=Dec("30600"))
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Party Settled"
    t = base_trip(is_cancelled=True)
    assert calc.trip_status(t, calc.trip_amounts(t)) == "Cancelled"


def test_postings_balanced_and_correct():
    t = base_trip(party_shortage_amt=Dec("900"), truck_shortage_amt=Dec("600"))
    a = calc.trip_amounts(t)
    lines = calc.trip_posting_lines(t, a, SYS)
    assert calc.lines_balanced(lines)
    by_acc = {}
    for acc, dr, cr in lines:
        by_acc[acc] = by_acc.get(acc, 0) + dr - cr
    assert by_acc[1] == Dec("30600") - Dec("900")                      # party receivable
    assert by_acc[2] == -(Dec("28050") - Dec("500") - Dec("600"))        # owner payable before payments
    assert by_acc[101] == Dec("-30600")
    # owner payable equals truck balance before payments
    assert -by_acc[2] == a["truck_balance"]


def test_no_postings_when_not_loaded_or_cancelled():
    assert calc.trip_posting_lines(base_trip(loaded_weight=None), calc.trip_amounts(base_trip(loaded_weight=None)), SYS) == []
    t = base_trip(is_cancelled=True)
    assert calc.trip_posting_lines(t, calc.trip_amounts(t), SYS) == []


def test_truck_payment_rules():
    t = base_trip()
    a = calc.trip_amounts(t)
    errs = calc.check_truck_payment(t, a, "BALANCE", Dec("1000"), False, False)
    assert any("POD" in e for e in errs)
    t = base_trip(pod_received=True)
    a = calc.trip_amounts(t)
    assert calc.check_truck_payment(t, a, "BALANCE", Dec("27550"), False, False) == []
    assert calc.check_truck_payment(t, a, "BALANCE", Dec("27550"), True, False)      # GR required
    assert calc.check_truck_payment(t, a, "ADVANCE", Dec("30000"), False, False)     # more than balance
    assert calc.check_truck_payment(t, a, "ADVANCE", Dec("30000"), False, True) == []
    assert calc.check_truck_payment(t, a, "ADVANCE", Dec("0"), False, False)


def test_locks():
    t = base_trip(pod_received=True, truck_paid=Dec("27550"))
    lk = calc.edit_locks(t, calc.trip_amounts(t))
    assert lk["truck"] and lk["weights"] and not lk["party"] and not lk["closed"]


def test_cancel_rules():
    assert calc.can_cancel_trip(base_trip(loaded_weight=None), 0)[0]
    assert not calc.can_cancel_trip(base_trip(loaded_weight=None), 1)[0]
    assert not calc.can_cancel_trip(base_trip(), 0)[0]


def test_normalizers():
    assert calc.normalize_truck_no(" mh 12-ab 1234 ") == "MH12AB1234"
    assert calc.normalize_gr(" gr4521 ") == "GR4521"


def test_books_identity_matches_formula():
    """What Hisaab Check relies on: ledger of a trip == formula balances (party, owner, profit)."""
    CASH, PUMP = 200, 300
    t = base_trip(pod_received=True, unloaded_weight=Dec("25.2"), party_shortage_amt=Dec("900"),
                  truck_shortage_amt=Dec("600"), commission_type="PERCENT", commission_value=Dec("2"),
                  truck_demurrage_amt=Dec("1500"), party_demurrage_amt=Dec("1000"))
    vouchers = [  # (dr, cr, amount)  — advance, diesel, balance payment, party receipts
        (2, CASH, Dec("10000")), (2, PUMP, Dec("8000.50")), (2, CASH, Dec("5000")),
        (CASH, 1, Dec("20000")), (CASH, 1, Dec("1234.56")),
    ]
    t.update(truck_paid=Dec("15000"), diesel=Dec("8000.50"), party_received=Dec("21234.56"))
    a = calc.trip_amounts(t)
    lines = calc.trip_posting_lines(t, a, SYS)
    for dr, cr, amt in vouchers:
        lines += [(dr, amt, Dec(0)), (cr, Dec(0), amt)]
    assert calc.lines_balanced(lines)
    net = {}
    for acc, dr, cr in lines:
        net[acc] = net.get(acc, Dec(0)) + dr - cr
    assert -net[2] == a["truck_balance"]
    assert net[1] == a["party_balance"]
    assert -sum(net[k] for k in SYS.values() if k in net) == a["net_profit"]


def test_party_split():
    trips_ = [dict(id=1, party_balance=Dec("10000")), dict(id=2, party_balance=Dec("0")),
              dict(id=3, party_balance=Dec("25000")), dict(id=4, party_balance=Dec("5000"))]
    assert calc.auto_allocate(Dec("30000"), trips_) == {1: Dec("10000"), 3: Dec("20000")}
    assert calc.auto_allocate(Dec("50000"), trips_) == {1: Dec("10000"), 3: Dec("25000"), 4: Dec("5000")}
    sm = calc.split_summary(Dec("50000"), [Dec("10000"), Dec("25000"), Dec("5000")])
    assert sm["on_account"] == Dec("10000") and not sm["over"]
    assert calc.split_summary(100, [60, 50])["over"]
    t = base_trip()
    t.update(calc.trip_amounts(t))                     # loaded, party balance 30600
    assert calc.receipt_purpose(t, Dec("30600")) == "BALANCE"
    assert calc.receipt_purpose(t, Dec("10000")) == "ADVANCE"
    t2 = base_trip(loaded_weight=None)
    t2.update(calc.trip_amounts(t2))
    assert calc.receipt_purpose(t2, Dec("99999")) == "ADVANCE"


def test_group_batches():
    rows = [dict(batch_no="R1", debit=Dec("10000"), credit=0, trip_no="T-1", narration="ABC · RJ1 · T-1"),
            dict(batch_no=None, debit=0, credit=Dec("500"), trip_no=None, narration="tea"),
            dict(batch_no="R1", debit=Dec("20000"), credit=0, trip_no="T-2", narration="ABC · RJ2 · T-2")]
    g = calc.group_batches(rows)
    assert len(g) == 2 and g[0]["debit"] == Dec("30000") and g[0]["trip_no"] == "T-1, T-2"
    assert g[0]["narration"] == "ABC · 2 trucks"


def test_demurrage():
    t = base_trip(pod_received=True, truck_demurrage_amt=Dec("2000"), party_demurrage_amt=Dec("1500"),
                  truck_shortage_amt=Dec("700"))
    a = calc.trip_amounts(t)
    assert a["truck_balance"] == Dec("28050") + Dec("2000") - Dec("500") - Dec("700")
    assert a["party_balance"] == Dec("30600") + Dec("1500")
    assert a["net_profit"] == Dec("2550") + Dec("500") + Dec("700") + Dec("1500") - Dec("2000")
    lines = calc.trip_posting_lines(t, a, SYS)
    assert calc.lines_balanced(lines)
    t2 = base_trip(loaded_weight=None, truck_demurrage_amt=Dec("2000"))
    assert calc.trip_amounts(t2)["truck_demurrage"] == 0


def test_advance_adjustment_keeps_books_right():
    """Party paid 50,000 'on account'; 30,600 is later moved to trip 1 through the clearing account."""
    PARTY, BANK, ADJ = 1, 200, 900
    lines = [(BANK, Dec("50000"), Dec(0)), (PARTY, Dec(0), Dec("50000"))]           # on-account receipt (no trip)
    lines += [(PARTY, Dec("30600"), Dec(0)), (ADJ, Dec(0), Dec("30600"))]           # off 'on account'
    trip_lines = [(ADJ, Dec("30600"), Dec(0)), (PARTY, Dec(0), Dec("30600"))]      # onto the trip (RECEIPT)
    t = base_trip(party_received=Dec("30600"))
    a = calc.trip_amounts(t)
    trip_lines += calc.trip_posting_lines(t, a, SYS)
    allx = lines + trip_lines
    assert calc.lines_balanced(allx)
    net = {}
    for acc, dr, cr in allx:
        net[acc] = net.get(acc, Dec(0)) + dr - cr
    assert net.get(ADJ, 0) == 0                                  # clearing account always back to zero
    assert a["party_balance"] == 0                               # trip shows paid
    assert net[PARTY] == Dec("-19400")                           # 19,400 advance still on account


def test_party_tds_one_percent():
    t = base_trip(tds_rate=Dec("1"), party_demurrage_amt=Dec("1000"))
    a = calc.trip_amounts(t)
    assert a["party_tds"] == Dec("316")                       # 1% of (30600 + 1000), rounded to rupee
    assert a["party_balance"] == Dec("30600") + Dec("1000") - Dec("316")
    assert a["net_profit"] == calc.trip_amounts(base_trip(party_demurrage_amt=Dec("1000")))["net_profit"]
    lines = calc.trip_posting_lines(t, a, SYS)
    assert calc.lines_balanced(lines)
    net = {}
    for acc, dr, cr in lines:
        net[acc] = net.get(acc, Dec(0)) + dr - cr
    assert net[108] == Dec("316") and net[1] == a["party_balance"]      # TDS receivable; party owes the rest
    # party pays exactly the net amount -> settled
    t2 = base_trip(tds_rate=Dec("1"), party_received=Dec("30294"), pod_received=True)
    assert calc.party_settled(t2, calc.trip_amounts(t2))
    assert calc.trip_amounts(base_trip(tds_rate=Dec("0")))["party_tds"] == 0
    assert calc.trip_amounts(base_trip(tds_rate=Dec("1"), loaded_weight=None))["party_tds"] == 0


def test_rate_units():
    assert calc.rate_store(Dec("175"), "QUINTAL") == Dec("1750.00")
    assert calc.rate_show(Dec("1750"), "QUINTAL") == Dec("175")
    assert calc.rate_store(Dec("1750"), "TON") == Dec("1750.00")
    assert calc.rate_text(Dec("35"), Dec("1750"), "QUINTAL") == "350 qtl × ₹175"
    assert calc.rate_text(Dec("25.5"), Dec("1100"), "TON") == "25.5 T × ₹1100"
    # 35 T at ₹175/qtl: hire = 35 × 1750 = 61,250
    t = base_trip(loaded_weight=Dec("35"), truck_rate=calc.rate_store(Dec("175"), "QUINTAL"), commission_value=0)
    assert calc.trip_amounts(t)["truck_hire"] == Dec("61250.00")


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
    print(f"{n} tests passed")
