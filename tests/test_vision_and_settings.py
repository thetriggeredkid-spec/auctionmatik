"""Characterization tests for engine/vision_factors.py + engine/settings.py (pure parts)."""

from engine import vision_factors as VF
from engine import settings as S


def test_map_mod_lift_truck_vs_car():
    assert (
        VF._map_mod("lift kit", "professional", {"model": "WRANGLER"})
        == "lift_kit_truck"
    )
    assert VF._map_mod("lift kit", "professional", {"model": "CIVIC"}) == "lift_kit_car"
    assert VF._map_mod("window tint", "amateur", {}) == "window_tint"
    assert VF._map_mod("unknown gizmo", "amateur", {}) is None


def test_vision_to_spec_grades_and_damage():
    va = {
        "exterior_grade": 4,
        "interior_grade": 3,
        "rust_severity": "none",
        "damage_details": [
            {"damage_type": "dent", "severity": "moderate", "panel": "door"}
        ],
    }
    spec = VF.vision_to_spec(va, {"model": "CIVIC"})
    assert spec["exterior_grade"] == 4
    assert spec["interior_grade"] == 3
    assert spec.get("rust_free") is True
    assert any(d["type"] == "dent" for d in spec.get("damage_items", []))


def test_vision_to_spec_empty():
    assert VF.vision_to_spec({}, {}) == {}
    assert VF.vision_to_spec({"error": "x"}, {}) == {}


def test_settings_deep_merge():
    merged = S._deep_merge({"a": {"x": 1, "y": 2}, "b": 3}, {"a": {"y": 9}, "c": 4})
    assert merged == {"a": {"x": 1, "y": 9}, "b": 3, "c": 4}


def test_settings_to_profile_shape():
    p = S._to_profile(
        {
            "label": "X",
            "margin_floor": 2000,
            "repair_small_factor": 0.6,
            "repair_large_factor": 0.7,
        },
        "x",
    )
    assert p["margin_floor"] == 2000
    assert p["repair"]["small_factor"] == 0.6
    assert p["repair"]["large_factor"] == 0.7


def test_active_location_and_tax():
    S.CURRENT.clear()
    S.CURRENT.update(
        {
            "locations": [
                {
                    "label": "Edmonton, AB",
                    "city": "edmonton",
                    "province": "AB",
                    "business_tax": 0.05,
                    "private_tax": 0.0,
                },
                {
                    "label": "Toronto, ON",
                    "city": "toronto",
                    "province": "ON",
                    "business_tax": 0.13,
                    "private_tax": 0.13,
                },
            ],
            "active_location": "Toronto, ON",
        }
    )
    assert S.active_location()["province"] == "ON"
    assert S.location_tax("private") == 0.13
    assert S.location_tax("dealer") == 0.13
    # switch to AB → private untaxed, business 5%
    S.CURRENT["active_location"] = "Edmonton, AB"
    assert S.location_tax("private") == 0.0
    assert S.location_tax("dealer") == 0.05
    # unknown active → first location; empty → Edmonton default
    S.CURRENT["active_location"] = "nope"
    assert S.active_location()["label"] == "Edmonton, AB"
    S.CURRENT.clear()
    assert S.active_location()["province"] == "AB"
