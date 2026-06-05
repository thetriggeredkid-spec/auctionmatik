"""Tests for the vision prompt upgrades + dash-warning-light wiring."""
from engine import vision
from engine import declarations as D
import dashboard.mapper as M


def test_prompt_asks_for_dash_lights_and_replacement_panels():
    p = vision.VISION_PROMPT
    assert "dash_warning_lights" in p
    assert "instrument cluster" in p.lower()
    # don't mislabel an unpainted/replacement panel as damage
    assert "REPLACEMENT" in p and "refinish" in p


def test_append_dash_lights_folds_into_notes():
    r = M._append_dash_lights("body fair.", {"dash_warning_lights": ["check engine", "airbag/SRS"]})
    assert "check engine light on" in r and "airbag/SRS light on" in r
    # no lights → unchanged
    assert M._append_dash_lights("x", {"dash_warning_lights": []}) == "x"
    assert M._append_dash_lights(None, {}) is None


def test_dash_lights_decode_to_mechanical_signals():
    notes = M._append_dash_lights("", {"dash_warning_lights": ["check engine", "airbag/SRS"]})
    d = D.analyze_declarations("", notes)
    assert "check_engine" in d["remark_signals"]
    assert "airbag_light" in d["remark_signals"]
    assert d["mechanical_risk"] is True


def test_vision_to_design_exposes_dash_lights():
    vd = M._vision_to_design({"exterior_grade": 3, "interior_grade": 3,
                              "dash_warning_lights": ["check engine"]})
    assert vd["dashLights"] == ["check engine"]
