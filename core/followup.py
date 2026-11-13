"""Follow-up: who owes how much for how long, and ready WhatsApp text.

- Party dues: every loaded trip with party balance left. Age counts from the day POD was given to the party;
  POD not given yet -> from the loading date (marked 'POD not given').
- POD chase: loaded trips whose POD has not come from the truck yet, oldest first.
Pure functions (no database / Streamlit) so they are easy to test.
"""
from datetime import date
from urllib.parse import quote

from core import calc

BUCKETS = [("0-15 din", 0, 15), ("16-30 din", 16, 30), ("31-60 din", 31, 60), ("60+ din", 61, 10 ** 6)]


def _inr(x) -> str:
    v = calc.r2(calc.D(x))
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = whole if frac == "00" else f"{whole}.{frac}"
    return ("-" if v < 0 else "") + out


def bucket(days: int) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= days <= hi:
            return name
    return BUCKETS[0][0]


def due_since(t: dict) -> date | None:
    """Date the party payment became due: POD handed over, else loading / booking date."""
    if t.get("pod_submitted") and t.get("pod_submit_date"):
        return t["pod_submit_date"]
    return t.get("loading_date") or t.get("booking_date")


def party_dues(trips: list[dict], today: date) -> list[dict]:
    """One row per party, oldest dues first: total, per-bucket amounts and the trip lines."""
    by = {}
    for t in trips:
        if t.get("is_cancelled") or not calc.is_loaded(t):
            continue
        bal = calc.D(t.get("party_balance"))
        if bal <= calc.SETTLED_TOLERANCE:
            continue
        since = due_since(t) or today
        days = max((today - since).days, 0)
        p = by.setdefault(t["party_id"], {"party_id": t["party_id"], "party": t.get("party_name") or "",
                                          "total": calc.ZERO, "oldest": 0, "lines": [],
                                          "buckets": {b[0]: calc.ZERO for b in BUCKETS}})
        p["total"] += bal
        p["oldest"] = max(p["oldest"], days)
        p["buckets"][bucket(days)] += bal
        p["lines"].append({"trip_id": t["id"], "trip_no": t.get("trip_no"), "truck_no": t.get("truck_no") or "",
                           "gr_no": t.get("gr_no") or "", "loading_date": t.get("loading_date"),
                           "pod_given": bool(t.get("pod_submitted")), "since": since, "days": days,
                           "balance": bal})
    out = list(by.values())
    for p in out:
        p["lines"].sort(key=lambda x: -x["days"])
    out.sort(key=lambda p: (-p["oldest"], -p["total"]))
    return out


def party_message(p: dict, company: str, only_pod_given: bool = False) -> str:
    lines = [x for x in p["lines"] if x["pod_given"] or not only_pod_given]
    rows = []
    for i, x in enumerate(lines, 1):
        d = f"{x['loading_date']:%d/%m/%y}" if x.get("loading_date") else ""
        gr = f" · GR {x['gr_no']}" if x["gr_no"] else ""
        rows.append(f"{i}. {x['truck_no']}{gr} · {d} · ₹{_inr(x['balance'])}")
    total = sum((x["balance"] for x in lines), calc.ZERO)
    return (f"Namaste {p['party']} ji,\n"
            f"Neeche diye trucks ka freight abhi baaki hai:\n" + "\n".join(rows) +
            f"\n*Kul baaki: ₹{_inr(total)}*\n"
            "Kripya jaldi payment karwa dein. Koi farak ho to bata dein.\nDhanyavaad\n— " + company)


def pod_pending(trips: list[dict], today: date, min_days: int = 0) -> list[dict]:
    """Loaded trips whose POD has not come back from the truck, oldest first."""
    out = []
    for t in trips:
        if t.get("is_cancelled") or not calc.is_loaded(t) or t.get("pod_received"):
            continue
        since = t.get("unloading_date") or t.get("loading_date") or t.get("booking_date") or today
        days = max((today - since).days, 0)
        if days >= min_days:
            out.append(dict(t, days=days))
    out.sort(key=lambda t: -t["days"])
    return out


def pod_message(t: dict, company: str) -> str:
    d = f" (load {t['loading_date']:%d/%m/%y})" if t.get("loading_date") else ""
    route = " → ".join(x for x in (t.get("from_place"), t.get("to_place")) if x)
    return (f"Namaste, gaadi {t.get('truck_no') or ''}{d} {route} ki POD abhi tak nahi mili.\n"
            f"Trip {t.get('trip_no')}" + (f" · GR {t['gr_no']}" if t.get("gr_no") else "") +
            "\nKripya POD jaldi bhej dein, uske baad hi balance payment hogi.\n— " + company)


def wa_link(phone: str | None, text: str) -> str:
    """wa.me link with the text ready. 10-digit Indian number -> opens that chat; else WhatsApp asks whom."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    base = f"https://wa.me/91{digits}" if len(digits) == 10 else "https://wa.me/"
    return f"{base}?text={quote(text)}"
