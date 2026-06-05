"""Characterization tests for engine/advisor.py + engine/valuation_modes.py."""
from engine import advisor, valuation_modes

_CLEAN_DECL = {
    "codes": [], "route_salvage": False, "rebuilt": False, "out_of_province": False,
    "mechanical_risk": False, "claims_total_low": None, "remark_signals": [],
    "verify_before_bid": [], "flags": [],
}


def test_claim_fraction_scales_with_value():
    assert advisor._claim_fraction(5000) == 0.05
    assert advisor._claim_fraction(15000) == 0.10
    assert advisor._claim_fraction(30000) == 0.18
    assert advisor._claim_fraction(50000) == 0.25


def test_margin_floor_respected():
    assert advisor._margin(advisor.PROFILES["charles"], 10000) == 1500
    assert advisor._margin(advisor.PROFILES["mechanic"], 10000) == 800


def test_advise_clean_retail_flip_is_bid():
    a = advisor.advise(
        {"year": 2015, "make": "JEEP", "model": "WRANGLER", "odometer_km": 140000},
        anchor_cents=1_500_000, clean_value_cents=1_500_000, decl=_CLEAN_DECL,
        vision={}, carfax=None, profile_key="charles",
    )
    assert a["verdict"] == "BID"
    assert a["mode"] == "A"
    assert 0 < a["max_bid_cents"] < 1_500_000   # below the anchor after margin/fee/gst
    assert "thesis" in a and a["thesis"]


def test_advise_profiles_diverge():
    kw = dict(anchor_cents=1_500_000, clean_value_cents=1_500_000, decl=_CLEAN_DECL,
              vision={}, carfax=None)
    subj = {"year": 2015, "make": "JEEP", "model": "WRANGLER", "odometer_km": 140000}
    ch = advisor.advise(subj, profile_key="charles", **kw)
    me = advisor.advise(subj, profile_key="mechanic", **kw)
    # mechanic's lower margin floor → higher bid ceiling
    assert me["max_bid_cents"] >= ch["max_bid_cents"]


def test_route_mode():
    assert valuation_modes.route_mode(_CLEAN_DECL, {}, {"total_mid": 0}, 1_500_000) == "A"
    salv = dict(_CLEAN_DECL, route_salvage=True)
    assert valuation_modes.route_mode(salv, {}, {"total_mid": 5000}, 1_500_000) == "B"
