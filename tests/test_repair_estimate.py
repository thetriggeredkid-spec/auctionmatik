"""Characterization tests for engine/repair_estimate.py."""
from engine import repair_estimate as RE


def test_single_component_quote():
    r = RE.estimate_repair([{"component": "front bumper", "action": "replace", "severity": "severe"}])
    assert len(r["line_items"]) == 1
    assert r["total_mid"] == 1200
    assert r["total_low"] <= r["total_mid"] <= r["total_high"]
    assert r["line_items"][0]["matched"] is True


def test_empty_components():
    r = RE.estimate_repair([])
    assert r["total_low"] == 0 and r["total_high"] == 0 and r["total_mid"] == 0
    assert r["line_items"] == []


def test_buffer_increases_total():
    comps = [{"component": "hood", "action": "replace", "severity": "moderate"}]
    low_buf = RE.estimate_repair(comps, buffer=0.0)
    hi_buf = RE.estimate_repair(comps, buffer=0.5)
    assert hi_buf["total_high"] > low_buf["total_high"]


def test_sourcing_factors_cheaper_diy():
    comps = [{"component": "frame rail", "action": "replace", "severity": "severe"}]
    oem = RE.estimate_repair(comps, small_factor=1.0, large_factor=1.0)
    diy = RE.estimate_repair(comps, small_factor=0.5, large_factor=0.55)
    assert diy["total_mid"] < oem["total_mid"]


def test_contingent_inspect_item_split():
    r = RE.estimate_repair([{"component": "airbag", "action": "inspect", "severity": "unknown"}])
    assert r["contingent_high"] > 0
    assert r["confirmed_high"] == 0


def test_string_components_accepted():
    r = RE.estimate_repair(["radiator", "hood"])
    assert len(r["line_items"]) == 2
