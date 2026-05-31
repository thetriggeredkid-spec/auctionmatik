"""
Options & Modifications Factor
Lookup table of % deltas per option.
Modifications use mod_tolerance by vehicle type.

Inputs (from vehicle dict):
    options_present:  list of option keys (str)
    modifications:    list of dicts [{type, quality}]
    vehicle_type:     str — Car / Truck / Sport Utility / Van
    make:             str
    model:            str

Output:
    {delta_pct, dollar_impact, reasoning, sub_factors}
"""

# Options lookup: option_key -> delta_pct
OPTIONS_DELTAS = {
    # Universal
    "sunroof":              +0.03,
    "panoramic_roof":       +0.04,
    "navigation":           +0.01,  # declining on newer vehicles
    "premium_audio":        +0.02,
    "heated_front_seats":   +0.015,
    "heated_steering":      +0.01,
    "remote_start":         +0.01,
    "blind_spot":           +0.02,
    "lane_assist":          +0.015,
    "parking_sensors":      +0.01,
    "360_camera":           +0.02,
    "backup_camera":        +0.01,
    "power_tailgate":       +0.02,
    "cold_weather_package": +0.03,  # Alberta premium
    "tech_safety_package":  +0.025,
    "leather_seats":        +0.025,
    "apple_carplay":        +0.01,
    "ventilated_seats":     +0.02,
    # Truck/SUV specific
    "towing_package":       +0.04,
    "max_tow_package":      +0.055,
    "spray_in_bedliner":    +0.02,
    "tonneau_cover":        +0.02,
    "running_boards":       +0.015,
    "diesel_engine":        +0.10,  # strong Alberta premium
    "third_row_seating":    +0.03,
    "air_suspension":       +0.04,
    # Performance
    "sport_package":        +0.025,
    "limited_slip_diff":    +0.02,
    "track_package":        +0.03,
}

# Options cap — redundant stacking capped at this total
OPTIONS_CAP = 0.12

# Modifications lookup
MOD_DELTAS = {
    "full_wrap":                -0.03,
    "aftermarket_remote_start":  0.0,
    "performance_intake":        0.0,
    "pro_audio_system":         +0.015,
    "diy_audio_system":         -0.01,
    "aftermarket_bumper":       -0.02,  # unknown quality default
    "quality_aftermarket_bumper": +0.025,
    "lift_kit_truck":           -0.025,
    "lift_kit_car":             -0.075,
    "aftermarket_wheels_cheap": -0.02,
    "aftermarket_wheels_quality": +0.015,
    "spray_in_bedliner":        +0.02,
    "performance_exhaust":       0.0,
    "ecu_tune":                 -0.03,
    "lowering_springs":         -0.04,
    "window_tint":               0.0,
    "aftermarket_head_unit":    -0.01,
    "running_boards_aftermarket": +0.015,
    "tonneau_cover_aftermarket": +0.02,
}

# Mod tolerance multipliers by vehicle type/model
MOD_TOLERANCE = {
    "high":    1.0,   # mods land as-is (Wrangler, off-road trucks)
    "moderate": 0.7,  # mods partially discounted
    "low":      0.4,  # mods amplified negative / positive suppressed
    "very_low": 0.2,  # luxury — mods mostly negative
}

HIGH_TOLERANCE_MODELS = {"WRANGLER", "GLADIATOR", "4RUNNER", "FJ CRUISER", "BRONCO"}
VERY_LOW_TOLERANCE_MAKES = {"BMW", "MERCEDES-BENZ", "AUDI", "LEXUS", "PORSCHE", "FERRARI", "MASERATI"}


def _get_mod_tolerance(vehicle: dict) -> tuple[str, float]:
    model = (vehicle.get("model") or "").upper()
    make = (vehicle.get("make") or "").upper()
    vtype = (vehicle.get("vehicle_type") or "").upper()

    if model in HIGH_TOLERANCE_MODELS:
        return "high", MOD_TOLERANCE["high"]
    if make in VERY_LOW_TOLERANCE_MAKES:
        return "very_low", MOD_TOLERANCE["very_low"]
    if "TRUCK" in vtype or "PICKUP" in model:
        return "moderate", MOD_TOLERANCE["moderate"]
    if vtype in ("SPORT UTILITY", "SUV"):
        return "low", MOD_TOLERANCE["low"]
    return "low", MOD_TOLERANCE["low"]


def evaluate(vehicle: dict, comp_pool: dict, base_price: int) -> dict:
    options_present = vehicle.get("options_present") or []
    modifications = vehicle.get("modifications") or []

    sub_factors = []

    # ── Options ───────────────────────────────────────────────────────────
    options_total_delta = 0.0
    options_applied = []
    for opt in options_present:
        opt_key = opt.lower().replace(" ", "_").replace("-", "_")
        delta = OPTIONS_DELTAS.get(opt_key, 0.0)
        if delta != 0.0:
            options_applied.append((opt_key, delta))
            options_total_delta += delta

    # Cap total options delta
    if options_total_delta > OPTIONS_CAP:
        options_total_delta = OPTIONS_CAP

    if options_applied:
        dollar_impact = int(base_price * options_total_delta)
        opt_list = ", ".join(f"{k} (+{d*100:.1f}%)" for k, d in options_applied[:8])
        sub_factors.append({
            "factor": "options",
            "label": f"{len(options_applied)} value-add option(s)",
            "delta_pct": options_total_delta * 100,
            "dollar_impact": dollar_impact,
            "reasoning": f"Options: {opt_list}. Capped at {OPTIONS_CAP*100:.0f}% total.",
        })

    # ── Modifications ─────────────────────────────────────────────────────
    tol_label, tol_mult = _get_mod_tolerance(vehicle)

    mod_total_delta = 0.0
    mod_descriptions = []
    for mod in modifications:
        mod_type = mod if isinstance(mod, str) else mod.get("type", "")
        mod_key = mod_type.lower().replace(" ", "_").replace("-", "_")
        raw_delta = MOD_DELTAS.get(mod_key, 0.0)
        adjusted_delta = raw_delta * tol_mult
        mod_total_delta += adjusted_delta
        mod_descriptions.append(f"{mod_type} ({raw_delta*100:+.1f}% × {tol_mult} tolerance = {adjusted_delta*100:+.1f}%)")

    if modifications:
        dollar_impact = int(base_price * mod_total_delta)
        sub_factors.append({
            "factor": "modifications",
            "label": f"{len(modifications)} modification(s) — {tol_label} tolerance vehicle",
            "delta_pct": mod_total_delta * 100,
            "dollar_impact": dollar_impact,
            "reasoning": f"Mod tolerance: {tol_label}. " + " | ".join(mod_descriptions),
        })

    total_delta_pct = sum(sf["delta_pct"] for sf in sub_factors)
    total_dollar = sum(sf["dollar_impact"] for sf in sub_factors)

    reasoning_parts = []
    if options_applied:
        reasoning_parts.append(f"{len(options_applied)} options valued")
    if modifications:
        reasoning_parts.append(f"{len(modifications)} mod(s) at {tol_label} tolerance")
    if not reasoning_parts:
        reasoning_parts.append("No notable options or modifications")

    return {
        "factor": "options",
        "label": "Options & modifications",
        "delta_pct": total_delta_pct,
        "dollar_impact": total_dollar,
        "reasoning": ". ".join(reasoning_parts) + ".",
        "sub_factors": sub_factors,
    }
