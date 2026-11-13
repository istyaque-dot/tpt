"""Follow-up aging + WhatsApp text, bill totals / words / number, voice transcription (no database)."""
import os
import sys
import types
from datetime import date
from decimal import Decimal as Dec
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "streamlit" not in sys.modules:
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_resource = st.cache_data
    st.secrets = {}
    sys.modules["streamlit"] = st
for m in ("psycopg2", "psycopg2.extras", "psycopg2.pool"):
    sys.modules.setdefault(m, types.ModuleType(m))
from core import bills, calc, followup  # noqa: E402

TODAY = date(2026, 11, 30)


def trip(i, bal, loaded, pod_given=None, party=1, pod=False, **kw):
    t = {"id": i, "trip_no": f"T-{i:04d}", "party_id": party, "party_name": "Shree Cement", "truck_id": 1,
         "truck_no": f"UP70AB{i:04d}", "loaded_weight": Dec("30"), "loading_date": loaded, "booking_date": loaded,
         "party_balance": Dec(bal), "pod_submitted": bool(pod_given), "pod_submit_date": pod_given,
         "pod_received": pod, "is_cancelled": False, "gr_no": f"G{i}"}
    t.update(kw)
    return t


def test_party_dues_aging():
    rows = [trip(1, "30000", date(2026, 10, 1), pod_given=date(2026, 10, 20)),   # 41 days since POD given
            trip(2, "20000", date(2026, 11, 25)),                                # 5 days since loading
            trip(3, "0.5", date(2026, 9, 1)),                                    # settled (tolerance)
            trip(4, "9000", date(2026, 11, 1), party=2)]
    d = followup.party_dues(rows, TODAY)
    assert [p["party_id"] for p in d] == [1, 2]            # oldest first
    p = d[0]
    assert p["total"] == Dec("50000") and p["oldest"] == 41
    assert p["buckets"]["31-60 din"] == Dec("30000") and p["buckets"]["0-15 din"] == Dec("20000")
    msg = followup.party_message(p, "My Transport", only_pod_given=True)
    assert "UP70AB0001" in msg and "UP70AB0002" not in msg and "30,000" in msg
    link = followup.wa_link("+91 98290 12345", msg)
    assert link.startswith("https://wa.me/919829012345?text=") and "Kul baaki" in unquote(link)
    assert followup.wa_link(None, "x") == "https://wa.me/?text=x"


def test_pod_pending():
    rows = [trip(1, "1", date(2026, 11, 1)), trip(2, "1", date(2026, 11, 28)), trip(3, "1", date(2026, 10, 1), pod=True)]
    p = followup.pod_pending(rows, TODAY, min_days=7)
    assert [t["id"] for t in p] == [1] and p[0]["days"] == 29
    assert "POD" in followup.pod_message(p[0], "X")


def test_bill_numbers_words_gst():
    assert bills.fy_of(date(2026, 4, 1)) == "26-27" and bills.fy_of(date(2027, 3, 31)) == "26-27"
    assert bills.fy_of(date(2026, 3, 31)) == "25-26"
    assert bills.in_words(Dec("125000")) == "Rupees One Lakh Twenty Five Thousand Only"
    assert bills.in_words(Dec("10305075.50")) == \
        "Rupees One Crore Three Lakh Five Thousand Seventy Five and Fifty Paise Only"
    lines = [{"amount": "61250"}, {"amount": "54000.50"}]
    t = bills.totals(lines, "FORWARD", 12, same_state=True)
    assert t["freight"] == Dec("115250.50") and t["gst"] == Dec("13830.06")
    assert t["cgst"] + t["sgst"] == t["gst"] and t["total"] == Dec("129080.56")
    t = bills.totals(lines, "FORWARD", 12, same_state=False)
    assert t["igst"] == t["gst"] and t["cgst"] == 0
    t = bills.totals(lines, "RCM", 5)
    assert t["gst"] == 0 and t["total"] == t["freight"] and t["rcm_gst"] == Dec("5762.53")
    assert bills.totals(lines, "NONE", 5)["rcm_gst"] == 0
    assert bills.same_state("09ABCDE1234F1Z5", "09XYZ") and not bills.same_state("09A", "07B")
    assert bills.same_state("", "07B")       # unknown -> CGST+SGST


def test_bill_pdf_has_rupee_font():
    from core import pdf_fonts
    assert pdf_fonts.setup()[0] == "AppSans"
    b = {"bill_no": "26-27/001", "bill_date": date(2026, 11, 30), "party_name": "Shree Cement",
         "party_address": "Kashipur", "party_gstin": "05AAAAA0000A1Z5", "gst_mode": "FORWARD", "gst_rate": Dec("12"),
         "gst_amt": Dec("7350"), "total": Dec("68600"),
         "lines": [{"trip_id": 1, "trip_no": "T-0001", "date": "2026-11-11", "truck_no": "UP70FT7739",
                    "gr_no": "1234", "from": "Kashipur", "to": "Sultanpur", "material": "", "weight": "35",
                    "rate": "1750", "freight": "61250", "demurrage": "0", "amount": "61250", "received": "0"}]}
    import core.db as dbm
    dbm.rate_unit = lambda: "QUINTAL"
    pdf = bills.to_pdf(b, {"name": "My Transport", "gstin": "05BBBBB1111B1Z5", "sac": "996791"})
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_voice_transcribe_fake():
    from core import ai
    ai.st.secrets = {"GEMINI_API_KEY": "k"}
    seen = {}

    def _post(model, body, timeout):
        seen["mime"] = body["contents"][0]["parts"][1]["inline_data"]["mime_type"]
        return {"candidates": [{"content": {"parts": [{"text": '{"text": "UP70FT7739 Kashipur se Sultanpur 35 ton rate 175"}'}]}}]}
    ai._post = _post
    assert ai.transcribe(b"RIFF....", "audio/wav").startswith("UP70FT7739")
    assert seen["mime"] == "audio/wav"
    ai._post = lambda *a: {"candidates": [{"content": {"parts": [{"text": '{"text": ""}'}]}}]}
    try:
        ai.transcribe(b"x")
        raise AssertionError("empty voice should raise")
    except ai.AIError:
        pass
    assert calc.D("1") == 1
