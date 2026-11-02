"""Pure business logic: no database, no Streamlit. Every rupee figure in the app comes from here.

See LOGIC.md sections 3-6.
"""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
PAISA = Decimal("0.01")
SETTLED_TOLERANCE = Decimal("0.50")   # balance within 50 paise counts as settled


def D(x) -> Decimal:
    if x is None or x == "":
        return ZERO
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def r2(x: Decimal) -> Decimal:
    return D(x).quantize(PAISA, rounding=ROUND_HALF_UP)


def is_loaded(trip: dict) -> bool:
    return trip.get("truck_id") is not None and D(trip.get("loaded_weight")) > 0


def billing_weight(trip: dict) -> Decimal:
    """Weight that freight and hire are charged on.

    LOADED basis   -> loaded weight.
    UNLOADED basis -> unloaded weight once entered, loaded weight until then.
    """
    if not is_loaded(trip):
        return ZERO
    loaded = D(trip.get("loaded_weight"))
    if trip.get("freight_basis") == "UNLOADED":
        unloaded = D(trip.get("unloaded_weight"))
        if unloaded > 0:
            return unloaded
    return loaded


def shortage_weight(trip: dict) -> Decimal:
    loaded = D(trip.get("loaded_weight"))
    unloaded = D(trip.get("unloaded_weight"))
    if loaded <= 0 or unloaded <= 0:
        return ZERO
    return max(loaded - unloaded, ZERO)


def commission_amount(trip: dict, truck_hire: Decimal) -> Decimal:
    if not is_loaded(trip):
        return ZERO
    value = D(trip.get("commission_value"))
    if trip.get("commission_type") == "PERCENT":
        return r2(truck_hire * value / Decimal("100"))
    return r2(value)


def trip_amounts(trip: dict) -> dict:
    """trip must contain trip columns plus aggregates:
    party_received, truck_paid, diesel (sums of non-cancelled vouchers linked to the trip)."""
    w = billing_weight(trip)
    loaded = is_loaded(trip)
    party_freight = r2(w * D(trip.get("party_rate"))) if loaded else ZERO
    truck_hire = r2(w * D(trip.get("truck_rate"))) if loaded else ZERO
    commission = commission_amount(trip, truck_hire)
    party_short = r2(D(trip.get("party_shortage_amt"))) if loaded else ZERO
    truck_short = r2(D(trip.get("truck_shortage_amt"))) if loaded else ZERO
    # demurrage (detention): extra paid to truck for waiting; optionally also charged to party
    truck_dem = r2(D(trip.get("truck_demurrage_amt"))) if loaded else ZERO
    party_dem = r2(D(trip.get("party_demurrage_amt"))) if loaded else ZERO

    # TDS: party pays freight after deducting TDS (default 1%) on freight + demurrage.
    # It is not a loss — it is our income-tax credit (TDS Receivable), shown in Form 26AS.
    tds_rate = D(trip.get("tds_rate")) if trip.get("tds_rate") is not None else ZERO
    party_tds = (((party_freight + party_dem) * tds_rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                 if loaded and tds_rate > 0 else ZERO)

    party_received = r2(D(trip.get("party_received")))
    truck_paid = r2(D(trip.get("truck_paid")))
    diesel = r2(D(trip.get("diesel")))

    party_balance = party_freight + party_dem - party_received - party_short - party_tds
    truck_balance = truck_hire + truck_dem - truck_paid - diesel - commission - truck_short
    margin = party_freight - truck_hire
    net_profit = margin + commission - party_short + truck_short + party_dem - truck_dem

    return {
        "billing_weight": w,
        "shortage_weight": shortage_weight(trip),
        "party_freight": party_freight,
        "truck_hire": truck_hire,
        "commission": commission,
        "party_shortage": party_short,
        "truck_shortage": truck_short,
        "truck_demurrage": truck_dem,
        "party_demurrage": party_dem,
        "tds_rate": tds_rate,
        "party_tds": party_tds,
        "party_received": party_received,
        "truck_paid": truck_paid,
        "diesel": diesel,
        "party_balance": party_balance,
        "truck_balance": truck_balance,
        "margin": margin,
        "net_profit": net_profit,
    }


def is_settled(balance: Decimal) -> bool:
    return abs(D(balance)) < SETTLED_TOLERANCE


def truck_settled(trip: dict, amt: dict) -> bool:
    return (is_loaded(trip) and bool(trip.get("pod_received"))
            and amt["truck_hire"] > 0 and is_settled(amt["truck_balance"]))


def party_settled(trip: dict, amt: dict) -> bool:
    return is_loaded(trip) and amt["party_freight"] > 0 and is_settled(amt["party_balance"])


STATUS_ORDER = ["Booked", "Truck Assigned", "Loaded", "Unloaded", "POD Received",
                "Truck Settled", "Party Settled", "Closed", "Cancelled"]


def trip_status(trip: dict, amt: dict) -> str:
    if trip.get("is_cancelled"):
        return "Cancelled"
    if trip.get("truck_id") is None:
        return "Booked"
    if not is_loaded(trip):
        return "Truck Assigned"
    if not trip.get("pod_received"):
        return "Unloaded" if D(trip.get("unloaded_weight")) > 0 else "Loaded"
    ts, ps = truck_settled(trip, amt), party_settled(trip, amt)
    if ts and ps:
        return "Closed"
    if ts:
        return "Truck Settled"
    if ps:
        return "Party Settled"
    return "POD Received"


def edit_locks(trip: dict, amt: dict) -> dict:
    """Which parts of a trip can no longer be edited (LOGIC.md section 9)."""
    ts, ps = truck_settled(trip, amt), party_settled(trip, amt)
    closed = ts and ps
    return {
        "truck": ts or closed,            # truck no, truck rate, commission, truck shortage
        "party": ps or closed,            # party, party rate, party shortage
        "weights": ts or ps or closed,    # loaded/unloaded weight, freight basis
        "closed": closed,
    }


def can_cancel_trip(trip: dict, linked_voucher_count: int) -> tuple[bool, str]:
    if trip.get("is_cancelled"):
        return False, "Trip is already cancelled."
    if is_loaded(trip):
        return False, "A loaded trip cannot be cancelled. Clear the loaded weight first if it was entered by mistake."
    if linked_voucher_count > 0:
        return False, "This trip has payment/receipt/diesel entries. Cancel those entries first."
    return True, ""


# ---------- Double-entry postings ----------

def trip_posting_lines(trip: dict, amt: dict, sys_acc: dict) -> list[tuple[int, Decimal, Decimal]]:
    """Ledger lines for the auto TRIP voucher. sys_acc maps system_code -> account id.
    Returns [(account_id, debit, credit), ...]. Empty list when the trip is not loaded."""
    if not is_loaded(trip) or trip.get("is_cancelled"):
        return []
    party, owner = trip["party_id"], trip["owner_id"]
    lines = []

    def pair(dr_acc, cr_acc, amount):
        if amount > 0:
            lines.append((dr_acc, amount, ZERO))
            lines.append((cr_acc, ZERO, amount))

    pair(party, sys_acc["FREIGHT_INCOME"], amt["party_freight"])
    pair(sys_acc["LORRY_HIRE"], owner, amt["truck_hire"])
    pair(owner, sys_acc["COMMISSION_INCOME"], amt["commission"])
    pair(sys_acc["SHORTAGE_EXP"], party, amt["party_shortage"])
    pair(owner, sys_acc["SHORTAGE_REC"], amt["truck_shortage"])
    if amt.get("party_tds", ZERO) > 0:
        if "TDS_REC" not in sys_acc:
            raise ValueError("TDS account is missing. Run the latest schema.sql in Supabase once.")
        pair(sys_acc["TDS_REC"], party, amt["party_tds"])
    if amt["truck_demurrage"] > 0 or amt["party_demurrage"] > 0:
        if "DEMURRAGE_EXP" not in sys_acc or "DEMURRAGE_INC" not in sys_acc:
            raise ValueError("Demurrage accounts are missing. Run the latest schema.sql in Supabase once.")
        pair(sys_acc["DEMURRAGE_EXP"], owner, amt["truck_demurrage"])
        pair(party, sys_acc["DEMURRAGE_INC"], amt["party_demurrage"])
    return lines


def lines_balanced(lines) -> bool:
    return sum((l[1] for l in lines), ZERO) == sum((l[2] for l in lines), ZERO)


# ---------- Payment rules ----------

def check_truck_payment(trip: dict, amt: dict, purpose: str, amount: Decimal,
                        require_gr: bool, allow_over: bool) -> list[str]:
    """Returns a list of error messages; empty list = allowed."""
    errors = []
    amount = D(amount)
    if amount <= 0:
        errors.append("Amount must be more than zero.")
    if trip.get("is_cancelled"):
        errors.append("Trip is cancelled.")
    if trip.get("truck_id") is None:
        errors.append("No truck assigned to this trip.")
    if purpose == "BALANCE":
        if not is_loaded(trip):
            errors.append("Balance payment needs the trip to be loaded.")
        if not trip.get("pod_received"):
            errors.append("Balance payment is allowed only after POD is received.")
        if require_gr and not (trip.get("gr_no") or "").strip():
            errors.append("Fill the GR No. before balance payment (setting).")
    if is_loaded(trip) and amount > amt["truck_balance"] + SETTLED_TOLERANCE and not allow_over:
        errors.append(f"Amount is more than the truck balance (Rs {amt['truck_balance']}). "
                      "Tick 'Allow more than balance' if this is intended.")
    return errors


# ---------- Party receipt split (one bank credit -> many trucks) ----------

def auto_allocate(total, trips_: list[dict]) -> dict:
    """Fill the received amount into trips oldest first, up to each trip's party balance.
    Returns {trip_id: amount}. Whatever is left is 'on account'."""
    left = r2(D(total))
    out = {}
    for t in trips_:
        if left <= 0:
            break
        due = D(t["party_balance"])
        if due <= 0:
            continue
        take = min(due, left)
        out[t["id"]] = take
        left -= take
    return out


def split_summary(total, allocations) -> dict:
    total = r2(D(total))
    allocated = r2(sum((D(a) for a in allocations), ZERO))
    return {"total": total, "allocated": allocated, "on_account": total - allocated,
            "over": allocated > total}


def group_batches(rows: list[dict]) -> list[dict]:
    """Bank book: lines of one bank credit (same batch_no) become one line, like the bank statement."""
    out, idx = [], {}
    for r in rows:
        b = r.get("batch_no")
        if b and b in idx:
            g = out[idx[b]]
            g["debit"] = D(g["debit"]) + D(r["debit"])
            g["credit"] = D(g["credit"]) + D(r["credit"])
            g["trip_no"] = ", ".join(x for x in (g.get("trip_no"), r.get("trip_no")) if x)
            g["lines"] += 1
            continue
        g = dict(r, lines=1)
        if b:
            idx[b] = len(out)
        out.append(g)
    for g in out:
        if g["lines"] > 1:
            g["narration"] = f"{(g.get('narration') or '').split(' · ')[0]} · {g['lines']} trucks"
    return out


def receipt_purpose(trip: dict, amount) -> str:
    """BALANCE when this receipt clears the trip's party balance, otherwise ADVANCE."""
    if is_loaded(trip) and D(amount) >= D(trip["party_balance"]) - SETTLED_TOLERANCE:
        return "BALANCE"
    return "ADVANCE"


def route(t: dict) -> str:
    """'Jaipur → Delhi', or just 'Delhi' when From is not filled."""
    frm, to = (t.get("from_place") or "").strip(), (t.get("to_place") or "").strip()
    return f"{frm} → {to}" if frm else to


def normalize_truck_no(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def normalize_gr(s: str) -> str:
    return (s or "").strip().upper()
