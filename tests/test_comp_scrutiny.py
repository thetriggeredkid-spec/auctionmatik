"""Characterization tests for engine/comp_scrutiny.py — normalization + scrutinize."""
from engine import comp_scrutiny as CS


def test_km_normalize_more_km_adjusts_up():
    # a higher-km comp normalized to a lower-km subject adjusts the price UP
    base = CS._km_normalize(1_000_000, 200_000, 100_000)
    assert base == 1_340_000
    # equal km → unchanged
    assert CS._km_normalize(1_000_000, 100_000, 100_000) == 1_000_000
    # missing data → unchanged
    assert CS._km_normalize(1_000_000, None, 100_000) == 1_000_000


def test_dom_discount_steps():
    assert CS._dom_discount(10) == 0.0
    assert CS._dom_discount(30) == 0.03
    assert CS._dom_discount(50) == 0.07
    assert CS._dom_discount(120) == 0.12
    assert CS._dom_discount(None) == 0.0


def test_norm_cab():
    assert CS._norm_cab("XLT SuperCrew") == "crew"
    assert CS._norm_cab("F-150 SuperCab") == "ext"
    assert CS._norm_cab("Regular Cab") == "reg"
    assert CS._norm_cab("Sedan") is None


def test_trim_token():
    assert CS._trim_token("2019 Ford F-150 Lariat") == "lariat"
    assert CS._trim_token("XLT SuperCrew") == "xlt"
    assert CS._trim_token("plain car") is None


def test_scrutinize_excludes_rebuilt_and_returns_anchor():
    subject = {"year": 2015, "make": "JEEP", "model": "WRANGLER", "odometer_km": 140000}
    comps = [
        {"year": 2015, "make": "Jeep", "model": "Wrangler", "odometer_km": 150000,
         "asking_price": 1_600_000, "title": "clean", "description": "good condition"},
        {"year": 2014, "make": "Jeep", "model": "Wrangler", "odometer_km": 135000,
         "asking_price": 1_550_000, "title": "clean", "description": ""},
        {"year": 2016, "make": "Jeep", "model": "Wrangler", "odometer_km": 120000,
         "asking_price": 1_700_000, "title": "clean", "description": ""},
        {"year": 2013, "make": "Jeep", "model": "Wrangler", "odometer_km": 160000,
         "asking_price": 950_000, "title": "rebuilt", "description": "rebuilt title salvage"},
    ]
    res = CS.scrutinize(subject, comps)
    assert set(res) >= {"anchor", "confidence", "clean", "excluded", "narrative"}
    assert isinstance(res["anchor"], int) and res["anchor"] > 0
    assert res["confidence"] in ("high", "medium", "low")
    # the rebuilt comp is excluded from the clean pool
    assert any("rebuilt" in (e.get("_reason") or "") for e in res["excluded"])
    assert all(c.get("_title") != "rebuilt" for c in res["clean"])


def test_scrutinize_empty_pool():
    res = CS.scrutinize({"year": 2015, "make": "X", "model": "Y", "odometer_km": 100000}, [])
    assert res["anchor"] is None
    assert res["clean"] == []
