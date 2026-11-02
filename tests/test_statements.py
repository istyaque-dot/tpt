"""Statement rendering (PDF + WhatsApp text) works without a database."""
import os
import sys
import types
from decimal import Decimal as Dec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "streamlit" not in sys.modules:
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_resource = st.cache_data
    st.secrets = {}
    sys.modules["streamlit"] = st
for m in ("psycopg2", "psycopg2.extras", "psycopg2.pool"):
    sys.modules.setdefault(m, types.ModuleType(m))
from core import statements  # noqa: E402

SAMPLE = {
    "title": "Party Statement", "name": "ABC Cement", "subtitle": "98290", "period": "01/10/2026 to 31/10/2026",
    "summary": [("Opening", Dec("0")), ("Bill", Dec("61200")), ("Received", Dec("30000")),
                ("Closing receivable", Dec("31200"))],
    "tables": [{"heading": "Account statement",
                "columns": ["Date", "Particulars", "Bill / Debit", "Received / Credit", "Balance (Receivable)"],
                "rows": [["01/10/26", "Opening balance", "", "", Dec("0")],
                         ["02/10/26", "Freight bill RJ14AB1234 T-0001 GR 4521", Dec("30600"), "", Dec("30600")],
                         ["05/10/26", "Received RJ14AB1234 T-0001 UTR 998", "", Dec("30000"), Dec("600")]] * 30,
                "money": {2, 3, 4}, "total": ["", "Total", Dec("61200"), Dec("30000"), Dec("31200")]}],
    "note": "Balance = amount receivable from party.",
}


def test_pdf_and_text():
    pdf = statements.to_pdf(SAMPLE, "Khan Transport")
    assert pdf[:4] == b"%PDF" and len(pdf) > 3000
    txt = statements.to_text(SAMPLE)
    assert "*Party Statement*" in txt and "30,600.00" in txt and "31,200.00" in txt
    rows = statements.to_rows(SAMPLE)
    assert rows[0]["Section"] == "Account statement" and rows[-1]["Particulars"] == "Total"


if __name__ == "__main__":
    test_pdf_and_text()
    print("statement tests passed")
