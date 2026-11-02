"""AI helper with a fake Gemini (no internet): mapping, quintal rates, fallback, POD bundle grouping."""
import json
import os
import sys
import types
from decimal import Decimal as Dec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "streamlit" not in sys.modules:
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_resource = st.cache_data
    sys.modules["streamlit"] = st
st = sys.modules["streamlit"]
st.secrets = {"GEMINI_API_KEY": "test-key"}
from core import ai  # noqa: E402

TRUCKS = [{"id": 1, "truck_no": "RJ14AB1234"}]
PARTIES = [{"id": 10, "name": "Universal Industries"}, {"id": 11, "name": "ABC Cement"}]


def fake(reply):
    def _post(model, body, timeout):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(reply)}]}}]}
    ai._post = _post


def test_message_quintal_and_party_match():
    fake({"truck_no": "up 70 ft 7739", "from_place": "kashipur", "to_place": "sultanpur", "weight_ton": 35,
          "rate": 175, "rate_unit": "quintal", "rate_for": "unknown", "party_name": "universal industries",
          "driver_mobile": "+91 90058 99224", "points": 2, "other_trucks": ["UP70AB1111"]})
    r = ai.parse_message("x", TRUCKS, PARTIES)
    assert r["truck_no"] == "UP70FT7739" and "truck_id" not in r
    assert r["from_place"] == "Kashipur" and r["to_place"] == "Sultanpur" and r["weight"] == Dec("35")
    assert r["party_rate"] == Dec("1750") and r["party_id"] == 10 and r["mobile"] == "9005899224"
    assert r["points"] == 2 and any("UP70AB1111" in n for n in r["notes"])
    assert any("quintal" in n for n in r["notes"])


def test_labelled_rates_and_existing_truck():
    fake({"truck_no": "RJ14AB1234", "to_place": "Delhi", "weight_ton": 25, "party_rate": 1200, "truck_rate": 1100,
          "rate_unit": "ton"})
    r = ai.parse_message("x", TRUCKS, PARTIES)
    assert r["truck_id"] == 1 and r["party_rate"] == Dec("1200") and r["truck_rate"] == Dec("1100")


def test_fallback_to_rules_when_ai_fails():
    def boom(model, body, timeout):
        raise ai.urllib.error.URLError("offline")
    ai._post = boom
    r = ai.parse_message_safe("UP70FT7739 Kashipur to Sultanpur mt 35 Rate 175", [], [], [], [])
    assert r["source"] == "rules" and r["weight"] == Dec("35") and "⚠️" in r["notes"][0]


def test_merge_rules_fill_gaps():
    fake({"truck_no": "UP70FT7739", "to_place": "Sultanpur"})            # AI missed weight
    r = ai.parse_message_safe("UP70FT7739 Kashipur to Sultanpur mt 35", [], [], [], [])
    assert r["source"] == "AI" and r["weight"] == Dec("35")
    assert not any("weight" in n for n in r["notes"])


def test_document_and_bundle():
    fake({"doc_type": "POD", "gr_no": " gr 4521 ", "truck_no": "up70 ft7739", "unloaded_weight_ton": "34.8"})
    d = ai.read_document(b"%PDF", "application/pdf")
    assert d["gr_no"] == "GR 4521" and d["truck_no"] == "UP70FT7739" and d["unloaded_weight_ton"] == Dec("34.8")
    fake([{"page": 1, "gr_no": "4521"}, {"page": 2, "gr_no": ""}, {"page": 3, "gr_no": "4522", "sure": False},
          {"page": 4, "gr_no": "4522"}, {"page": 5, "gr_no": ""}])
    groups = ai.group_pages(ai.map_bundle(b"%PDF"), 5)
    assert groups == [{"gr_no": "4521", "pages": [1, 2], "sure": True},
                      {"gr_no": "4522", "pages": [3, 4, 5], "sure": False}]


def test_split_pdf():
    import io

    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for _ in range(4):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    part = ai.split_pdf(buf.getvalue(), [2, 3])
    assert len(PdfReader(io.BytesIO(part)).pages) == 2


def test_not_configured():
    st.secrets = {}
    try:
        ai.ask_json("x")
        raise AssertionError("should fail")
    except ai.AIError as e:
        assert "GEMINI_API_KEY" in str(e)
    st.secrets = {"GEMINI_API_KEY": "test-key"}


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            n += 1
    print(f"{n} AI tests passed")
