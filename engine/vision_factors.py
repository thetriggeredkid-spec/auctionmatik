"""
Vision → Vehicle-Spec Bridge
Translates a stored vision_assessment (from engine/vision.py) into the vehicle-spec
fields the pricing factors already consume:

    exterior_grade / interior_grade   -> condition factor
    damage_details + rust_severity    -> condition.damage_items (cost-to-repair)
    aftermarket_mods                  -> options.modifications (MOD_DELTAS keys)
    flood_or_frame_concern            -> history.accident_type = 'major'

This keeps the factors unchanged — vision just fills the same inputs a human would.
Cost tables are first-pass estimates; tune them with Charles's repair-cost experience.
"""

# Cost-to-repair (CAD dollars) by (damage_type, severity). Midpoint is deducted at
# 1.35x in condition.py. Conservative; override from real shop quotes over time.
DAMAGE_COST = {
    ("dent", "minor"): (150, 400),    ("dent", "moderate"): (400, 1200),   ("dent", "severe"): (1200, 3000),
    ("scratch", "minor"): (100, 300), ("scratch", "moderate"): (300, 800),  ("scratch", "severe"): (800, 2000),
    ("paint", "minor"): (200, 500),   ("paint", "moderate"): (500, 1500),   ("paint", "severe"): (1500, 4000),
    ("crack", "minor"): (150, 400),   ("crack", "moderate"): (400, 1000),   ("crack", "severe"): (1000, 2500),
    ("rust", "minor"): (200, 500),    ("rust", "moderate"): (800, 2000),    ("rust", "severe"): (3000, 6000),
    ("missing", "minor"): (200, 500), ("missing", "moderate"): (500, 1500), ("missing", "severe"): (1500, 4000),
    ("other", "minor"): (150, 400),   ("other", "moderate"): (400, 1000),   ("other", "severe"): (1000, 2500),
}

# Body/underbody rust by severity (Alberta road salt). 'none' also unlocks the rust-free bonus.
RUST_COST = {"none": (0, 0), "surface": (200, 500), "moderate": (800, 2000),
             "severe": (3000, 6000), "unknown": (0, 0)}

_TRUCKISH_MODELS = {"WRANGLER", "GLADIATOR", "BRONCO", "4RUNNER", "FJ CRUISER"}


def _is_truckish(vehicle: dict) -> bool:
    vtype = (vehicle.get("vehicle_type") or "").upper()
    model = (vehicle.get("model") or "").upper()
    return ("TRUCK" in vtype or vtype in ("SPORT UTILITY", "SUV")
            or model in _TRUCKISH_MODELS or "PICKUP" in model)


def _map_mod(mod_type: str, quality: str, vehicle: dict) -> str | None:
    """Map a free-text vision mod into an engine MOD_DELTAS key (or None if unpriced)."""
    t = (mod_type or "").lower()
    q = (quality or "unknown").lower()
    pro = q == "professional"
    if "lift" in t:
        return "lift_kit_truck" if _is_truckish(vehicle) else "lift_kit_car"
    if "lower" in t:
        return "lowering_springs"
    if "wheel" in t or "rim" in t:
        return "aftermarket_wheels_quality" if pro else "aftermarket_wheels_cheap"
    if "exhaust" in t:
        return "performance_exhaust"
    if "tint" in t:
        return "window_tint"
    if "running board" in t:
        return "running_boards_aftermarket"
    if "tonneau" in t:
        return "tonneau_cover_aftermarket"
    if "bumper" in t:
        return "quality_aftermarket_bumper" if pro else "aftermarket_bumper"
    if "intake" in t:
        return "performance_intake"
    if "tune" in t or "ecu" in t:
        return "ecu_tune"
    # light bar, winch, roof rack, fog lights, spare carrier, etc. — no priced delta
    return None


def vision_to_spec(va: dict, vehicle: dict | None = None) -> dict:
    """
    Convert a vision_assessment dict into vehicle-spec overrides.
    Returns only the keys vision can speak to; merge over the base vehicle dict.
    """
    vehicle = vehicle or {}
    spec: dict = {}
    if not va or va.get("error"):
        return spec

    # Grades (mechanical isn't visible from photos — left to default/other inputs)
    if va.get("exterior_grade") is not None:
        spec["exterior_grade"] = int(va["exterior_grade"])
    if va.get("interior_grade") is not None:
        spec["interior_grade"] = int(va["interior_grade"])

    # Damage items (visible panels) + rust as an underbody damage item
    damage_items = []
    for d in va.get("damage_details") or []:
        dtype = (d.get("damage_type") or "other").lower()
        sev = (d.get("severity") or "moderate").lower()
        low, high = DAMAGE_COST.get((dtype, sev), DAMAGE_COST.get(("other", sev), (0, 0)))
        if high > 0:
            damage_items.append({
                "type": dtype, "location": d.get("panel", "unknown"),
                "repair_cost_low": low, "repair_cost_high": high,
            })

    rust = (va.get("rust_severity") or "unknown").lower()
    r_low, r_high = RUST_COST.get(rust, (0, 0))
    if r_high > 0:
        damage_items.append({
            "type": "rust", "location": "body/underbody",
            "repair_cost_low": r_low, "repair_cost_high": r_high,
        })
    if damage_items:
        spec["damage_items"] = damage_items

    # Confirmed rust-free unlocks the Alberta location bonus
    if rust == "none":
        spec["rust_free"] = True

    # Aftermarket mods -> engine mod keys
    mods = []
    for m in va.get("aftermarket_mods") or []:
        key = _map_mod(m.get("type", ""), m.get("quality", "unknown"), vehicle)
        if key:
            mods.append(key)
    if mods:
        spec["modifications"] = mods

    # Visible flood / frame evidence = major-accident-grade red flag
    if va.get("flood_or_frame_concern") is True:
        spec["accident_type"] = "major"

    return spec
