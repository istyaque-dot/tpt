"""AI helper (Google Gemini — free key from aistudio.google.com).

Rules:
- AI only FILLS forms / suggests. It never saves anything by itself.
- If the key is missing, the free limit is over, or anything fails, callers fall back to the old
  rule-based reader (core.parse_msg) — the app never stops working because of AI.
- Uses plain HTTPS (no extra package).

Secrets:
    GEMINI_API_KEY = "..."
    GEMINI_MODEL   = "gemini-flash-latest"   # optional
"""
import base64
import json
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

import streamlit as st

from core import calc

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = ("gemini-flash-latest", "gemini-2.5-flash")


class AIError(Exception):
    pass


def configured() -> bool:
    try:
        return bool(str(st.secrets.get("GEMINI_API_KEY", "")).strip())
    except Exception:
        return False


def _models():
    m = str(st.secrets.get("GEMINI_MODEL", "")).strip()
    return (m,) if m else DEFAULT_MODELS


def _post(model: str, body: dict, timeout: int) -> dict:
    key = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    req = urllib.request.Request(API.format(model=model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def ask_json(prompt: str, files: list[tuple[bytes, str]] = (), timeout: int = 60) -> dict | list:
    """Send prompt (+ images / PDFs) and get JSON back. Raises AIError with a plain message."""
    if not configured():
        raise AIError("AI key nahi hai (Streamlit Secrets mein GEMINI_API_KEY daalo).")
    parts = [{"text": prompt}]
    for data, mime in files:
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    last = None
    for model in _models():
        try:
            out = _post(model, body, timeout)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            if e.code == 404:                       # model name retired -> try the next one
                last = AIError(f"AI model '{model}' nahi mila.")
                continue
            if e.code == 429:
                raise AIError("AI ki aaj ki free limit khatam / bahut jaldi-jaldi request. Thodi der baad try karo.")
            if e.code in (400, 403) and ("API key" in detail or "API_KEY" in detail or "PERMISSION" in detail):
                raise AIError("GEMINI_API_KEY galat hai ya band hai.")
            raise AIError(f"AI error {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            raise AIError(f"AI tak nahi pahunch paaye: {e}")
    else:
        raise last or AIError("AI model nahi mila. Secrets mein GEMINI_MODEL badlo.")
    try:
        text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise AIError("AI ne khaali jawab diya (shayad photo saaf nahi thi).")
    return _loads(text)


def _loads(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise AIError("AI ka jawab samajh nahi aaya.")


# ---------- helpers ----------

def _num(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).replace(",", "").strip())
        return d if d > 0 else None
    except InvalidOperation:
        return None


def _match_name(name: str, options: list[dict]) -> dict | None:
    """Party/owner name from AI -> one of our Masters (exact, then 'contains', ignoring case/spaces)."""
    if not name:
        return None
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    if not k:
        return None
    for o in options:
        if re.sub(r"[^a-z0-9]", "", o["name"].lower()) == k:
            return o
    hits = [o for o in options if k in re.sub(r"[^a-z0-9]", "", o["name"].lower())
            or re.sub(r"[^a-z0-9]", "", o["name"].lower()) in k]
    return hits[0] if len(hits) == 1 else None


def _to_per_ton(rate: Decimal | None, unit: str | None) -> tuple[Decimal | None, str | None]:
    if rate is None:
        return None, None
    u = (unit or "").lower()
    if u.startswith("q"):                        # per quintal -> per ton (1 ton = 10 quintal)
        return rate * 10, f"₹{rate}/quintal = ₹{rate * 10}/ton"
    return rate, None


# ---------- 1. booking message ----------

MSG_PROMPT = """You read Indian truck-booking WhatsApp messages (Hindi / Hinglish / English) for a transport broker.
Return ONLY JSON with these keys (null when not in the message):
{"truck_no": "UP70FT7739", "from_place": "", "to_place": "", "weight_ton": 35, "rate": 175,
 "rate_unit": "ton|quintal|fixed|unknown", "rate_for": "party|truck|unknown",
 "party_rate": null, "truck_rate": null, "party_name": "", "material": "", "gr_no": "", "advance": null,
 "driver_mobile": "", "points": null, "other_trucks": [], "notes": ""}
Rules:
- truck_no: Indian vehicle number, uppercase, no spaces. If several trucks, first in truck_no, rest in other_trucks.
- "mt 35", "35 MT", "35 ton", "35 टन" = weight_ton 35. Quintal weight -> divide by 10.
- If two rates are clearly labelled (party/freight/company vs gaadi/truck/bhada/hire) fill party_rate and truck_rate.
  Otherwise put the single rate in "rate"; rate_for = "party" or "truck" ONLY if the message says so, else "unknown".
- "per qtl", "/qtl", "quintal" = rate_unit quintal. "fix", "fixed", "lumpsum" = fixed (total, not per ton).
- "2point", "2 point" = points 2 (unloading points).
- driver_mobile: 10 digits without +91.
- Never invent values.
Message:
"""


def parse_message(text: str, trucks: list[dict], parties: list[dict], default_unit: str = "TON",
                  single_rate_for: str = "TRUCK") -> dict:
    """Same output shape as core.parse_msg.parse (so New Trip can use either)."""
    r = ask_json(MSG_PROMPT + text.strip(), timeout=40)
    if isinstance(r, list):
        r = r[0] if r else {}
    return _map_one(r, trucks, parties, default_unit, single_rate_for)


def _map_one(r: dict, trucks: list[dict], parties: list[dict], default_unit: str = "TON",
             single_rate_for: str = "TRUCK") -> dict:
    """One AI trip (raw JSON) -> form values (rates per ton, truck/party matched to Masters)."""
    out: dict = {"notes": [], "source": "AI"}
    tn = calc.normalize_truck_no(r.get("truck_no") or "")
    if tn:
        out["truck_no"] = tn
        hit = next((t for t in trucks if t["truck_no"] == tn), None)
        if hit:
            out["truck_id"] = hit["id"]
        else:
            out["notes"].append(f"Naya truck {tn} — Save karte hi apne aap ban jaayega.")
    for k in ("from_place", "to_place", "material", "gr_no"):
        v = (r.get(k) or "").strip() if isinstance(r.get(k), str) else r.get(k)
        if v:
            out[k] = str(v).strip().title() if k.endswith("place") and str(v).islower() else str(v).strip()
    w = _num(r.get("weight_ton"))
    if w and w < 100:
        out["weight"] = w
    unit = r.get("rate_unit")
    if (unit or "unknown").lower() in ("unknown", "", "none") and (default_unit or "").upper() == "QUINTAL":
        unit = "quintal"
    for k in ("party_rate", "truck_rate"):
        v, note = _to_per_ton(_num(r.get(k)), unit)
        if v:
            out[k] = v
            if note:
                out["notes"].append(note)
    one, note = _to_per_ton(_num(r.get("rate")), unit)
    if one and (unit or "").lower() == "fixed":
        out["notes"].append(f"Rate ₹{one} fixed (poori trip) likha hai — weight se bhaag karke per ton bharo.")
        one = None
    if one:
        if note:
            out["notes"].append(note)
        who = (r.get("rate_for") or "").lower()
        if who not in ("party", "truck"):
            who = "truck" if (single_rate_for or "TRUCK").upper() == "TRUCK" else "party"
        first = f"{who}_rate"
        other = "party_rate" if first == "truck_rate" else "truck_rate"
        if first not in out:
            out[first] = one
        elif other not in out:
            out[other] = one
        if other not in out:
            out["notes"].append("Message ka rate " + ("TRUCK ka bhada" if first == "truck_rate" else "party freight")
                                + " maana hai — " + ("Freight (party rate) khud likho." if first == "truck_rate"
                                                     else "Truck rate khud likho."))
    p = _match_name(r.get("party_name") or "", parties)
    if p:
        out["party_id"], out["party_name"] = p["id"], p["name"]
    elif r.get("party_name"):
        out["notes"].append(f"Party '{r['party_name']}' Masters mein nahi mili — chuno ya ➕ se jodo.")
    a = _num(r.get("advance"))
    if a:
        out["advance"] = a
    mob = re.sub(r"\D", "", str(r.get("driver_mobile") or ""))[-10:]
    if len(mob) == 10:
        out["mobile"] = mob
    if r.get("points"):
        try:
            out["points"] = int(r["points"])
        except (TypeError, ValueError):
            pass
    others = [calc.normalize_truck_no(x) for x in (r.get("other_trucks") or []) if x]
    if others:
        out["notes"].append(f"Message mein aur trucks bhi hain: {', '.join(others)} — unki alag trip banao.")
    if r.get("notes"):
        out["notes"].append(f"AI: {r['notes']}")
    for k, label in (("to_place", "destination"), ("weight", "weight"), ("truck_rate", "truck rate"),
                     ("party_rate", "freight"), ("party_id", "party")):
        if k not in out:
            out["notes"].append(f"Not found: {label}.")
    return out


def parse_message_safe(text: str, trucks, parties, places, materials, default_unit: str = "TON",
                       single_rate_for: str = "TRUCK") -> dict:
    """AI first; on any problem use the rule-based reader. Rule results fill gaps AI left.
    All rates come back per TON."""
    from core import parse_msg
    rules = parse_msg.parse(text, trucks, parties, places, materials, default_unit=default_unit,
                            single_rate_for=single_rate_for)
    if not configured():
        rules["source"] = "rules"
        return rules
    try:
        ai = parse_message(text, trucks, parties, default_unit, single_rate_for)
    except AIError as e:
        rules["source"] = "rules"
        rules["notes"].insert(0, f"⚠️ {e} — purane tareeke se padha.")
        return rules
    for k, v in rules.items():
        if k not in ("notes", "source") and k not in ai and v:
            ai[k] = v
    ai["notes"] = [n for n in ai["notes"] if not n.startswith("Not found")]
    for k, label in (("to_place", "destination"), ("weight", "weight"), ("truck_rate", "truck rate"),
                     ("party_rate", "freight"), ("party_id", "party")):
        if k not in ai:
            ai["notes"].append(f"Not found: {label}.")
    return ai


# ---------- 1b. one message, many trucks ----------

MULTI_PROMPT = """You read an Indian truck-booking WhatsApp message that may list SEVERAL trucks.
Return ONLY JSON: {"trips": [ {one object per truck, same keys as below} ]}
Keys per truck (null when not in the message):
{"truck_no": "", "from_place": "", "to_place": "", "weight_ton": null, "rate": null,
 "rate_unit": "ton|quintal|fixed|unknown", "rate_for": "party|truck|unknown", "party_rate": null, "truck_rate": null,
 "party_name": "", "material": "", "gr_no": "", "advance": null, "driver_mobile": "", "points": null, "notes": ""}
Rules:
- One object per truck number. Details written once for all trucks (route, rate, party, material) go into EVERY truck.
- Details written next to one truck (its weight, driver no., GR, advance) go only to that truck.
- truck_no uppercase without spaces. "mt 35", "35 MT", "35 ton" = weight_ton 35.
- rate_for = "party" or "truck" ONLY if the message says so, else "unknown". "qtl"/"quintal" = rate_unit quintal.
- Never invent values.
Message:
"""


def parse_many(text: str, trucks, parties, default_unit: str = "TON", single_rate_for: str = "TRUCK") -> list[dict]:
    r = ask_json(MULTI_PROMPT + text.strip(), timeout=60)
    items = r.get("trips") if isinstance(r, dict) else r
    out = []
    for x in items or []:
        if isinstance(x, dict) and calc.normalize_truck_no(x.get("truck_no") or ""):
            m = _map_one(x, trucks, parties, default_unit, single_rate_for)
            m["notes"] = [n for n in m["notes"] if not n.startswith(("Not found", "Message ka rate"))]
            out.append(m)
    return out


def parse_many_safe(text: str, trucks, parties, places, materials, default_unit: str = "TON",
                    single_rate_for: str = "TRUCK") -> list[dict]:
    """All trucks of a message (AI first, rule reader as backup and gap-filler). Rates per TON."""
    from core import parse_msg
    rules = parse_msg.parse_many(text, trucks, parties, places, materials, default_unit=default_unit,
                                 single_rate_for=single_rate_for)
    if not configured():
        return rules
    try:
        found = parse_many(text, trucks, parties, default_unit, single_rate_for)
    except AIError as e:
        if rules:
            rules[0]["notes"].insert(0, f"⚠️ {e} — purane tareeke se padha.")
        return rules
    if not found:
        return rules
    by_truck = {r_.get("truck_no"): r_ for r_ in rules}
    for f in found:
        for k, v in (by_truck.get(f.get("truck_no")) or {}).items():
            if k not in ("notes", "source") and k not in f and v:
                f[k] = v
    return found


# ---------- 2. GR / POD photo ----------

DOC_PROMPT = """This is a photo/scan of an Indian transport document (GR / LR / bilty, or a POD / delivery receipt).
Return ONLY JSON (null when not visible):
{"doc_type": "GR|POD|OTHER", "gr_no": "", "truck_no": "", "date": "DD/MM/YYYY", "from_place": "", "to_place": "",
 "consignor": "", "consignee": "", "material": "", "weight_ton": null, "unloaded_weight_ton": null,
 "shortage_note": "", "received_stamp": true, "notes": ""}
- GR No. may be handwritten in a box at the top right — read it carefully.
- truck_no uppercase without spaces. Weights in tons (kg/1000, quintal/10).
- received_stamp = true if the consignee's receiving stamp / signature is present.
- Never invent values."""


def _prepare(data: bytes, mime: str) -> tuple[bytes, str]:
    if (mime or "").startswith("image/"):
        from core import drive
        try:
            return drive.compress_image(data, max_side=1600, quality=80), "image/jpeg"
        except Exception:
            pass
    return data, mime or "application/octet-stream"


def read_document(data: bytes, mime: str) -> dict:
    d, m = _prepare(data, mime)
    r = ask_json(DOC_PROMPT, [(d, m)], timeout=90)
    if isinstance(r, list):
        r = r[0] if r else {}
    r["truck_no"] = calc.normalize_truck_no(r.get("truck_no") or "") or None
    r["gr_no"] = calc.normalize_gr(r.get("gr_no") or "") or None
    for k in ("weight_ton", "unloaded_weight_ton"):
        r[k] = _num(r.get(k))
    return r


# ---------- 3. scanned POD bundle: page -> GR ----------

BUNDLE_PROMPT = """This PDF is many POD / GR pages scanned together. On every page a GR number is handwritten
(usually top-right, in a box). For EACH page return its GR number.
Return ONLY JSON: [{"page": 1, "gr_no": "4521", "sure": true}, ...] — one item per page, pages counted from 1.
- If a page has no GR number written (blank back side, continuation page), gr_no = "" .
- sure = false when the handwriting is unclear.
- Never invent numbers."""


def map_bundle(pdf: bytes) -> list[dict]:
    r = ask_json(BUNDLE_PROMPT, [(pdf, "application/pdf")], timeout=180)
    if isinstance(r, dict):
        r = r.get("pages") or r.get("items") or []
    out = []
    for x in r:
        try:
            out.append({"page": int(x.get("page")), "gr_no": calc.normalize_gr(x.get("gr_no") or ""),
                        "sure": bool(x.get("sure", True))})
        except (TypeError, ValueError, AttributeError):
            continue
    return sorted(out, key=lambda x: x["page"])


def group_pages(mapping: list[dict], n_pages: int) -> list[dict]:
    """Pages without a GR number belong to the GR of the page before them (same POD bundle)."""
    by_page = {m["page"]: m for m in mapping}
    groups, cur = [], None
    for p in range(1, n_pages + 1):
        m = by_page.get(p, {"gr_no": "", "sure": False})
        if m["gr_no"]:
            if cur and cur["gr_no"] == m["gr_no"]:
                cur["pages"].append(p)
                cur["sure"] = cur["sure"] and m["sure"]
            else:
                cur = {"gr_no": m["gr_no"], "pages": [p], "sure": m["sure"]}
                groups.append(cur)
        elif cur:
            cur["pages"].append(p)
        else:
            cur = {"gr_no": "", "pages": [p], "sure": False}
            groups.append(cur)
    return groups


def split_pdf(pdf: bytes, pages: list[int]) -> bytes:
    import io

    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf))
    w = PdfWriter()
    for p in pages:
        w.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test() -> str:
    r = ask_json('Reply with JSON {"ok": true, "hindi": "<say namaste in Hindi>"}', timeout=30)
    return str(r)
