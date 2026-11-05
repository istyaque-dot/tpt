"""Read a pasted WhatsApp / SMS booking message and pull out trip details.

Works without internet or AI: patterns + matching against your own Masters (trucks, parties, places,
materials). Everything it finds only FILLS the New Trip form — you always check and press Save yourself.

Understands things like:
    RJ14AB1234 Jaipur se Delhi 25.5 ton rate 1200 gaadi bhada 1100 ABC Cement GR 4521 adv 10000
    Truck: MH 12 AB 1234 | Kota -> Indore | Wt 28 MT | Freight @1150 | Truck rate 1080
    गाड़ी 1234 जयपुर से दिल्ली 25 टन भाड़ा 1100
"""
import re
from decimal import Decimal, InvalidOperation

PLATE = re.compile(r"\b([A-Z]{2})[\s\-.]*(\d{1,2})[\s\-.]*([A-Z]{0,3})[\s\-.]*(\d{3,4})\b", re.I)
NUM = r"(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)"

WEIGHT = [re.compile(NUM + r"\s*(?:tons?|tonnes?|mts?\b|m\.t\.?|t\b|टन)", re.I),
          re.compile(r"(?:wt|weight|vajan|wajan|वजन)\s*[:=\-]?\s*" + NUM, re.I),
          # unit written first: "mt 35", "MT-35", "ton 28"
          re.compile(r"(?<![a-z])(?:mt|m\.t\.|tons?|tonnes?|टन)\s*[:=\-]?\s*" + NUM, re.I)]
POINTS = re.compile(r"(?<!\d)(\d)\s*-?\s*(?:points?|pt|पॉइंट)\b", re.I)
# truck rate needs a rate word ("gaadi bhada 1100", "truck rate 1100", "hire 1100") so that
# "gaadi 1234" (last digits of the truck number) is never read as a rate
TRUCK_RATE = re.compile(r"(?:(?:truck|gaadi|gadi|gari|lorry|गाड़ी|गाडी)\s*(?:rate|bhada|bhaada|hire|भाड़ा|भाडा)"
                        r"|bhada|bhaada|hire|भाड़ा|भाडा)\s*[:=@\-]?\s*(?:rs\.?|₹)?\s*" + NUM, re.I)
PARTY_RATE = re.compile(r"(?:party\s*rate|party|freight|fright|frieght|company\s*rate|parti)\s*(?:rate)?"
                        r"\s*[:=@\-]?\s*(?:rs\.?|₹)?\s*" + NUM, re.I)
ANY_RATE = [re.compile(r"(?:rate|@)\s*[:=\-]?\s*(?:rs\.?|₹)?\s*" + NUM, re.I),
            re.compile(NUM + r"\s*(?:/|per\s*)\s*(?:ton|tonne|mt|t\b|टन)", re.I)]
GR = re.compile(r"\b(?:gr|g\.r\.|lr|bilty|builty|बिल्टी)\s*(?:no\.?|number|#)?\s*[:=\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,15})", re.I)
ADVANCE = re.compile(r"\b(?:adv|advance|एडवांस)\s*[:=\-]?\s*(?:rs\.?|₹)?\s*" + NUM, re.I)
MOBILE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?([6-9]\d{9})(?!\d)")
DEST = re.compile(r"(?:dest|destination|to|unload|unloading|khali|खाली)\s*[:=\-]\s*([A-Za-zऀ-ॿ][\wऀ-ॿ .]{1,30})",
                  re.I)


def _num(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _plate_key(*parts) -> str:
    return "".join(parts).upper().replace(" ", "")


def _find_known(text_l: str, names: list[str]) -> list[tuple[int, str]]:
    """Known names found in the text, with their position (longest names first so 'New Delhi' beats 'Delhi')."""
    hits, taken = [], []
    for name in sorted({n for n in names if n and len(n.strip()) >= 3}, key=len, reverse=True):
        for m in re.finditer(r"(?<![\wऀ-ॿ])" + re.escape(name.lower()) + r"(?![\wऀ-ॿ])", text_l):
            if not any(a <= m.start() < b for a, b in taken):
                hits.append((m.start(), name))
                taken.append((m.start(), m.end()))
    return sorted(hits)


CARRY = ("from_place", "to_place", "party_id", "party_name", "material", "truck_rate", "party_rate")


def parse_many(text: str, trucks: list[dict] = (), parties: list[dict] = (), places: list[str] = (),
               materials: list[str] = (), default_unit: str = "TON", single_rate_for: str = "TRUCK") -> list[dict]:
    """Message with several truck numbers -> one result per truck.
    Text before the first truck no. (and details written once) is shared by all trucks; weight, GR,
    driver no., advance stay with the truck they are written next to."""
    raw = text or ""
    hits = list(PLATE.finditer(raw))
    seen, starts = set(), []
    for m in hits:
        no = _plate_key(*m.groups())
        if no not in seen:
            seen.add(no)
            starts.append(m.start())
    if len(starts) <= 1:
        r = parse(raw, trucks, parties, places, materials, default_unit, single_rate_for)
        return [r] if r.get("truck_no") or r.get("truck_id") or r.get("to_place") else []
    header = raw[:starts[0]]
    common = parse(header, trucks, parties, places, materials, default_unit, single_rate_for) if header.strip() else {}
    results, carry = [], {k: common[k] for k in CARRY if common.get(k)}
    for i, s0 in enumerate(starts):
        seg = raw[s0: starts[i + 1] if i + 1 < len(starts) else len(raw)]
        r = parse(seg, trucks, parties, places, materials, default_unit, single_rate_for)
        for k in CARRY:                       # shared details: header, else the truck before
            if not r.get(k) and carry.get(k):
                r[k] = carry[k]
        for k in CARRY:
            if r.get(k):
                carry[k] = r[k]
        r["notes"] = [n for n in r["notes"] if not n.startswith(("Not found", "Message ka rate"))]
        results.append(r)
    return results


UNIT_QTL = re.compile(r"(?:qtl|quintal|quintel|kwintal|क्विंटल|कुंतल|/\s*q\b)", re.I)
UNIT_TON = re.compile(r"(?:per\s*ton|/\s*ton|/\s*mt\b|\bpmt\b|p\.m\.t|प्रति\s*टन)", re.I)


def parse(text: str, trucks: list[dict] = (), parties: list[dict] = (), places: list[str] = (),
          materials: list[str] = (), default_unit: str = "TON", single_rate_for: str = "TRUCK") -> dict:
    """trucks: [{id, truck_no}], parties: [{id, name}]. Returns found values + notes for the user.
    Rates are always returned PER TON. A message rate is per quintal when the message says so,
    or when nothing is said and default_unit is QUINTAL (then ×10)."""
    raw = text or ""
    t = " ".join(raw.split())
    tl = t.lower()
    out: dict = {"notes": []}

    # ---- truck ----
    by_no = {x["truck_no"].upper(): x for x in trucks}
    m = PLATE.search(t)
    if m:
        no = _plate_key(*m.groups())
        out["truck_no"] = no
        if no in by_no:
            out["truck_id"] = by_no[no]["id"]
        else:
            out["notes"].append(f"Naya truck {no} — Save karte hi apne aap ban jaayega.")
    else:   # only last 4 digits written ("gaadi 1234")
        for d in re.findall(r"(?<!\d)(\d{4})(?!\d)", t):
            cands = [x for x in trucks if x["truck_no"].endswith(d)]
            if len(cands) == 1:
                out["truck_id"], out["truck_no"] = cands[0]["id"], cands[0]["truck_no"]
                break

    # ---- weight ----
    for rx in WEIGHT:
        mm = rx.search(t)
        if mm:
            w = _num(mm.group(1))
            if w and 0 < w < 100:
                out["weight"] = w
                break

    # ---- rates ----
    tr = TRUCK_RATE.search(t)
    pr = PARTY_RATE.search(t)
    if tr and 50 <= (_num(tr.group(1)) or 0) <= 50000:
        out["truck_rate"] = _num(tr.group(1))
    if pr and 50 <= (_num(pr.group(1)) or 0) <= 50000:
        out["party_rate"] = _num(pr.group(1))
    if "truck_rate" not in out or "party_rate" not in out:
        used = {m_.start(1) for m_ in (tr, pr) if m_}
        loose = []
        for rx in ANY_RATE:
            for m_ in rx.finditer(t):
                v = _num(m_.group(1))
                if v and m_.start(1) not in used and 100 <= v <= 20000 and v not in loose:
                    loose.append(v)
        if "party_rate" not in out and "truck_rate" not in out and len(loose) >= 2:
            # two rates, no labels: higher one is what the party pays
            out["party_rate"], out["truck_rate"] = max(loose[:2]), min(loose[:2])
            out["notes"].append("Two rates without labels: higher taken as freight, lower as truck rate — check.")
        elif loose:
            # one rate without a label: whose it is comes from Settings (messages carry the TRUCK rate)
            first = "truck_rate" if (single_rate_for or "TRUCK").upper() == "TRUCK" else "party_rate"
            other = "party_rate" if first == "truck_rate" else "truck_rate"
            key = first if first not in out else other
            out[key] = loose[0]
            if other not in out:
                out["notes"].append("Message ka rate " + ("TRUCK ka bhada" if key == "truck_rate" else "party freight")
                                    + " maana hai — " + ("Freight (party rate) khud likho." if key == "truck_rate"
                                                         else "Truck rate khud likho."))

    # rate unit: message word wins, else the app's default
    if "party_rate" in out or "truck_rate" in out:
        unit = "QUINTAL" if UNIT_QTL.search(t) else "TON" if UNIT_TON.search(t) else (default_unit or "TON").upper()
        if unit == "QUINTAL":
            for k in ("party_rate", "truck_rate"):
                if k in out:
                    out["notes"].append(f"{'Freight' if k == 'party_rate' else 'Truck'} ₹{out[k]}/quintal "
                                        f"= ₹{out[k] * 10}/ton")
                    out[k] = out[k] * 10
        out["rate_unit_seen"] = unit

    # ---- route ----
    # 1) "A se B" / "A to B" / "A -> B" decides direction; known places only fix the spelling / multi-word names
    known = sorted({p for p in places if p}, key=len, reverse=True)

    def _end_place(before: str) -> str:          # place that ENDS the text before "se"
        bl = before.lower().rstrip(" .")
        for k in known:
            if bl.endswith(k.lower()):
                return k
        return before.split()[-1].strip(" .").title()

    def _start_place(after: str) -> str:         # place that STARTS the text after "se"
        al = after.lower().lstrip()
        for k in known:
            if al.startswith(k.lower()) and (len(al) == len(k) or not al[len(k)].isalnum()):
                return k
        return after.split()[0].strip(" .,").title()

    for rx in (re.compile(r"(?<![\w\u0900-\u097F])(?:se|से|from)(?![\w\u0900-\u097F])", re.I),
               re.compile(r"\s*(?:->|→|—|–)\s*|\s+to\s+", re.I)):
        cm = rx.search(t)
        if cm and t[:cm.start()].strip() and t[cm.end():].strip():
            a, b = _end_place(t[:cm.start()]), _start_place(t[cm.end():])
            if not re.search(r"\d", a + b) and a.lower() != b.lower():
                out["from_place"], out["to_place"] = a, b
                break
    if "to_place" not in out:
        dm = DEST.search(t)
        if dm:
            out["to_place"] = _start_place(dm.group(1))
    if "to_place" not in out:
        found_places = _find_known(tl, list(places))
        if len(found_places) >= 2:
            out["from_place"], out["to_place"] = found_places[0][1], found_places[-1][1]
        elif len(found_places) == 1:
            out["to_place"] = found_places[0][1]

    # ---- party / material ----
    party_hits = _find_known(tl, [p["name"] for p in parties])
    if party_hits:
        name = party_hits[0][1]
        out["party_id"] = next(p["id"] for p in parties if p["name"] == name)
        out["party_name"] = name
    mats = _find_known(tl, list(materials))
    if mats:
        out["material"] = mats[0][1]

    # ---- unloading points ----
    pm = POINTS.search(t)
    if pm:
        out["points"] = int(pm.group(1))

    # ---- GR / advance / mobile ----
    g = GR.search(t)
    if g and not PLATE.fullmatch(g.group(1)):
        out["gr_no"] = g.group(1).upper()
    a = ADVANCE.search(t)
    if a and _num(a.group(1)):
        out["advance"] = _num(a.group(1))
    mob = MOBILE.search(t)
    if mob:
        out["mobile"] = mob.group(1)

    for k, label in (("truck_id", "truck"), ("to_place", "destination"), ("weight", "weight"),
                     ("truck_rate", "truck rate"), ("party_rate", "freight"), ("party_id", "party")):
        if k not in out and not (k == "truck_id" and out.get("truck_no")):
            out["notes"].append(f"Not found: {label}.")
    return out
