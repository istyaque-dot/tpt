"""Suggestions from past trips (less typing)."""
import os
import sys
from datetime import date
from decimal import Decimal as Dec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import smart  # noqa: E402

H = [  # newest first
    dict(party_id=2, to_place="Sultanpur", from_place="Kashipur", material="Paper", party_rate=Dec("1850"),
         truck_rate=Dec("1750"), commission_value=Dec("0"), owner_id=9, booking_date=date(2026, 11, 2)),
    dict(party_id=1, to_place="sultanpur", from_place="Bazpur", material="Rice", party_rate=Dec("1800"),
         truck_rate=Dec("1700"), commission_value=Dec("300"), owner_id=7, booking_date=date(2026, 10, 20)),
    dict(party_id=1, to_place="Delhi", from_place="Bazpur", material="Rice", party_rate=Dec("1200"),
         truck_rate=Dec("1100"), commission_value=Dec("500"), owner_id=8, booking_date=date(2026, 10, 1)),
]


def test_destination_brings_party_and_rates():
    s = smart.suggest(H, "Sultanpur")
    assert s["party_id"][0] == 2 and s["party_rate"][0] == Dec("1850") and s["truck_rate"][0] == Dec("1750")
    assert s["from_place"][0] == "Kashipur"


def test_chosen_party_wins():
    s = smart.suggest(H, "SULTANPUR", party_id=1)
    assert "party_id" not in s and s["party_rate"][0] == Dec("1800") and s["truck_rate"][0] == Dec("1700")
    assert s["material"][0] == "Rice"


def test_commission_by_owner_then_last():
    assert smart.suggest(H, "", owner_id=8)["commission"][0] == Dec("500")
    assert smart.suggest(H, "", owner_id=99)["commission"][0] == Dec("300")     # last non-zero


def test_new_destination_nothing_wrong():
    s = smart.suggest(H, "Patna")
    assert "party_id" not in s and "party_rate" not in s and "truck_rate" not in s


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("smart tests passed")
