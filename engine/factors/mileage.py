"""
Mileage Factor
Compares the vehicle's odometer to the comp pool percentile distribution.

Input:
    vehicle: dict with odometer_km
    comp_pool: dict from engine.comps.get_comp_pool()

Output:
    {delta_pct, dollar_impact, reasoning, band, percentile}
"""


BAND_DELTAS = {
    "very_low":   +0.08,   # bottom 10th percentile
    "low":        +0.035,  # 10–30th percentile
    "average":    0.0,     # 30–70th percentile
    "high":       -0.06,   # 70–90th percentile
    "very_high":  -0.12,   # above 90th percentile
}

BAND_LABELS = {
    "very_low":  "Very low mileage (bottom 10% of comps)",
    "low":       "Low mileage (10–30th percentile of comps)",
    "average":   "Average mileage (30–70th percentile of comps)",
    "high":      "High mileage (70–90th percentile of comps)",
    "very_high": "Very high mileage (top 10% of comps)",
}


def _percentile_band(odometer_km: int, percentiles: dict) -> tuple[str, int | None]:
    """
    Returns (band_name, approximate_percentile).
    percentiles: {p10, p30, p50, p70, p90}
    """
    if not percentiles or odometer_km is None:
        return "average", None

    p10 = percentiles.get("p10", 0)
    p30 = percentiles.get("p30", 0)
    p70 = percentiles.get("p70", 0)
    p90 = percentiles.get("p90", 0)

    if odometer_km < p10:
        return "very_low", 5
    elif odometer_km < p30:
        return "low", 20
    elif odometer_km <= p70:
        return "average", 50
    elif odometer_km <= p90:
        return "high", 80
    else:
        return "very_high", 95


def evaluate(vehicle: dict, comp_pool: dict, base_price: int) -> dict:
    """
    Returns factor result dict.

    Args:
        vehicle:    vehicle spec dict (needs odometer_km)
        comp_pool:  result from engine.comps.get_comp_pool()
        base_price: base median in CAD cents
    """
    odometer_km = vehicle.get("odometer_km")
    percentiles = comp_pool.get("odometer_percentiles", {})

    if odometer_km is None:
        return {
            "factor": "mileage",
            "label": "Mileage unknown",
            "delta_pct": 0.0,
            "dollar_impact": 0,
            "reasoning": "Odometer not available — no mileage adjustment applied.",
            "band": None,
            "percentile": None,
        }

    band, approx_pct = _percentile_band(odometer_km, percentiles)
    delta_pct = BAND_DELTAS[band]
    dollar_impact = int(base_price * delta_pct)

    p50 = percentiles.get("p50")
    median_str = f"{p50:,} km" if p50 else "unknown median"
    odo_str = f"{odometer_km:,} km"

    reasoning = (
        f"{odo_str} vs. comp pool median {median_str}. "
        f"{BAND_LABELS[band]}."
    )

    return {
        "factor": "mileage",
        "label": BAND_LABELS[band],
        "delta_pct": delta_pct * 100,
        "dollar_impact": dollar_impact,
        "reasoning": reasoning,
        "band": band,
        "percentile": approx_pct,
    }
