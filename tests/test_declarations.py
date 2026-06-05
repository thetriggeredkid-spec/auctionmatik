"""Characterization tests for engine/declarations.py — Regal code + remark decoding."""
from engine import declarations as D


def test_known_codes_decode():
    d = D.analyze_declarations("FD;RS;MP", "")
    codes = {c["code"] for c in d["codes"]}
    assert codes == {"FD", "RS", "MP"}
    assert d["route_salvage"] is True   # FD
    assert d["rebuilt"] is True         # RS
    assert d["mechanical_risk"] is True  # MP


def test_claims_band_parsing():
    d = D.analyze_declarations("CH15000", "")
    assert d["claims_total_low"] == 15000
    assert any(c["code"] == "CH15000" for c in d["codes"])


def test_aa_and_freezing_damage():
    d = D.analyze_declarations("AA", "FREEZING DAMAGE")
    assert any(c["code"] == "AA" for c in d["codes"])
    assert "freezing_damage" in d["remark_signals"]
    assert d["mechanical_risk"] is True            # freezing routes to mechanical risk
    msgs = " ".join(f["message"].lower() for f in d["flags"])
    assert "auctioneer" in msgs and "freez" in msgs


def test_finance_repo_is_not_salvage():
    d = D.analyze_declarations("FR", "")
    assert d["finance_repo"] is True
    assert d["route_salvage"] is False


def test_unknown_code_labeled_cleanly():
    d = D.analyze_declarations("ZZZ", "")
    z = next(c for c in d["codes"] if c["code"] == "ZZZ")
    assert "unrecognized" in z["label"].lower()


def test_empty_input():
    d = D.analyze_declarations("", "")
    assert d["codes"] == []
    assert d["claims_total_low"] is None
    assert d["flags"] == []
