"""Statements: Party, Petrol Pump, Truck Owner (ledger style, with running balance) and one-Trip statement.

Every statement is plain data first:
    {"title", "name", "subtitle", "period", "summary": [(label, value)], "tables": [table, ...], "note"}
    table = {"heading", "columns": [...], "rows": [[...]], "money": {col_index, ...}, "total": [...] or None}
and is then drawn as PDF (to_pdf) or WhatsApp text (to_text) — so screen, PDF and text always agree.
"""
import io
from collections import OrderedDict

from core import calc, clock, db, trips, ui

D, ZERO = calc.D, calc.ZERO


def _ledger_lines(account_id: int, d_from, d_to):
    """Opening + one row per entry (voucher) for an account, with trip / truck details."""
    acc = db.one("select * from accounts where id=%s", (account_id,))
    before = db.one("select coalesce(sum(debit - credit), 0) s from v_ledger where account_id=%s and v_date < %s",
                    (account_id, d_from))["s"]
    opening = D(acc["opening_balance"]) + D(before)
    rows = db.query(
        "select l.voucher_id, min(l.v_date) v_date, min(l.v_type) v_type, min(l.purpose) purpose, "
        "min(l.trip_no) trip_no, min(l.gr_no) gr_no, min(l.ref_no) ref_no, min(l.narration) narration, "
        "min(l.litres) litres, min(l.rate) rate, sum(l.debit) debit, sum(l.credit) credit, "
        "min(tk.truck_no) truck_no, min(l.batch_no) batch_no "
        "from v_ledger l left join trips t on t.id = l.trip_id left join trucks tk on tk.id = t.truck_id "
        "where l.account_id = %s and l.v_date between %s and %s "
        "group by l.voucher_id order by min(l.v_date), l.voucher_id", (account_id, d_from, d_to))
    return acc, opening, rows


def _particulars(r, side: str) -> str:
    """Human words for one ledger row. side = PARTY / PUMP / OWNER."""
    t = f"{r['truck_no'] or ''} {r['trip_no'] or ''}".strip()
    gr = f" GR {r['gr_no']}" if r.get("gr_no") else ""
    vt, p = r["v_type"], r["purpose"] or ""
    if vt == "TRIP":
        if side == "PARTY":
            return f"Freight bill {t}{gr}" + (" (less shortage)" if D(r["credit"]) else "")
        return f"Truck hire {t}{gr}" + (" (less commission/shortage)" if D(r["debit"]) else "")
    if vt == "RECEIPT":
        return ("Advance adjusted " if p == "ADJUST" else "Received ") + (t or "on account") + \
            (f" UTR {r['ref_no']}" if r.get("ref_no") else "")
    if vt == "PAYMENT":
        return ("Advance adjusted " if p == "ADJUST" else f"{p.title()} paid ") + t + \
            (f" UTR {r['ref_no']}" if r.get("ref_no") else "")
    if vt == "DIESEL":
        lit = f" {D(r['litres'])} L" if r.get("litres") else ""
        slip = f" slip {r['ref_no']}" if r.get("ref_no") else ""
        return f"Diesel {t}{gr}{lit}{slip}"
    if vt == "PUMP_PAYMENT":
        return "Payment to pump" + (f" Ref {r['ref_no']}" if r.get("ref_no") else "")
    return r.get("narration") or vt.title()


def account_statement(account_id: int, d_from, d_to, side: str) -> dict:
    """side PARTY: balance shown as receivable (Dr +). PUMP / OWNER: shown as payable (Cr +)."""
    acc, opening, rows = _ledger_lines(account_id, d_from, d_to)
    sign = 1 if side == "PARTY" else -1
    run = opening
    out, tot_dr, tot_cr = [], ZERO, ZERO
    for r in rows:
        dr, cr = D(r["debit"]), D(r["credit"])
        run += dr - cr
        tot_dr += dr
        tot_cr += cr
        out.append([f"{r['v_date']:%d/%m/%y}", _particulars(r, side), dr or "", cr or "", run * sign])
    label = {"PARTY": ("Bill / Debit", "Received / Credit", "Receivable"),
             "PUMP": ("Paid / Debit", "Diesel / Credit", "Payable"),
             "OWNER": ("Paid / Debit", "Hire / Credit", "Payable")}[side]
    tables = [{"heading": "Account statement",
               "columns": ["Date", "Particulars", label[0], label[1], f"Balance ({label[2]})"],
               "rows": [[f"{d_from:%d/%m/%y}", "Opening balance", "", "", opening * sign]] + out,
               "money": {2, 3, 4}, "total": ["", "Total", tot_dr, tot_cr, run * sign]}]
    summary = [("Opening", opening * sign), (label[0].split(" /")[0], tot_dr), (label[1].split(" /")[0], tot_cr),
               (f"Closing {label[2].lower()}", run * sign)]

    if side == "PUMP":
        dies = [r for r in rows if r["v_type"] == "DIESEL"]
        if dies:
            lit = sum((D(r["litres"]) for r in dies), ZERO)
            tables.append({"heading": "Diesel truck-wise",
                           "columns": ["Date", "Truck", "Trip / GR", "Slip", "Litres", "Rate", "Amount"],
                           "rows": [[f"{r['v_date']:%d/%m/%y}", r["truck_no"] or "", (r["trip_no"] or "")
                                     + (f" / {r['gr_no']}" if r.get("gr_no") else ""), r["ref_no"] or "",
                                     D(r["litres"]) or "", D(r["rate"]) or "", D(r["credit"])] for r in dies],
                           "money": {6}, "total": ["", "", "", "Total", lit or "", "",
                                                   sum((D(r["credit"]) for r in dies), ZERO)]})
            summary.insert(3, ("Diesel litres", lit))

    if side in ("PARTY", "OWNER"):
        key = "party_id" if side == "PARTY" else "owner_id"
        open_trips = [t for t in trips.load_trips(f"not t.is_cancelled and t.{key} = %s", (account_id,),
                                                  "t.loading_date nulls last, t.id")
                      if (t["party_balance"] if side == "PARTY" else t["truck_balance"]) > calc.SETTLED_TOLERANCE]
        if side == "PARTY":
            rows_ = [[t["truck_no"] or "", t.get("gr_no") or "", f"{t['loading_date']:%d/%m/%y}" if t.get("loading_date")
                      else "", t["billing_weight"], t["party_rate"], t["party_freight"] + t["party_demurrage"],
                      t["party_shortage"], t["party_received"], t["party_balance"]] for t in open_trips]
            cols = ["Truck", "GR", "Loaded", "Wt (T)", "Rate", "Freight+Dem", "Shortage", "Received", "Balance"]
            money = {5, 6, 7, 8}
        else:
            rows_ = [[t["truck_no"] or "", t["trip_no"], f"{t['loading_date']:%d/%m/%y}" if t.get("loading_date") else "",
                      t["truck_hire"] + t["truck_demurrage"], t["truck_paid"] + t["diesel"],
                      t["commission"] + t["truck_shortage"], "Yes" if t["pod_received"] else "No", t["truck_balance"]]
                     for t in open_trips]
            cols = ["Truck", "Trip", "Loaded", "Hire+Dem", "Paid+Diesel", "Comm+Short", "POD", "Balance"]
            money = {3, 4, 5, 7}
        if rows_:
            tot = [""] * len(cols)
            tot[0] = "Total"
            tot[-1] = sum((D(r[-1]) for r in rows_), ZERO)
            tables.append({"heading": "Pending trips (balance due)", "columns": cols, "rows": rows_,
                           "money": money, "total": tot})

    extra = " · ".join(x for x in (f"Mobile {acc['mobile']}" if acc.get("mobile") else "",
                                    acc.get("location") or "", f"GSTIN {acc['gstin']}" if acc.get("gstin") else "") if x)
    return {"title": {"PARTY": "Party Statement", "PUMP": "Petrol Pump Statement",
                      "OWNER": "Truck Owner Statement"}[side],
            "name": acc["name"], "subtitle": extra, "period": f"{d_from:%d/%m/%Y} to {d_to:%d/%m/%Y}",
            "summary": summary, "tables": tables,
            "note": "Balance = amount receivable from party." if side == "PARTY"
            else "Balance = amount payable by us."}


def trip_statement(trip_id: int) -> dict:
    t = trips.get_trip(trip_id)
    v = db.query(
        "select v.id, v.v_date, v.v_type, v.purpose, v.amount, v.litres, v.rate, v.ref_no, v.is_cancelled, "
        "(select string_agg(a.name, ', ') from ledger_entries e join accounts a on a.id = e.account_id "
        "  where e.voucher_id = v.id and a.acc_type in ('CASH','BANK','PUMP','OTHER')) via "
        "from vouchers v where v.trip_id = %s and v.v_type <> 'TRIP' and not v.is_cancelled "
        "order by v.v_date, v.id", (trip_id,))
    truck_rows = [[f"{x['v_date']:%d/%m/%y}",
                   ("Diesel" + (f" {D(x['litres'])} L" if x.get("litres") else "")) if x["v_type"] == "DIESEL"
                   else (x["purpose"] or "").title(), x["via"] or "", x["ref_no"] or "", D(x["amount"])]
                  for x in v if x["v_type"] in ("PAYMENT", "DIESEL")]
    party_rows = [[f"{x['v_date']:%d/%m/%y}", (x["purpose"] or "").replace("_", " ").title(), x["via"] or "",
                   x["ref_no"] or "", D(x["amount"])] for x in v if x["v_type"] == "RECEIPT"]
    info = [
        ("Truck", f"{t.get('truck_no') or '-'} ({t.get('owner_name') or '-'})"),
        ("Party", t["party_name"]), ("Route", calc.route(t)),
        ("GR No.", t.get("gr_no") or "pending"),
        ("Loaded", f"{t['loaded_weight'] or 0} T on {t['loading_date']:%d/%m/%Y}" if t.get("loading_date") else "-"),
        ("Unloaded", f"{t['unloaded_weight']} T" if t.get("unloaded_weight") else "-"),
        ("POD", ("received" if t["pod_received"] else "pending")
         + (f", given to party {t['pod_submit_date']:%d/%m/%Y}" if t.get("pod_submitted") and t.get("pod_submit_date") else "")),
        ("Status", t["status"]),
    ]
    w = t["billing_weight"]
    truck_calc = [["Truck hire", f"{w} T × {t['truck_rate'] or 0}", t["truck_hire"]]]
    if t["truck_demurrage"]:
        truck_calc.append(["+ Demurrage", f"{t.get('demurrage_days') or ''} day(s)".strip(), t["truck_demurrage"]])
    truck_calc += [["− Advance / payments", "", t["truck_paid"]], ["− Diesel", "", t["diesel"]],
                   ["− Commission", f"{t['commission_value']}%" if t["commission_type"] == "PERCENT" else "",
                    t["commission"]]]
    if t["truck_shortage"]:
        truck_calc.append(["− Shortage / damage", "", t["truck_shortage"]])
    party_calc = [["Freight", f"{w} T × {t['party_rate']}", t["party_freight"]]]
    if t["party_demurrage"]:
        party_calc.append(["+ Demurrage", "", t["party_demurrage"]])
    party_calc.append(["− Received", "", t["party_received"]])
    if t["party_shortage"]:
        party_calc.append(["− Shortage / damage", "", t["party_shortage"]])
    tables = [
        {"heading": "Truck side", "columns": ["Item", "Detail", "Amount"], "rows": truck_calc, "money": {2},
         "total": ["Balance payable", "", t["truck_balance"]]},
        {"heading": "Advance / diesel / payment details", "columns": ["Date", "Type", "From", "Ref", "Amount"],
         "rows": truck_rows, "money": {4},
         "total": ["", "Total", "", "", sum((r[-1] for r in truck_rows), ZERO)] if truck_rows else None},
        {"heading": "Party side", "columns": ["Item", "Detail", "Amount"], "rows": party_calc, "money": {2},
         "total": ["Balance receivable", "", t["party_balance"]]},
        {"heading": "Party receipts", "columns": ["Date", "Type", "Into", "UTR / Ref", "Amount"],
         "rows": party_rows, "money": {4},
         "total": ["", "Total", "", "", sum((r[-1] for r in party_rows), ZERO)] if party_rows else None},
    ]
    return {"title": "Trip Statement", "name": f"{t['trip_no']} · {t.get('truck_no') or ''}",
            "subtitle": " · ".join(f"{k}: {v}" for k, v in info), "period": "",
            "summary": [("Truck balance", t["truck_balance"]), ("Party balance", t["party_balance"]),
                        ("Profit", t["net_profit"])],
            "tables": tables, "note": t.get("remarks") or "", "info": info}


# ---------- rendering ----------

def _fmt(v, money: bool) -> str:
    if v == "" or v is None:
        return ""
    if isinstance(v, (int, float, calc.Decimal)) and not isinstance(v, bool):
        return ui.inr(v) if money else (f"{D(v).normalize():f}" if D(v) else "")
    return str(v)


def to_text(s: dict) -> str:
    """Short WhatsApp version."""
    lines = [f"*{s['title']}*", s["name"]]
    if s.get("period"):
        lines.append(s["period"])
    if s.get("info"):
        lines += [f"{k}: {v}" for k, v in s["info"]]
    lines.append("")
    for t in s["tables"]:
        if not t["rows"]:
            continue
        lines.append(f"*{t['heading']}*")
        for r in t["rows"][:60]:
            lines.append(" | ".join(_fmt(v, i in t["money"]) for i, v in enumerate(r) if _fmt(v, i in t["money"])))
        if t.get("total"):
            lines.append("*" + " | ".join(_fmt(v, i in t["money"]) for i, v in enumerate(t["total"])
                                          if _fmt(v, i in t["money"])) + "*")
        lines.append("")
    lines += [f"{k}: {_fmt(v, True)}" for k, v in s["summary"]]
    return "\n".join(lines)


def to_rows(s: dict) -> list[OrderedDict]:
    """Flat rows for CSV/Excel (all tables one after another)."""
    out = []
    for t in s["tables"]:
        for r in t["rows"] + ([t["total"]] if t.get("total") else []):
            row = OrderedDict(Section=t["heading"])
            for c, v in zip(t["columns"], r):
                row[c] = float(v) if isinstance(v, calc.Decimal) else v
            out.append(row)
    return out


def to_pdf(s: dict, company: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=f"{s['title']} - {s['name']}", author=company)
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, leading=10)
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=7.5, leading=9)
    cell_r = ParagraphStyle("cell_r", parent=cell, alignment=2)          # money: right aligned
    head = ParagraphStyle("head", parent=ss["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=4)
    blue = colors.HexColor("#1f6feb")
    story = [Paragraph(f"<b>{company}</b>", ParagraphStyle("co", parent=ss["Title"], fontSize=16, alignment=0,
                                                           textColor=blue, spaceAfter=2)),
             Paragraph(f"<b>{s['title']}</b> — {s['name']}", ParagraphStyle("t", parent=ss["Normal"], fontSize=11)),
             ]
    if s.get("period"):
        story.append(Paragraph(f"Period: {s['period']}", small))
    if s.get("info"):
        info_rows = [[Paragraph(f"<b>{k}</b>", cell), Paragraph(str(v), cell)] for k, v in s["info"]]
        it = Table(info_rows, colWidths=[28 * mm, 150 * mm])
        it.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        story += [Spacer(1, 4), it]
    elif s.get("subtitle"):
        story.append(Paragraph(str(s["subtitle"]), small))

    summ = [[Paragraph(f"<b>{k}</b>", cell) for k, _ in s["summary"]],
            [Paragraph(_fmt(v, True), cell) for _, v in s["summary"]]]
    st_ = Table(summ, colWidths=[186 * mm / len(s["summary"])] * len(s["summary"]))
    st_.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb")),
                             ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d6ea")),
                             ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d6ea"))]))
    story += [Spacer(1, 6), st_]

    for t in s["tables"]:
        if not t["rows"]:
            continue
        story.append(Paragraph(t["heading"], head))
        hdr = ParagraphStyle("hdr", parent=cell, textColor=colors.white)
        hdr_r = ParagraphStyle("hdr_r", parent=hdr, alignment=2)
        data = [[Paragraph(f"<b>{c}</b>", hdr_r if i in t["money"] else hdr) for i, c in enumerate(t["columns"])]]
        for r in t["rows"]:
            data.append([Paragraph(_fmt(v, i in t["money"]), cell_r if i in t["money"] else cell)
                         for i, v in enumerate(r)])
        if t.get("total"):
            data.append([Paragraph(f"<b>{_fmt(v, i in t['money'])}</b>", cell_r if i in t["money"] else cell)
                         for i, v in enumerate(t["total"])])
        n = len(t["columns"])
        widths = _col_widths(t, n)
        tbl = Table(data, colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6feb")),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d6ea")),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fc")])]
        for i in t["money"]:
            style.append(("ALIGN", (i, 1), (i, -1), "RIGHT"))
        if t.get("total"):
            style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef3fb")))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)
    if s.get("note"):
        story += [Spacer(1, 6), Paragraph(s["note"], small)]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(12 * mm, 8 * mm, f"{company} · generated {clock.now():%d/%m/%Y %H:%M}")
        canvas.drawRightString(198 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _col_widths(t, n):
    from reportlab.lib.units import mm
    total = 186 * mm
    if t["columns"][:2] == ["Date", "Particulars"]:
        rest = (total - 18 * mm - 70 * mm) / (n - 2)
        return [18 * mm, 70 * mm] + [rest] * (n - 2)
    if t["columns"] == ["Item", "Detail", "Amount"]:
        return [60 * mm, 86 * mm, 40 * mm]
    return [total / n] * n
