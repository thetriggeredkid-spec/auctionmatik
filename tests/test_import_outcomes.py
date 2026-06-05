"""Tests for collector/import_outcomes.py pure transforms."""
from collector import import_outcomes as IO


def test_vehicle_from_sold_maps_fields():
    rec = {"year": 2019, "make": "FORD", "model": "F-150", "trim": "XLT", "driveline": "4WD",
           "odometer_km": 120000, "declarations": "FR", "condition_notes": "clean",
           "vin": "X", "contract": "123", "sale_price": 2_400_000}
    v = IO._vehicle_from_sold(rec)
    assert v["year"] == 2019 and v["make"] == "FORD" and v["driveline"] == "4WD"
    assert v["odometer_km"] == 120000
    # neutral condition defaults applied (no inspection for a historical sale)
    assert v["exterior_grade"] == 3 and v["accident_type"] == "none"


def test_norm_verdict():
    assert IO._norm_verdict("BID-TO-FIX") == "BID_TO_FIX"
    assert IO._norm_verdict("BID") == "BID"
    assert IO._norm_verdict("PASS (thin margin)") == "PASS"
    assert IO._norm_verdict(None) == "PASS"


def test_bid_err_pct():
    # engine bid below the realized price → negative error (expected from margin)
    assert IO._bid_err_pct(900_000, 1_000_000) == -10.0
    assert IO._bid_err_pct(1_100_000, 1_000_000) == 10.0
    assert IO._bid_err_pct(1_000_000, 0) is None


def test_feedback_params_shape():
    rec = {"contract": "123", "year": 2019, "make": "FORD", "model": "F-150", "sale_price": 2_000_000}
    call = {"verdict": "BID-TO-FIX", "value_cents": 1_800_000, "max_bid_cents": 1_500_000}
    p = IO._feedback_params(rec, call)
    assert p[0] == "123"
    assert p[4] == "BID_TO_FIX"          # normalized verdict
    assert p[6] == 1_500_000             # engine_max_bid (cents)
    assert p[7] == 2_000_000             # actual_sale_price (cents)
    assert p[8].startswith("[auto]")     # auto tag → kept out of the retail track
