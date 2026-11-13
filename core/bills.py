"""Party freight bill (invoice) for one or many trips.

Rules
- A bill only PRINTS what is already in the books: the freight was posted to the party when the trip was
  loaded. So a normal bill (GST 'NONE' or 'RCM') makes no ledger entry.
- GST 'RCM' (reverse charge): party pays GST to the government itself; the bill only carries the note.
- GST 'FORWARD': GST is added to the bill -> one entry Party Dr / GST Payable Cr (not linked to a trip,
  so trip-wise balances stay freight-only; the GST part shows in the party ledger).
- One trip can be on one live bill only. Cancelling a bill frees its trips and cancels its GST entry.
- Bill No.: <FY>/<number>, e.g. 26-27/001 (April to March).
"""
import io
import json
from datetime import date

from core import calc, clock, db, trips

D, ZERO = calc.D, calc.ZERO
GST_MODES = {"NONE": "GST nahi", "RCM": "GST — party bharegi (RCM)", "FORWARD": "GST bill mein jodo (forward)"}


def fy_of(d: date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y % 100:02d}-{(y + 1) % 100:02d}"


def trip_line(t: dict) -> dict:
    """What one trip puts on the bill (freight + party demurrage; shortage is the party's own deduction)."""
    return {"trip_id": t["id"], "trip_no": t["trip_no"], "date": str(t.get("loading_date") or t.get("booking_date")),
            "truck_no": t.get("truck_no") or "", "gr_no": t.get("gr_no") or "",
            "from": t.get("from_place") or "", "to": t.get("to_place") or "", "material": t.get("material") or "",
            "weight": str(D(t["billing_weight"])), "rate": str(D(t["party_rate"])),
            "freight": str(D(t["party_freight"])), "demurrage": str(D(t["party_demurrage"])),
            "amount": str(D(t["party_freight"]) + D(t["party_demurrage"])),
            "received": str(D(t["party_received"]))}


def totals(lines: list[dict], gst_mode: str, gst_rate, same_state: bool = True) -> dict:
    freight = calc.r2(sum((D(x["amount"]) for x in lines), ZERO))
    rate = D(gst_rate) if gst_mode in ("RCM", "FORWARD") else ZERO
    gst = calc.r2(freight * rate / 100) if gst_mode == "FORWARD" else ZERO
    half = calc.r2(gst / 2)
    return {"freight": freight, "gst_rate": rate, "gst": gst,
            "cgst": half if same_state else ZERO, "sgst": gst - half if same_state else ZERO,
            "igst": ZERO if same_state else gst, "total": freight + gst,
            "rcm_gst": calc.r2(freight * rate / 100) if gst_mode == "RCM" else ZERO,
            "received": calc.r2(sum((D(x.get("received")) for x in lines), ZERO))}


def same_state(gstin_a: str, gstin_b: str) -> bool:
    a, b = (gstin_a or "").strip()[:2], (gstin_b or "").strip()[:2]
    return not (a.isdigit() and b.isdigit()) or a == b


def billable_trips(party_id: int) -> list[dict]:
    """Loaded, not cancelled trips of this party that are not on a live bill yet (oldest first)."""
    rows = trips.load_trips("not t.is_cancelled and t.party_id = %s and t.bill_id is null", (party_id,),
                            "coalesce(t.loading_date, t.booking_date), t.id")
    return [r for r in rows if calc.is_loaded(r) and r["party_freight"] > 0]


def create(party_id: int, trip_ids: list[int], bill_date: date, gst_mode: str, gst_rate) -> dict:
    if not trip_ids:
        raise ValueError("Kam se kam ek trip chuno.")
    if gst_mode not in GST_MODES:
        raise ValueError("GST type galat hai.")
    party = db.one("select * from accounts where id = %s", (party_id,))
    with db.tx() as cur:
        cur.execute("select id from trips where id = any(%s) and (bill_id is not null or party_id <> %s "
                    "or is_cancelled) for update", (list(trip_ids), party_id))
        if cur.fetchall():
            raise ValueError("Koi trip pehle se kisi bill mein hai (ya doosri party ki hai). Page refresh karo.")
        lines = []
        for tid in trip_ids:
            t = trips.get_trip(tid, cur)
            if not calc.is_loaded(t):
                raise ValueError(f"{t['trip_no']} abhi load nahi hui — bill nahi ban sakta.")
            lines.append(trip_line(t))
        lines.sort(key=lambda x: (x["date"], x["trip_no"]))
        tot = totals(lines, gst_mode, gst_rate, same_state(db.setting("company_gstin", ""), party.get("gstin")))
        fy = fy_of(bill_date)
        cur.execute("lock table bills in share row exclusive mode")          # no two bills get one number
        cur.execute("select coalesce(max(seq), 0) + 1 n from bills where fy = %s", (fy,))
        seq = cur.fetchone()["n"]
        bill_no = f"{fy}/{seq:03d}"
        vid = None
        if tot["gst"] > 0:
            gst_acc = db.system_accounts().get("GST_PAYABLE")
            if not gst_acc:
                raise ValueError("GST Payable account nahi mila — schema.sql ek baar chalao.")
            vid = trips.add_voucher(cur, v_date=bill_date, v_type="OTHER", purpose="BILL_GST", amount=tot["gst"],
                                    dr_account=party_id, cr_account=gst_acc, ref_no=bill_no,
                                    narration=f"GST {tot['gst_rate'].normalize():f}% on bill {bill_no}")
        cur.execute("insert into bills (fy, seq, bill_no, bill_date, party_id, freight, gst_mode, gst_rate, "
                    "gst_amt, total, lines, voucher_id) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (fy, seq, bill_no, bill_date, party_id, tot["freight"], gst_mode, tot["gst_rate"], tot["gst"],
                     tot["total"], json.dumps(lines), vid))
        bid = cur.fetchone()["id"]
        cur.execute("update trips set bill_id = %s where id = any(%s)", (bid, list(trip_ids)))
        trips.audit(cur, "bill", bid, "create", {"bill_no": bill_no, "trips": list(trip_ids),
                                                 "total": str(tot["total"])})
    return get(bid)


def cancel(bill_id: int, reason: str):
    with db.tx() as cur:
        cur.execute("select * from bills where id = %s for update", (bill_id,))
        b = cur.fetchone()
        if not b or b["is_cancelled"]:
            raise ValueError("Bill nahi mila ya pehle se cancel hai.")
        cur.execute("update bills set is_cancelled = true, cancel_reason = %s where id = %s", (reason, bill_id))
        cur.execute("update trips set bill_id = null where bill_id = %s", (bill_id,))
        if b["voucher_id"]:
            cur.execute("update vouchers set is_cancelled = true, cancel_reason = %s, cancelled_at = now() "
                        "where id = %s", (f"Bill {b['bill_no']} cancelled", b["voucher_id"]))
        trips.audit(cur, "bill", bill_id, "cancel", {"reason": reason})


def get(bill_id: int) -> dict | None:
    b = db.one("select b.*, a.name party_name, a.address party_address, a.gstin party_gstin, a.mobile party_mobile "
               "from bills b join accounts a on a.id = b.party_id where b.id = %s", (bill_id,))
    if b and isinstance(b.get("lines"), str):
        b["lines"] = json.loads(b["lines"])
    return b


def list_for(party_id: int | None = None, limit: int = 50) -> list[dict]:
    where, params = ("b.party_id = %s", (party_id,)) if party_id else ("true", None)
    rows = db.query(f"select b.*, a.name party_name from bills b join accounts a on a.id = b.party_id "
                    f"where {where} order by b.bill_date desc, b.id desc limit {int(limit)}", params)
    for r in rows:
        if isinstance(r.get("lines"), str):
            r["lines"] = json.loads(r["lines"])
    return rows


def changed_since_bill(b: dict) -> list[str]:
    """Trips whose freight / demurrage changed after the bill was made (bill should be re-made)."""
    out = []
    for x in b["lines"]:
        t = trips.get_trip(x["trip_id"])
        if t and D(t["party_freight"]) + D(t["party_demurrage"]) != D(x["amount"]):
            out.append(x["trip_no"])
    return out


# ---------- words ----------

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    return ((_ONES[h] + " Hundred" + (" " if r else "")) if h else "") + (_two(r) if r else "")


def in_words(amount) -> str:
    """12345.50 -> 'Rupees Twelve Thousand Three Hundred Forty Five and Fifty Paise Only' (Indian system)."""
    v = calc.r2(D(amount))
    rupees, paise = int(v), int((v - int(v)) * 100)
    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"
    parts = []
    crore, rest = divmod(rupees, 10 ** 7)
    lakh, rest = divmod(rest, 10 ** 5)
    thousand, rest = divmod(rest, 1000)
    if crore:
        parts.append((in_words(crore).replace("Rupees ", "").replace(" Only", "") if crore > 999
                      else _three(crore)) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if rest:
        parts.append(_three(rest))
    s = "Rupees " + " ".join(parts) if parts else "Rupees Zero"
    if paise:
        s += f" and {_two(paise)} Paise"
    return s + " Only"


# ---------- PDF + WhatsApp ----------

def whatsapp_text(b: dict, company: str) -> str:
    tot = b["total"]
    trucks = ", ".join(x["truck_no"] for x in b["lines"][:8]) + (" ..." if len(b["lines"]) > 8 else "")
    return (f"Namaste {b['party_name']} ji,\nFreight bill *{b['bill_no']}* dt {b['bill_date']:%d/%m/%Y}\n"
            f"{len(b['lines'])} truck: {trucks}\n*Amount: ₹{_inr(tot)}*\n"
            "Bill PDF bhej rahe hain. Kripya payment karwa dein.\n— " + company)


def _inr(x) -> str:
    from core import followup
    return followup._inr(x)


def to_pdf(b: dict, co: dict, show_received: bool = False) -> bytes:
    """co = company details from settings: name, address, gstin, pan, mobile, bank, sac."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from core import pdf_fonts
    F, FB = pdf_fonts.setup()
    sf = pdf_fonts.safe
    RU = db.rate_unit()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=f"Bill {b['bill_no']}", author=co.get("name", ""))
    N = ParagraphStyle("n", fontName=F, fontSize=8.5, leading=11)
    S = ParagraphStyle("s", parent=N, fontSize=7.5, leading=9.5)
    SR = ParagraphStyle("sr", parent=S, alignment=2)
    H = ParagraphStyle("h", parent=N, fontName=FB, fontSize=16, leading=19, textColor=colors.HexColor("#1f6feb"))
    T = ParagraphStyle("t", parent=N, fontName=FB, fontSize=12, leading=15, alignment=1)
    blue, line = colors.HexColor("#1f6feb"), colors.HexColor("#c9d6ea")
    forward = b["gst_mode"] == "FORWARD"
    tot = totals(b["lines"], b["gst_mode"], b["gst_rate"], same_state(co.get("gstin"), b.get("party_gstin")))
    if forward:     # amounts as saved on the bill
        tot["gst"], tot["total"] = D(b["gst_amt"]), D(b["total"])

    co_lines = [x for x in (co.get("address"), " · ".join(y for y in (
        f"GSTIN: {co['gstin']}" if co.get("gstin") else "", f"PAN: {co['pan']}" if co.get("pan") else "",
        f"Mob: {co['mobile']}" if co.get("mobile") else "") if y)) if x]
    story = [Paragraph(sf(co.get("name") or "My Transport"), H)]
    story += [Paragraph(sf(x).replace("\n", "<br/>"), S) for x in co_lines]
    story += [Spacer(1, 6), Paragraph("TAX INVOICE (Freight Bill)" if forward else "FREIGHT BILL", T), Spacer(1, 6)]

    party = [f"<b>To:</b> {b['party_name']}"]
    if b.get("party_address"):
        party.append(str(b["party_address"]).replace("\n", "<br/>"))
    if b.get("party_gstin"):
        party.append(f"GSTIN: {b['party_gstin']}")
    right = [f"<b>Bill No.:</b> {b['bill_no']}", f"<b>Date:</b> {b['bill_date']:%d/%m/%Y}",
             f"<b>SAC:</b> {co.get('sac') or '996791'}"]
    hdr = Table([[Paragraph(sf("<br/>".join(party)), N), Paragraph(sf("<br/>".join(right)), N)]],
                colWidths=[120 * mm, 66 * mm])
    hdr.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, line), ("INNERGRID", (0, 0), (-1, -1), 0.5, line),
                             ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [hdr, Spacer(1, 8)]

    unit = "Qtl" if RU == "QUINTAL" else "T"
    cols = ["#", "Date", "Truck No.", "GR No.", "From → To", f"Wt ({unit})", f"Rate ₹/{unit.lower()}", "Freight",
            "Detention", "Amount"]
    data = [[Paragraph(f"<b>{sf(c)}</b>", ParagraphStyle("hd", parent=S, fontName=FB, textColor=colors.white,
                                                        alignment=2 if i >= 5 else 0)) for i, c in enumerate(cols)]]
    for i, x in enumerate(b["lines"], 1):
        w = D(x["weight"]) * (10 if RU == "QUINTAL" else 1)
        rate = calc.rate_show(D(x["rate"]), RU)
        d = date.fromisoformat(x["date"][:10]) if x.get("date") and x["date"] != "None" else None
        data.append([Paragraph(str(i), S), Paragraph(f"{d:%d/%m/%y}" if d else "", S), Paragraph(x["truck_no"], S),
                     Paragraph(x["gr_no"], S), Paragraph(sf(" → ".join(y for y in (x["from"], x["to"]) if y)), S),
                     Paragraph(f"{w.normalize():f}", SR), Paragraph(f"{rate.normalize():f}", SR),
                     Paragraph(_inr(x["freight"]), SR),
                     Paragraph(_inr(x["demurrage"]) if D(x["demurrage"]) else "", SR),
                     Paragraph(_inr(x["amount"]), SR)])
    widths = [6, 17, 22, 18, 33, 14, 14, 20, 21, 21]
    tbl = Table(data, colWidths=[w_ * mm for w_ in widths], repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), blue), ("GRID", (0, 0), (-1, -1), 0.25, line),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fc")])]))
    story.append(tbl)

    summ = [["Total freight", _inr(tot["freight"])]]
    if forward:
        if tot["igst"]:
            summ.append([f"IGST @ {D(tot['gst_rate']).normalize():f}%", _inr(tot["igst"])])
        else:
            half = D(tot["gst_rate"]) / 2
            summ += [[f"CGST @ {half.normalize():f}%", _inr(tot["cgst"])],
                     [f"SGST @ {half.normalize():f}%", _inr(tot["sgst"])]]
    summ.append(["Bill amount", _inr(tot["total"])])
    if show_received and tot["received"]:
        summ += [["Received (advance)", _inr(tot["received"])], ["Balance", _inr(tot["total"] - tot["received"])]]
    st_ = Table([[Paragraph(sf(k), N), Paragraph(f"₹ {v}" if pdf_fonts.setup()[0] == "AppSans" else f"Rs. {v}", SR)]
                 for k, v in summ], colWidths=[50 * mm, 36 * mm], hAlign="RIGHT")
    bi = [k for k, _ in summ].index("Bill amount")
    st_.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, line), ("INNERGRID", (0, 0), (-1, -1), 0.25, line),
                             ("BACKGROUND", (0, bi), (-1, bi), colors.HexColor("#eef3fb"))]))
    story += [Spacer(1, 6), st_, Spacer(1, 4), Paragraph(f"<b>{in_words(tot['total'])}</b>", N)]
    if b["gst_mode"] == "RCM":
        story.append(Paragraph(sf(f"GST @ {D(tot['gst_rate']).normalize():f}% (₹{_inr(tot['rcm_gst'])}) is payable "
                                  "by the recipient under Reverse Charge (RCM)."), S))
    elif b["gst_mode"] == "NONE":
        story.append(Paragraph("GST not charged on this bill.", S))
    if co.get("bank"):
        story += [Spacer(1, 6), Paragraph("<b>Bank details:</b> " + sf(co["bank"]).replace("\n", "<br/>"), S)]
    story += [Spacer(1, 26), Table([[Paragraph("Receiver's signature", S),
                                     Paragraph(sf(f"For {co.get('name') or ''}<br/><br/>Authorised signatory"), SR)]],
                                   colWidths=[93 * mm, 93 * mm])]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(F, 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(12 * mm, 8 * mm, f"Bill {b['bill_no']} · generated {clock.now():%d/%m/%Y %H:%M}")
        canvas.drawRightString(198 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def company() -> dict:
    s = db.get_settings()
    return {"name": s.get("company_name", ""), "address": s.get("company_address", ""),
            "gstin": s.get("company_gstin", ""), "pan": s.get("company_pan", ""),
            "mobile": s.get("company_mobile", ""), "bank": s.get("company_bank", ""),
            "sac": s.get("bill_sac", "996791")}
