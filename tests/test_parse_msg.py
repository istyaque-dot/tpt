"""Pasted booking messages -> trip fields."""
import os
import sys
from decimal import Decimal as Dec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.parse_msg import parse  # noqa: E402

TRUCKS = [{"id": 1, "truck_no": "RJ14AB1234"}, {"id": 2, "truck_no": "MH12CD5678"}]
PARTIES = [{"id": 10, "name": "ABC Cement"}, {"id": 11, "name": "Shree Steel"}]
PLACES = ["Jaipur", "Delhi", "New Delhi", "Kota", "Indore"]
MATS = ["Cement", "Coal"]


def p(text):
    return parse(text, TRUCKS, PARTIES, PLACES, MATS)


def test_hinglish_full():
    r = p("RJ14AB1234 Jaipur se Delhi 25.5 ton cement party rate 1200 gaadi bhada 1100 ABC Cement GR 4521 adv 10000")
    assert r["truck_id"] == 1 and r["from_place"] == "Jaipur" and r["to_place"] == "Delhi"
    assert r["weight"] == Dec("25.5") and r["party_rate"] == Dec("1200") and r["truck_rate"] == Dec("1100")
    assert r["party_id"] == 10 and r["gr_no"] == "4521" and r["advance"] == Dec("10000")
    assert r["material"] == "Cement"


def test_spaced_plate_arrow_route_units():
    r = p("Truck: mh 12 cd 5678 | Kota -> Indore | Wt 28 MT | Freight @1,150 | Truck rate 1080 | Shree Steel")
    assert r["truck_id"] == 2 and r["from_place"] == "Kota" and r["to_place"] == "Indore"
    assert r["weight"] == Dec("28") and r["party_rate"] == Dec("1150") and r["truck_rate"] == Dec("1080")
    assert r["party_id"] == 11


def test_last_digits_and_unlabelled_rates():
    r = p("gaadi 1234 kota se new delhi 30 tons rate 1250 aur 1150/ton driver 9876543210")
    assert r["truck_id"] == 1                                    # matched by last 4 digits
    assert r["to_place"] == "New Delhi" and r["from_place"] == "Kota"
    assert r["party_rate"] == Dec("1250") and r["truck_rate"] == Dec("1150")   # two rates: higher = party
    assert r["mobile"] == "9876543210" and r["weight"] == Dec("30")
    assert any("check" in n for n in r["notes"])


def test_one_known_place_is_not_forced_to_destination():
    r = parse("RJ14AB1234 Jaipur se Bhopal 25 ton", TRUCKS, PARTIES, ["Jaipur"], [])
    assert r["from_place"] == "Jaipur" and r["to_place"] == "Bhopal"
    r = parse("RJ14AB1234 Bhopal se Jaipur 25 ton", TRUCKS, PARTIES, ["Jaipur"], [])
    assert r["from_place"] == "Bhopal" and r["to_place"] == "Jaipur"
    r = parse("unload: new delhi, RJ14AB1234 25 ton", TRUCKS, PARTIES, PLACES, [])
    assert r["to_place"] == "New Delhi"


def test_hindi():
    r = parse("गाड़ी RJ14AB1234 जयपुर से दिल्ली 25 टन भाड़ा 1100", TRUCKS, PARTIES, [], [])
    assert r["truck_id"] == 1 and r["weight"] == Dec("25") and r["truck_rate"] == Dec("1100")
    assert r["from_place"] == "जयपुर" and r["to_place"] == "दिल्ली"


def test_unknown_truck_and_missing():
    r = p("GJ01XY9999 to Indore")
    assert r["truck_no"] == "GJ01XY9999" and "truck_id" not in r
    assert any("Naya truck" in n for n in r["notes"]) and any("weight" in n for n in r["notes"])
    assert r["to_place"] == "Indore"


def test_real_message_unit_first_and_points():
    r = parse("UP70FT7739 Kashipur to Sultanpur 2point mt 35 Rate 175  Driver no +919005899224", [], [], [], [])
    assert r["truck_no"] == "UP70FT7739" and r["from_place"] == "Kashipur" and r["to_place"] == "Sultanpur"
    assert r["weight"] == Dec("35") and r["points"] == 2 and r["mobile"] == "9005899224"
    assert Dec("175") in (r.get("party_rate"), r.get("truck_rate"))
    assert parse("RJ14AB1234 25 mt Jaipur to Kota", [], [], [], [])["weight"] == Dec("25")


def test_quintal_default_and_explicit_ton():
    msg = "UP70FT7739 Kashipur to Sultanpur 2point mt 35 Rate 175  Driver no +919005899224"
    r = parse(msg, [], [], [], [], default_unit="QUINTAL")
    assert r["truck_rate"] == Dec("1750") and "party_rate" not in r and any("quintal" in n for n in r["notes"])
    assert any("TRUCK ka bhada" in n for n in r["notes"])
    r = parse("RJ14AB1234 Jaipur to Kota 25 ton rate 1200/ton", [], [], [], [], default_unit="QUINTAL")
    assert r["truck_rate"] == Dec("1200")                       # message says per ton -> no ×10
    r = parse("RJ14AB1234 Jaipur to Kota 25 ton rate 120 per qtl", [], [], [], [])
    assert r["truck_rate"] == Dec("1200")                       # message says quintal even when default is ton
    r = parse(msg, [], [], [], [], default_unit="QUINTAL", single_rate_for="PARTY")
    assert r["party_rate"] == Dec("1750") and "truck_rate" not in r
    r = parse("RJ14AB1234 Jaipur to Kota 25 ton party rate 1200", [], [], [], [])
    assert r["party_rate"] == Dec("1200")                       # labelled rate still goes to its own box


def test_many_trucks_one_message():
    from core.parse_msg import parse_many
    msg = "Kashipur to Sultanpur rate 175\nUP70FT7739 mt 35 driver 9005899224\nUP22AB1234 mt 30\nHR55X1234 32 mt"
    rs = parse_many(msg, [], [], [], [], default_unit="QUINTAL")
    assert [r["truck_no"] for r in rs] == ["UP70FT7739", "UP22AB1234", "HR55X1234"]
    assert all(r["to_place"] == "Sultanpur" and r["truck_rate"] == Dec("1750") for r in rs)
    assert [r["weight"] for r in rs] == [Dec("35"), Dec("30"), Dec("32")]
    assert rs[0]["mobile"] == "9005899224" and "mobile" not in rs[1]       # driver no. stays with its truck
    rs = parse_many("UP70FT7739 Kashipur to Sultanpur mt 35 Rate 175\nUP22AB1234 Bazpur to Bemetara mt 30 rate 300",
                    [], [], [], [], default_unit="QUINTAL")
    assert rs[1]["to_place"] == "Bemetara" and rs[1]["truck_rate"] == Dec("3000")
    assert len(parse_many("UP70FT7739 Kashipur to Sultanpur mt 35 Rate 175", [], [], [], [])) == 1


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            n += 1
    print(f"{n} parse tests passed")
