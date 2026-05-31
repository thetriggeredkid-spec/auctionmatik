"""
Location Factor
Alberta-specific premiums: 4WD/AWD, diesel trucks, rust-free vehicles.

Inputs (from vehicle dict):
    driveline:   str — FWD / RWD / AWD / 4WD / 4X4
    fuel_type:   str — Gas / Diesel / Hybrid / EV
    vehicle_type: str — Car / Truck / Sport Utility / Van
    rust_free:   bool — True if vehicle has been Alberta-only or otherwise rust-free

Output:
    {delta_pct, dollar_impact, reasoning, sub_factors}
"""

AWD_4WD_PREMIUM = +0.03        # 4WD/AWD strong preference in Alberta
DIESEL_TRUCK_PREMIUM = +0.10   # Strong oilfield/ranch demand
RUST_FREE_PREMIUM = +0.02      # Dry climate rust-free premium


def evaluate(vehicle: dict, comp_pool: dict, base_price: int) -> dict:
    driveline = (vehicle.get("driveline") or "").upper()
    fuel_type = (vehicle.get("fuel_type") or "").upper()
    vtype = (vehicle.get("vehicle_type") or "").upper()
    rust_free = bool(vehicle.get("rust_free"))

    sub_factors = []

    # ── 4WD/AWD premium ───────────────────────────────────────────────────
    if any(kw in driveline for kw in ("4WD", "AWD", "4X4")):
        sub_factors.append({
            "factor": "location_4wd_premium",
            "label": "4WD/AWD — Alberta preference premium",
            "delta_pct": AWD_4WD_PREMIUM * 100,
            "dollar_impact": int(base_price * AWD_4WD_PREMIUM),
            "reasoning": f"{driveline} drivetrain. Strong Alberta preference for 4WD/AWD in winter conditions.",
        })

    # ── Diesel truck premium ──────────────────────────────────────────────
    if "DIESEL" in fuel_type and vtype in ("TRUCK", "SPORT UTILITY", "VAN"):
        sub_factors.append({
            "factor": "location_diesel_premium",
            "label": "Diesel — Alberta oilfield/ranch premium",
            "delta_pct": DIESEL_TRUCK_PREMIUM * 100,
            "dollar_impact": int(base_price * DIESEL_TRUCK_PREMIUM),
            "reasoning": "Diesel powertrain on truck/SUV. Strong Alberta demand from oilfield and agricultural users.",
        })

    # ── Rust-free premium ─────────────────────────────────────────────────
    if rust_free:
        sub_factors.append({
            "factor": "location_rust_free",
            "label": "Rust-free vehicle — Alberta dry climate premium",
            "delta_pct": RUST_FREE_PREMIUM * 100,
            "dollar_impact": int(base_price * RUST_FREE_PREMIUM),
            "reasoning": "Confirmed rust-free. Alberta-only or dry climate history commands trust premium "
                         "vs. vehicles from Ontario salt belt or BC coast.",
        })

    total_delta_pct = sum(sf["delta_pct"] for sf in sub_factors)
    total_dollar = sum(sf["dollar_impact"] for sf in sub_factors)

    if not sub_factors:
        return {
            "factor": "location",
            "label": "Location (Alberta)",
            "delta_pct": 0.0,
            "dollar_impact": 0,
            "reasoning": "No Alberta-specific location premiums apply.",
            "sub_factors": [],
        }

    reasoning = " | ".join(sf["label"] for sf in sub_factors)

    return {
        "factor": "location",
        "label": "Location (Alberta)",
        "delta_pct": total_delta_pct,
        "dollar_impact": total_dollar,
        "reasoning": reasoning,
        "sub_factors": sub_factors,
    }
