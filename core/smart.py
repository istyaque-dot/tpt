"""Less typing: suggest New-Trip values from past trips.

Everything here only SUGGESTS (the form shows it, you can change it). Rules:
- Party      : last party sent to this destination.
- Freight    : last freight for the same party + destination.
- Truck rate : last truck rate to this destination (same party preferred).
- Commission : last commission of this truck's owner (else the last commission used).
- From / material: last ones for the same party (+ destination).
"""
from core import calc


def _same(a, b) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def suggest(history: list[dict], to_place: str = "", party_id=None, owner_id=None) -> dict:
    """history: past trips newest first (party_id, to_place, from_place, material, party_rate, truck_rate,
    commission_value, owner_id, booking_date). Returns {field: (value, reason)}."""
    out = {}
    dest = (to_place or "").strip()
    if dest and not party_id:
        h = next((x for x in history if _same(x["to_place"], dest)), None)
        if h:
            party_id = h["party_id"]
            out["party_id"] = (party_id, f"{dest} ki pichhli party")
    if dest and party_id:
        h = next((x for x in history if _same(x["to_place"], dest) and x["party_id"] == party_id
                  and calc.D(x["party_rate"]) > 0), None)
        if h:
            out["party_rate"] = (calc.D(h["party_rate"]), f"pichhli baar {h['booking_date']:%d/%m}")
            if h.get("from_place"):
                out["from_place"] = (h["from_place"], "pichhli trip")
            if h.get("material"):
                out["material"] = (h["material"], "pichhli trip")
    if dest:
        h = (next((x for x in history if _same(x["to_place"], dest) and x["party_id"] == party_id
                   and calc.D(x["truck_rate"]) > 0), None) if party_id else None) \
            or next((x for x in history if _same(x["to_place"], dest) and calc.D(x["truck_rate"]) > 0), None)
        if h:
            out["truck_rate"] = (calc.D(h["truck_rate"]), f"{dest} ka pichhla bhada {h['booking_date']:%d/%m}")
    h = (next((x for x in history if owner_id and x["owner_id"] == owner_id
               and calc.D(x["commission_value"]) > 0), None) if owner_id else None)
    if h:
        out["commission"] = (calc.D(h["commission_value"]), "is owner ka pichhla commission")
    else:
        h = next((x for x in history if calc.D(x["commission_value"]) > 0), None)
        if h:
            out["commission"] = (calc.D(h["commission_value"]), "pichhla commission")
    if party_id and "material" not in out:
        h = next((x for x in history if x["party_id"] == party_id and x.get("material")), None)
        if h:
            out["material"] = (h["material"], "is party ka pichhla maal")
    return out
