"""Characterization tests for engine/factors/* — each evaluate(vehicle, comp_pool, base)."""
from engine.factors import mileage, condition, history, options, market_context, location

_BASE = 2_000_000
_CP = {
    "odometer_percentiles": {"p10": 50000, "p30": 80000, "p50": 110000, "p70": 150000, "p90": 220000},
    "comp_count": 12, "confidence": "high", "active_comp_count": 8,
}
_REQUIRED = {"factor", "label", "delta_pct", "dollar_impact", "reasoning"}


def _veh(**kw):
    v = {
        "year": 2019, "make": "FORD", "model": "F-150", "odometer_km": 110000,
        "driveline": "FWD", "fuel_type": "gas", "vehicle_type": "Truck",
        "exterior_grade": 3, "interior_grade": 3, "mechanical_grade": 3,
        "damage_items": [], "options_present": [],
        "accident_type": "none", "accident_claim_amount": 0, "rebuilt_title": False,
        "service_records": "full_dealer", "odometer_integrity": "clean",
        "seller_type": "Private", "declarations": "", "days_on_market": 0, "rust_free": False,
    }
    v.update(kw)
    return v


def _check_shape(r):
    assert _REQUIRED <= set(r)
    assert isinstance(r["delta_pct"], (int, float))


def test_mileage_band_direction():
    low = mileage.evaluate(_veh(odometer_km=40000), _CP, _BASE)
    high = mileage.evaluate(_veh(odometer_km=240000), _CP, _BASE)
    _check_shape(low); _check_shape(high)
    assert low["delta_pct"] == 8.0     # very low km premium
    assert high["delta_pct"] == -12.0  # very high km penalty
    assert low["delta_pct"] > 0 > high["delta_pct"]


def test_condition_grades():
    g5 = condition.evaluate(_veh(exterior_grade=5, interior_grade=5, mechanical_grade=5), _CP, _BASE)
    g1 = condition.evaluate(_veh(exterior_grade=1, interior_grade=1, mechanical_grade=1), _CP, _BASE)
    _check_shape(g5); _check_shape(g1)
    assert g5["delta_pct"] == 12.0
    assert g1["delta_pct"] == -18.0


def test_history_service_bonus_and_rebuilt_penalty():
    clean = history.evaluate(_veh(), _CP, _BASE)
    rebuilt = history.evaluate(_veh(rebuilt_title=True), _CP, _BASE)
    _check_shape(clean); _check_shape(rebuilt)
    assert clean["delta_pct"] == 3.0       # full dealer service history bonus
    assert rebuilt["delta_pct"] == -22.0   # rebuilt title penalty
    assert rebuilt["delta_pct"] < clean["delta_pct"]


def test_history_near_total_loss_flag():
    r = history.evaluate(_veh(accident_type="major", accident_claim_amount=18000,
                              vehicle_value_at_incident=20000), _CP, _BASE)
    assert r["near_total_loss"] is True
    assert r["delta_pct"] < -20


def test_options_add_value_capped():
    r = options.evaluate(_veh(options_present=["sunroof", "leather_seats"]), _CP, _BASE)
    _check_shape(r)
    assert r["delta_pct"] == 5.5
    # cap at +12%
    many = options.evaluate(_veh(options_present=[
        "sunroof", "leather_seats", "navigation", "premium_audio", "heated_front_seats",
        "remote_start", "blind_spot", "towing_package", "360_camera", "panoramic_roof"]), _CP, _BASE)
    assert many["delta_pct"] <= 12.0


def test_market_context_finance_repo_not_penalized():
    # FR must contribute 0% (same-day release), and a private seller has no dealer-exit penalty
    mc = market_context.evaluate(_veh(declarations="FR"), _CP, _BASE)
    _check_shape(mc)
    fr = [s for s in mc["sub_factors"] if "Repo" in s["label"]]
    assert fr and fr[0]["delta_pct"] == 0.0
    assert mc["delta_pct"] == 0.0


def test_market_context_dealer_at_auction_penalty():
    mc = market_context.evaluate(_veh(seller_type="Dealer"), _CP, _BASE)
    assert mc["delta_pct"] == -4.0


def test_location_alberta_premiums():
    assert location.evaluate(_veh(driveline="4WD"), _CP, _BASE)["delta_pct"] == 3.0
    assert location.evaluate(_veh(driveline="4WD", fuel_type="diesel"), _CP, _BASE)["delta_pct"] == 13.0
    assert location.evaluate(_veh(rust_free=True), _CP, _BASE)["delta_pct"] == 2.0
