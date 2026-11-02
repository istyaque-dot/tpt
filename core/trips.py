"""Trip + voucher database operations. All money maths comes from core.calc."""

from core import calc, clock, db

TRIP_SELECT = """
select t.*,
       p.name  as party_name,
       o.name  as owner_name,
       tr.truck_no, tr.driver_name, tr.driver_mobile,
       coalesce(a.party_received, 0) as party_received,
       coalesce(a.truck_paid, 0)     as truck_paid,
       coalesce(a.diesel, 0)         as diesel,
       coalesce(a.voucher_count, 0)  as voucher_count,
       coalesce(d.gr_docs, 0)        as gr_docs,
       coalesce(d.pod_docs, 0)       as pod_docs,
       coalesce(d.all_docs, 0)       as all_docs
from trips t
join accounts p       on p.id = t.party_id
left join trucks tr   on tr.id = t.truck_id
left join accounts o  on o.id = t.owner_id
left join (
    select trip_id,
           sum(amount) filter (where v_type = 'RECEIPT') as party_received,
           sum(amount) filter (where v_type = 'PAYMENT') as truck_paid,
           sum(amount) filter (where v_type = 'DIESEL')  as diesel,
           count(*)    filter (where v_type <> 'TRIP')   as voucher_count
    from vouchers
    where not is_cancelled and trip_id is not null
    group by trip_id
) a on a.trip_id = t.id
left join (
    select trip_id,
           count(*) filter (where doc_type = 'GR')  as gr_docs,
           count(*) filter (where doc_type = 'POD') as pod_docs,
           count(*) as all_docs
    from trip_documents where not is_deleted
    group by trip_id
) d on d.trip_id = t.id
"""


def _enrich(row: dict) -> dict:
    amt = calc.trip_amounts(row)
    row.update(amt)
    row["status"] = calc.trip_status(row, amt)
    row["locks"] = calc.edit_locks(row, amt)
    return row


def load_trips(where: str = "true", params=None, order: str = "t.id desc") -> list[dict]:
    rows = db.query(f"{TRIP_SELECT} where {where} order by {order}", params)
    return [_enrich(r) for r in rows]


def get_trip(trip_id: int, cur=None) -> dict | None:
    sql = f"{TRIP_SELECT} where t.id = %s"
    if cur is None:
        rows = db.query(sql, (trip_id,))
    else:
        cur.execute(sql, (trip_id,))
        rows = [dict(r) for r in cur.fetchall()]
    return _enrich(rows[0]) if rows else None


QUICK_FILTERS = {
    "All open": lambda r: r["status"] not in ("Closed", "Cancelled"),
    "POD pending": lambda r: r["status"] in ("Loaded", "Unloaded"),
    "Truck to pay": lambda r: calc.is_loaded(r) and not calc.truck_settled(r, r)
                              and calc.D(r["truck_balance"]) > calc.SETTLED_TOLERANCE,
    "Party to receive": lambda r: calc.is_loaded(r) and calc.D(r["party_balance"]) > calc.SETTLED_TOLERANCE,
    "GR pending": lambda r: not r.get("gr_no") and not r["is_cancelled"],
    "POD to submit": lambda r: bool(r["pod_received"]) and not r.get("pod_submitted")
                               and not calc.party_settled(r, r),
    "All": lambda r: True,
}


def find_trips(q: str, quick: str = "All", limit: int = 40) -> list[dict]:
    """One search box for everything: Trip No., truck no. (even last 4 digits), GR No., party,
    owner, driver mobile. Blank search = latest trips."""
    q = (q or "").strip()
    where, params = "true", []
    if q:
        key = calc.normalize_truck_no(q)          # letters+digits only, uppercase
        like = f"%{q}%"
        where = ("(t.trip_no ilike %s or tr.truck_no like %s "
                 " or regexp_replace(upper(coalesce(t.gr_no, '')), '[^A-Z0-9]', '', 'g') like %s "
                 " or p.name ilike %s or o.name ilike %s or tr.driver_mobile like %s)")
        params = [like, f"%{key}%", f"%{key}%", like, like, like]
        if q.isdigit():                            # "12" also finds T-0012
            where = f"({where} or t.id = %s)"
            params.append(int(q))
    if quick == "All":
        rows = load_trips(where, params, f"t.id desc limit {int(limit)}")
    else:   # filters need every open trip, not just the latest few
        rows = load_trips(f"{where} and not t.is_cancelled", params, "t.id desc")
    rows = [r for r in rows if QUICK_FILTERS[quick](r)]
    return rows[:limit]


def trip_label(t: dict) -> str:
    parts = [t["trip_no"]]
    if t.get("truck_no"):
        parts.append(t["truck_no"])
    parts.append(f"GR {t['gr_no']}" if t.get("gr_no") else "GR pending")
    parts.append(t.get("party_name") or "")
    parts.append(calc.route(t))
    return " | ".join(parts)


# ---------- Posting ----------

def repost_trip(cur, trip_id: int):
    """Delete the auto TRIP voucher of this trip and create it again from current trip data."""
    trip = get_trip(trip_id, cur)
    cur.execute("delete from vouchers where trip_id = %s and v_type = 'TRIP'", (trip_id,))
    lines = calc.trip_posting_lines(trip, trip, db.system_accounts())
    if not lines:
        return
    if not calc.lines_balanced(lines):
        raise ValueError("Internal error: trip posting is not balanced.")
    v_date = trip.get("loading_date") or trip.get("booking_date") or clock.today()
    cur.execute(
        "insert into vouchers (v_date, v_type, purpose, trip_id, amount, narration) "
        "values (%s, 'TRIP', 'TRIP_BILL', %s, %s, %s) returning id",
        (v_date, trip_id, trip["party_freight"],
         f"Trip {trip['trip_no']} {calc.route(trip)} "
         f"{trip['billing_weight']} T"))
    vid = cur.fetchone()["id"]
    for acc, dr, cr in lines:
        cur.execute("insert into ledger_entries (voucher_id, account_id, debit, credit) "
                    "values (%s, %s, %s, %s)", (vid, acc, dr, cr))


# ---------- Trips ----------

TRIP_FIELDS = ["booking_date", "party_id", "from_place", "to_place", "material", "party_rate",
               "approx_weight", "truck_id", "truck_rate", "loaded_weight", "loading_date",
               "unloaded_weight", "unloading_date", "pod_received", "pod_date", "gr_no", "gr_date",
               "freight_basis", "commission_type", "commission_value", "party_shortage_amt",
               "truck_shortage_amt", "remarks", "truck_demurrage_amt", "party_demurrage_amt", "demurrage_days",
               "pod_submitted", "pod_submit_date", "pod_submit_mode", "pod_submit_ref", "party_demurrage_days",
               "tds_rate"]


def _clean(data: dict) -> dict:
    data = {k: v for k, v in data.items() if k in TRIP_FIELDS}
    if "gr_no" in data:
        data["gr_no"] = calc.normalize_gr(data["gr_no"]) or None
    return data


def find_truck(text: str, trucks: list[dict]) -> dict | None:
    """Typed truck no. -> existing truck. Full number, or last 3-4 digits when only one truck matches."""
    key = calc.normalize_truck_no(text)
    if not key:
        return None
    for t in trucks:
        if t["truck_no"] == key:
            return t
    if key.isdigit() and len(key) >= 3:
        hits = [t for t in trucks if t["truck_no"].endswith(key)]
        if len(hits) == 1:
            return hits[0]
    return None


def resolve_truck(cur, truck_no: str, owner_name: str | None) -> int:
    """Truck id for a typed truck no.; creates the truck (and its owner) the first time it is used.
    Owner left blank -> the owner account is named after the truck itself."""
    key = calc.normalize_truck_no(truck_no)
    cur.execute("select id from trucks where truck_no = %s", (key,))
    row = cur.fetchone()
    if row:
        return row["id"]
    name = (owner_name or "").strip() or key
    cur.execute("insert into accounts (name, acc_type) values (%s, 'OWNER') "
                "on conflict (acc_type, name) do update set active = true returning id", (name,))
    owner_id = cur.fetchone()["id"]
    cur.execute("insert into trucks (truck_no, owner_id) values (%s, %s) returning id", (key, owner_id))
    return cur.fetchone()["id"]


def looks_like_truck_no(text: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{3,4}", calc.normalize_truck_no(text)))


def create_trip(data: dict, new_truck_no: str | None = None, new_owner: str | None = None) -> int:
    data = _clean(data)
    with db.tx() as cur:
        if new_truck_no and not data.get("truck_id"):
            data["truck_id"] = resolve_truck(cur, new_truck_no, new_owner)
        if data.get("truck_id"):
            cur.execute("select owner_id from trucks where id=%s", (data["truck_id"],))
            data["owner_id"] = cur.fetchone()["owner_id"]
        cols = list(data.keys())
        cur.execute(
            f"insert into trips ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
            "returning id", [data[c] for c in cols])
        tid = cur.fetchone()["id"]
        audit(cur, "trip", tid, "create", {})
        db.add_lookup(cur, "PLACE", data.get("from_place"))
        db.add_lookup(cur, "PLACE", data.get("to_place"))
        db.add_lookup(cur, "MATERIAL", data.get("material"))
        repost_trip(cur, tid)
    return tid


def update_trip(trip_id: int, data: dict, new_truck_no: str | None = None, new_owner: str | None = None):
    data = _clean(data)
    with db.tx() as cur:
        if new_truck_no:
            data["truck_id"] = resolve_truck(cur, new_truck_no, new_owner)
        cur.execute("select * from trips where id=%s for update", (trip_id,))
        old = dict(cur.fetchone())
        if "truck_id" in data:
            if data["truck_id"]:
                cur.execute("select owner_id from trucks where id=%s", (data["truck_id"],))
                new_owner = cur.fetchone()["owner_id"]
                # keep the owner snapshot unless the truck itself changed
                data["owner_id"] = (old["owner_id"] if old["truck_id"] == data["truck_id"] and old["owner_id"]
                                    else new_owner)
            else:
                data["owner_id"] = None
        # Money already given/received is in the old owner's / party's ledger. Moving the trip to someone
        # else would split the hisaab between two ledgers, so it is blocked until those entries are cancelled.
        cur.execute("select v_type, count(*) n from vouchers where trip_id=%s and not is_cancelled "
                    "and v_type in ('PAYMENT','DIESEL','RECEIPT') group by v_type", (trip_id,))
        used = {r["v_type"]: r["n"] for r in cur.fetchall()}
        if "owner_id" in data and data["owner_id"] != old["owner_id"] and (used.get("PAYMENT") or used.get("DIESEL")):
            raise ValueError("This trip already has truck advance/diesel entries for the old truck owner. "
                             "Cancel those entries first, then change the truck.")
        if "party_id" in data and data["party_id"] != old["party_id"] and used.get("RECEIPT"):
            raise ValueError("This trip already has party receipts. Cancel them first, then change the party.")
        data = {k: v for k, v in data.items() if not _same(old.get(k), v)}
        if not data:
            return
        sets = ", ".join(f"{k} = %s" for k in data)
        cur.execute(f"update trips set {sets}, updated_at = now() where id = %s",
                    list(data.values()) + [trip_id])
        for k, kind in (("from_place", "PLACE"), ("to_place", "PLACE"), ("material", "MATERIAL")):
            if data.get(k):
                db.add_lookup(cur, kind, data[k])
        repost_trip(cur, trip_id)
        audit(cur, "trip", trip_id, "edit", {k: [_js(old.get(k)), _js(v)] for k, v in data.items()})


def _same(a, b) -> bool:
    if a is None or b is None:
        return (a is None or a == "") and (b is None or b == "")
    if isinstance(a, (int, float, calc.Decimal)) and not isinstance(a, bool):
        try:
            return calc.D(a) == calc.D(b)
        except Exception:
            return False
    return a == b


def _js(v):
    return v if v is None or isinstance(v, (bool, int, str)) else str(v)


def audit(cur, entity: str, entity_id, action: str, details: dict | None = None):
    """Edit history: who changed what and when (Masters → nothing is lost silently)."""
    import json
    import streamlit as st
    try:
        user = st.session_state.get("user", "admin")
    except Exception:
        user = "admin"
    # savepoint: if audit_log does not exist yet (old database), the real save still goes through
    cur.execute("savepoint audit_sp")
    try:
        cur.execute("insert into audit_log (at, username, entity, entity_id, action, details) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    (clock.now(), user, entity, entity_id, action, json.dumps(details or {}, ensure_ascii=False)))
        cur.execute("release savepoint audit_sp")
    except Exception:
        cur.execute("rollback to savepoint audit_sp")


def cancel_trip(trip_id: int, reason: str):
    with db.tx() as cur:
        t = get_trip(trip_id, cur)
        ok, msg = calc.can_cancel_trip(t, int(t["voucher_count"]))
        if not ok:
            raise ValueError(msg)
        cur.execute("update trips set is_cancelled = true, cancel_reason = %s, updated_at = now() "
                    "where id = %s", (reason, trip_id))
        repost_trip(cur, trip_id)
        audit(cur, "trip", trip_id, "cancel", {"reason": reason})


# ---------- Vouchers ----------

def add_voucher(cur, *, v_date, v_type, amount, dr_account, cr_account, purpose=None,
                trip_id=None, ref_no=None, narration=None, litres=None, rate=None, batch_no=None) -> int:
    amount = calc.r2(calc.D(amount))
    if amount <= 0:
        raise ValueError("Amount must be more than zero.")
    if dr_account == cr_account:
        raise ValueError("Debit and credit account cannot be the same.")
    cur.execute(
        "insert into vouchers (v_date, v_type, purpose, trip_id, amount, litres, rate, ref_no, narration, batch_no) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
        (v_date, v_type, purpose, trip_id, amount, litres, rate, ref_no or None, narration or None, batch_no))
    vid = cur.fetchone()["id"]
    cur.execute("insert into ledger_entries (voucher_id, account_id, debit, credit) values "
                "(%s, %s, %s, 0), (%s, %s, 0, %s)",
                (vid, dr_account, amount, vid, cr_account, amount))
    audit(cur, "voucher", vid, "create", {"type": v_type, "purpose": purpose, "amount": str(amount),
                                          "trip_id": trip_id})
    return vid


def cancel_voucher(voucher_id: int, reason: str):
    with db.tx() as cur:
        cur.execute("select v_type, is_cancelled, batch_no from vouchers where id=%s", (voucher_id,))
        v = cur.fetchone()
        if not v:
            raise ValueError("Entry not found.")
        if v["v_type"] == "TRIP":
            raise ValueError("Trip bill entries change automatically when the trip is edited.")
        if v["is_cancelled"]:
            raise ValueError("Entry is already cancelled.")
        audit(cur, "voucher", voucher_id, "cancel", {"reason": reason, "batch": v.get("batch_no")})
        if v.get("batch_no"):
            # one bank credit split over trucks is cancelled together, so the bank stays right
            cur.execute("update vouchers set is_cancelled = true, cancel_reason = %s, cancelled_at = now() "
                        "where batch_no = %s and not is_cancelled", (reason, v["batch_no"]))
        else:
            cur.execute("update vouchers set is_cancelled = true, cancel_reason = %s, cancelled_at = now() "
                        "where id = %s", (reason, voucher_id))


def open_trips_for(party_id=None, owner_id=None) -> list[dict]:
    """Non-cancelled trips of a party / truck owner that are not fully settled on that side."""
    if party_id:
        rows = load_trips("not t.is_cancelled and t.party_id = %s", (party_id,), "t.id")
        return [r for r in rows if not calc.party_settled(r, r)]
    rows = load_trips("not t.is_cancelled and t.owner_id = %s", (owner_id,), "t.id")
    return [r for r in rows if not calc.truck_settled(r, r)]


VOUCHER_LIST_SQL = """
select v.id, v.v_date, v.v_type, v.purpose, v.amount, v.litres, v.rate, v.ref_no, v.narration,
       v.is_cancelled, v.cancel_reason, v.batch_no, t.trip_no, t.gr_no,
       (select string_agg(a.name, ', ') from ledger_entries e join accounts a on a.id=e.account_id
         where e.voucher_id=v.id and e.debit>0) as debit_account,
       (select string_agg(a.name, ', ') from ledger_entries e join accounts a on a.id=e.account_id
         where e.voucher_id=v.id and e.credit>0) as credit_account
from vouchers v left join trips t on t.id = v.trip_id
"""
