"""
Valuation Modes & Router
Decides whether a vehicle is priced as Mode A (retail-grade) or Mode B
(salvage / repair-project), then produces a sane, floored value for each.

This is the layer that fixes the test blow-ups:
  - Outlander  -65% condition on a cheap car  -> capped + floored (Mode A)
  - Equinox    negative price                 -> salvage math / parts-only (Mode B)

Inputs come from: declarations.analyze_declarations, the vision assessment,
repair_estimate.estimate_repair, and the comp anchor.

Constants are TUNABLE — confirm with Charles.
"""

# ── Tunables ──────────────────────────────────────────────────────────────────
TITLE_FACTOR_REBUILT      = 0.78   # rebuilt title -> ~78% of clean after-fix value (Charles: ~0.75-0.80)
CONDITION_DEDUCTION_CAP   = 0.55   # Mode A: condition+damage can't knock more than 55% off the anchor
SALVAGE_FLOOR_RATIO       = 0.12   # a running vehicle rarely sells below ~12% of clean (wholesale/parts floor)
HEAVY_DAMAGE_ROUTE_RATIO  = 0.40   # repair_mid > 40% of clean value -> route to Mode B even if not declared
MECHANICAL_RESERVE_UNKNOWN = 1000  # $ reserve for an unspecified mechanical problem (bigger % bite on cheap cars)
PARTS_VALUE_RATIO         = 0.10   # parts-only residual ~10% of clean (very rough; tune)


def route_mode(decl: dict, vision: dict, repair_est: dict, clean_value: int | None) -> str:
    """Return 'B' (salvage/repair-project) or 'A' (retail-grade)."""
    decl = decl or {}
    vision = vision or {}
    if decl.get("route_salvage") or vision.get("flood_or_frame_concern") is True:
        return "B"
    if "not_drivable" in (decl.get("remark_signals") or []):
        return "B"
    if clean_value and repair_est and repair_est.get("total_mid", 0) > HEAVY_DAMAGE_ROUTE_RATIO * clean_value:
        return "B"
    return "A"


def value_mode_a(base_value: int, condition_deduction_pct: float,
                 other_deltas_pct: float, mechanical_reserve: int = 0) -> dict:
    """
    Retail-grade value with guards (base_value in cents, value in cents out).
      condition_deduction_pct: total NEGATIVE % from condition+damage (e.g. -65.2)
      other_deltas_pct:        summed % of all NON-condition factors (mileage/history/market/location...)
      mechanical_reserve:      $ held back for known/unspecified mechanical risk
    """
    # Cap how much condition+damage alone can knock off the anchor.
    cap_pct = -CONDITION_DEDUCTION_CAP * 100
    capped_condition_pct = max(condition_deduction_pct, cap_pct)
    condition_capped = capped_condition_pct != condition_deduction_pct

    adjusted = base_value * (1 + other_deltas_pct / 100) * (1 + capped_condition_pct / 100)
    adjusted -= mechanical_reserve * 100                         # reserve in cents (base_value is cents)

    # A running vehicle has a wholesale/parts floor below which it won't sell.
    floor = int(base_value * SALVAGE_FLOOR_RATIO)
    floored = adjusted < floor
    final = max(int(adjusted), floor)

    return {
        "mode": "A",
        "final_value": final,
        "condition_capped": condition_capped,
        "floored": floored,
        "mechanical_reserve": mechanical_reserve,
        "floor": floor,
    }


def value_mode_b(clean_value: int, rebuilt: bool, repair_est: dict,
                 target_margin: int) -> dict:
    """
    Salvage / repair-project math (CAD cents in, cents out).
      after_fix = clean_value * title_factor
      project economics: after_fix - repair - margin = max you'd pay (pre fee/GST)
    """
    title_factor = TITLE_FACTOR_REBUILT if rebuilt else 1.0
    after_fix = int(clean_value * title_factor)
    repair = (repair_est.get("total_mid", 0) if repair_est else 0) * 100  # dollars -> cents
    parts_value = int(clean_value * PARTS_VALUE_RATIO)

    if repair >= after_fix:
        # Costs more to fix than it's worth fixed -> not a repair project.
        return {
            "mode": "B", "verdict": "PARTS_ONLY",
            "after_fix_value": after_fix, "repair_cost": int(repair),
            "parts_value": parts_value,
            "buy_to_fix_ceiling": 0,
            "reason": "Repair cost exceeds after-fix value — write-off; value is parts/scrap only.",
        }

    # Most you'd pay so the project still clears margin (before buyer fee + GST)
    buy_ceiling = after_fix - int(repair) - target_margin * 100
    return {
        "mode": "B", "verdict": "REPAIR_PROJECT" if buy_ceiling > 0 else "PASS_THIN_MARGIN",
        "after_fix_value": after_fix, "repair_cost": int(repair),
        "parts_value": parts_value,
        "buy_to_fix_ceiling": max(0, buy_ceiling),
        "reason": "After-fix value minus repair and margin sets the buy ceiling.",
    }
