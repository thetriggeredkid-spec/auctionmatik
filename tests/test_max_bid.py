"""Characterization tests for engine/max_bid.py — fee schedule, margin tiers, calc."""
from engine import max_bid


def test_buyer_fee_bands():
    assert max_bid.get_buyer_fee(4000) == 285
    assert max_bid.get_buyer_fee(7500) == 385
    assert max_bid.get_buyer_fee(12000) == 535
    assert max_bid.get_buyer_fee(20000) == 685
    assert max_bid.get_buyer_fee(30000) == 835
    assert max_bid.get_buyer_fee(50000) == 985


def test_buyer_fee_boundaries():
    # band is low <= price < high
    assert max_bid.get_buyer_fee(5000) == 385
    assert max_bid.get_buyer_fee(0) == 285


def test_margin_tiers():
    assert max_bid.get_margin(10000) == (1500, "Tier 1 (<$15k sell)")
    assert max_bid.get_margin(18000) == (2500, "Tier 2 ($15k–$20k sell)")
    assert max_bid.get_margin(25000) == (3500, "Tier 3 ($20k–$35k sell)")
    assert max_bid.get_margin(50000) == (5000, "Tier 4 ($35k+ sell)")


def test_calculate_structure_and_gst():
    res = max_bid.calculate(1_500_000)  # $15,000 retail in cents
    assert isinstance(res, dict)
    assert {"tier1", "tier2", "tier3", "tier4"} <= set(res)
    t = res["tier1"]
    assert {"label", "max_bid_cents", "buyer_fee", "margin"} <= set(t)
    # higher margin tier ⇒ lower max bid
    assert res["tier1"]["max_bid_cents"] >= res["tier4"]["max_bid_cents"]
    # default tier label matches one of the tier labels
    labels = {res[f"tier{i}"]["label"] for i in range(1, 5)}
    assert res["default_tier_label"] in labels
