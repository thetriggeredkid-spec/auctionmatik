"""
Condition Factor
Grades: exterior_grade, interior_grade, mechanical_grade (1–5 each)
Damage items: [{type, location, repair_cost_low, repair_cost_high}]

Grade baseline is 3 (average). Each grade level above/below 3 applies a delta.
Damage costs are deducted at 1.35x midpoint of repair range (buyer hassle premium).

Output:
    {delta_pct, dollar_impact, reasoning, sub_factors}
"""

# Grade deltas relative to grade 3 (average) baseline
# (exterior, interior, mechanical) — mechanical carries more weight
GRADE_DELTAS = {
    "exterior": {5: +0.04, 4: +0.02, 3: 0.0, 2: -0.03, 1: -0.06},
    "interior": {5: +0.03, 4: +0.015, 3: 0.0, 2: -0.02, 1: -0.04},
    "mechanical": {5: +0.05, 4: +0.025, 3: 0.0, 2: -0.04, 1: -0.08},
}

GRADE_LABELS = {5: "Exceptional", 4: "Above average", 3: "Average", 2: "Below average", 1: "Poor"}
DAMAGE_HASSLE_MULTIPLIER = 1.35


def _grade_factor(area: str, grade: int, base_price: int) -> dict:
    if grade not in GRADE_DELTAS[area]:
        grade = 3
    delta_pct = GRADE_DELTAS[area][grade]
    dollar_impact = int(base_price * delta_pct)
    label = GRADE_LABELS.get(grade, "Average")
    return {
        "factor": f"condition_{area}",
        "label": f"{label} {area} (grade {grade}/5)",
        "delta_pct": delta_pct * 100,
        "dollar_impact": dollar_impact,
        "reasoning": f"{area.capitalize()} graded {grade}/5 ({label}). "
                     f"{'Above' if grade > 3 else 'Below' if grade < 3 else 'At'} average baseline.",
    }


def _damage_factor(damage_items: list, base_price: int) -> dict:
    """
    Damage items: list of dicts with repair_cost_low and repair_cost_high.
    Deducted at 1.35x midpoint. Returns a single combined damage factor.
    """
    if not damage_items:
        return None

    total_deduction = 0
    item_descriptions = []

    for item in damage_items:
        low = item.get("repair_cost_low", 0) or 0
        high = item.get("repair_cost_high", 0) or 0
        midpoint = (low + high) / 2
        deduction = int(midpoint * DAMAGE_HASSLE_MULTIPLIER) * 100  # convert to cents
        total_deduction += deduction

        dtype = item.get("type", "damage")
        location = item.get("location", "unknown location")
        item_descriptions.append(
            f"{dtype} ({location}): ${low}–${high} repair → ${deduction/100:,.0f} deducted"
        )

    delta_pct = -total_deduction / base_price if base_price > 0 else 0.0

    return {
        "factor": "condition_damage",
        "label": f"Damage items ({len(damage_items)} item{'s' if len(damage_items) != 1 else ''})",
        "delta_pct": delta_pct * 100,
        "dollar_impact": -total_deduction,
        "reasoning": (
            f"Repair costs deducted at {DAMAGE_HASSLE_MULTIPLIER}x midpoint (buyer hassle premium). "
            + " | ".join(item_descriptions)
        ),
        "damage_items": damage_items,
        "total_deduction_cents": total_deduction,
    }


def evaluate(vehicle: dict, comp_pool: dict, base_price: int) -> dict:
    """
    Args:
        vehicle: needs exterior_grade, interior_grade, mechanical_grade, damage_items
        comp_pool: not used directly but passed for consistency
        base_price: base median in CAD cents

    Returns combined condition factor with sub_factors list.
    """
    ext_grade = int(vehicle.get("exterior_grade") or 3)
    int_grade = int(vehicle.get("interior_grade") or 3)
    mec_grade = int(vehicle.get("mechanical_grade") or 3)
    damage_items = vehicle.get("damage_items") or []

    sub_factors = [
        _grade_factor("exterior", ext_grade, base_price),
        _grade_factor("interior", int_grade, base_price),
        _grade_factor("mechanical", mec_grade, base_price),
    ]

    damage_result = _damage_factor(damage_items, base_price)
    if damage_result:
        sub_factors.append(damage_result)

    total_delta_pct = sum(sf["delta_pct"] for sf in sub_factors)
    total_dollar = sum(sf["dollar_impact"] for sf in sub_factors)

    reasoning_parts = [
        f"Exterior {ext_grade}/5, Interior {int_grade}/5, Mechanical {mec_grade}/5."
    ]
    if damage_items:
        reasoning_parts.append(f"{len(damage_items)} damage item(s) recorded.")

    return {
        "factor": "condition",
        "label": "Condition assessment",
        "delta_pct": total_delta_pct,
        "dollar_impact": total_dollar,
        "reasoning": " ".join(reasoning_parts),
        "sub_factors": sub_factors,
    }
