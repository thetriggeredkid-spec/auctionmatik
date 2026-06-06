"""Characterization tests for engine/advisor.py + engine/valuation_modes.py."""

from engine import advisor, valuation_modes

_CLEAN_DECL = {
    "codes": [],
    "route_salvage": False,
    "rebuilt": False,
    "out_of_province": False,
    "mechanical_risk": False,
    "claims_total_low": None,
    "remark_signals": [],
    "verify_before_bid": [],
    "flags": [],
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
        anchor_cents=1_500_000,
        clean_value_cents=1_500_000,
        decl=_CLEAN_DECL,
        vision={},
        carfax=None,
        profile_key="charles",
    )
    assert a["verdict"] == "BID"
    assert a["mode"] == "A"
    assert 0 < a["max_bid_cents"] < 1_500_000  # below the anchor after margin/fee/gst
    assert "thesis" in a and a["thesis"]


def test_advise_profiles_diverge():
    kw = dict(
        anchor_cents=1_500_000,
        clean_value_cents=1_500_000,
        decl=_CLEAN_DECL,
        vision={},
        carfax=None,
    )
    subj = {"year": 2015, "make": "JEEP", "model": "WRANGLER", "odometer_km": 140000}
    ch = advisor.advise(subj, profile_key="charles", **kw)
    me = advisor.advise(subj, profile_key="mechanic", **kw)
    # mechanic's lower margin floor → higher bid ceiling
    assert me["max_bid_cents"] >= ch["max_bid_cents"]


def test_purchase_context_private_dealer_vs_auction():
    subj = {"year": 2015, "make": "JEEP", "model": "WRANGLER", "odometer_km": 140000}
    kw = dict(
        anchor_cents=1_500_000,
        clean_value_cents=1_500_000,
        decl=_CLEAN_DECL,
        vision={},
        carfax=None,
        profile_key="charles",
    )
    auction = advisor.advise(subj, **kw)  # default ctx == auction
    private_ab = advisor.advise(
        subj, ctx=advisor.purchase_context("private", tax_rate=0.0), **kw
    )
    dealer_ab = advisor.advise(
        subj, ctx=advisor.purchase_context("dealer", tax_rate=0.05), **kw
    )

    # Private AB: no auction fee, no tax → highest max-buy (closest to sale − margin)
    assert (
        private_ab["max_bid_cents"]
        > dealer_ab["max_bid_cents"]
        > auction["max_bid_cents"]
    )
    # Private AB max buy == expected_sale − margin exactly (no fee, no tax)
    margin = advisor._margin(
        advisor.PROFILES["charles"], private_ab["expected_sale_cents"] / 100
    )
    assert (
        private_ab["max_bid_cents"] == private_ab["expected_sale_cents"] - margin * 100
    )
    # Dealer AB divides the same net by 1.05 (no fee)
    net = dealer_ab["expected_sale_cents"] - margin * 100
    assert abs(dealer_ab["max_bid_cents"] - net / 1.05) < 200  # cents rounding
    # context echoed back; off-auction thesis says "max buy", not "bid"
    assert private_ab["context"]["kind"] == "private"
    assert "max buy" in private_ab["thesis"] and "Regal fee" not in private_ab["thesis"]


def test_purchase_context_helper():
    a = advisor.purchase_context("auction")
    assert a["apply_auction_fee"] and a["tax_rate"] == advisor.GST_RATE
    p = advisor.purchase_context("private", tax_rate=0.0)
    assert not p["apply_auction_fee"] and p["tax_rate"] == 0.0


def test_route_mode():
    assert (
        valuation_modes.route_mode(_CLEAN_DECL, {}, {"total_mid": 0}, 1_500_000) == "A"
    )
    salv = dict(_CLEAN_DECL, route_salvage=True)
    assert valuation_modes.route_mode(salv, {}, {"total_mid": 5000}, 1_500_000) == "B"
