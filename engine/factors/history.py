"""
History Factor
Handles accident history, rebuilt title, service records, and odometer integrity.

Inputs (from vehicle dict):
    accident_claim_amount:     int (CAD dollars — the claim amount from report)
    vehicle_value_at_incident: int (CAD dollars — estimated vehicle value when incident occurred)
    rebuilt_title:             bool
    history_gap_post_accident: bool (service records gap following accident)
    service_records:           str — 'full_dealer' | 'mixed' | 'third_party' | 'self' | 'sparse' | 'none'
    odometer_integrity:        str — 'clean' | 'risk' | 'high_risk'
    accident_type:             str — 'none' | 'minor' | 'major' | 'unknown'

Output:
    {delta_pct, dollar_impact, reasoning, flags, sub_factors}
"""

# Accident claim deduction: 1/3 to 1/2 of claim amount
CLAIM_DEDUCTION_RATIO_LOW = 1 / 3
CLAIM_DEDUCTION_RATIO_HIGH = 1 / 2
CLAIM_DEDUCTION_RATIO = (CLAIM_DEDUCTION_RATIO_LOW + CLAIM_DEDUCTION_RATIO_HIGH) / 2  # midpoint ~0.417

NEAR_TOTAL_LOSS_THRESHOLD = 0.70  # claim >= 70% of vehicle value at time
NEAR_TOTAL_LOSS_CEILING_COMPRESS = 0.25  # compress high end by 25%

REBUILT_TITLE_DELTA = -0.25  # -25% for rebuilt title

SERVICE_RECORD_DELTAS = {
    "full_dealer":   +0.03,
    "mixed":          0.0,
    "third_party":   -0.01,
    "self":          -0.02,
    "sparse":        -0.04,
    "none":          -0.05,
    "unknown":        0.0,   # a Carfax/history report exists but we haven't read it — don't assume the worst
}

ODOMETER_INTEGRITY_DELTAS = {
    "clean":      0.0,
    "risk":      -0.05,
    "high_risk": -0.10,
}


def evaluate(vehicle: dict, comp_pool: dict, base_price: int) -> dict:
    sub_factors = []
    flags = []
    hard_to_sell = False

    claim = (vehicle.get("accident_claim_amount") or 0)
    vv_at_incident = (vehicle.get("vehicle_value_at_incident") or 0)
    rebuilt = bool(vehicle.get("rebuilt_title"))
    history_gap = bool(vehicle.get("history_gap_post_accident"))
    service = vehicle.get("service_records") or "none"
    odo_integrity = vehicle.get("odometer_integrity") or "clean"
    accident_type = vehicle.get("accident_type") or "none"

    # ── Accident history ──────────────────────────────────────────────────
    if claim > 0:
        deduction_dollars = int(claim * CLAIM_DEDUCTION_RATIO)
        deduction_cents = deduction_dollars * 100
        delta_pct = -deduction_cents / base_price if base_price > 0 else 0.0

        near_total = False
        if vv_at_incident > 0:
            damage_ratio = claim / vv_at_incident
            near_total = damage_ratio >= NEAR_TOTAL_LOSS_THRESHOLD
        elif claim > 0 and base_price > 0:
            # Rough approximation if no historical value given
            damage_ratio = (claim * 100) / base_price
            near_total = damage_ratio >= NEAR_TOTAL_LOSS_THRESHOLD

        reasoning = (
            f"${claim:,} accident claim → ${deduction_dollars:,} deduction "
            f"(~{CLAIM_DEDUCTION_RATIO*100:.0f}% of claim amount)."
        )

        if near_total:
            hard_to_sell = True
            flags.append({
                "code": "near_total_loss",
                "severity": "high",
                "message": f"Claim amount is ≥70% of vehicle value at time of incident. "
                           f"Ceiling compressed by {int(NEAR_TOTAL_LOSS_CEILING_COMPRESS*100)}%. "
                           f"Reduced buyer pool — expect extended days-on-market.",
            })
            reasoning += " NEAR-TOTAL-LOSS: ceiling compressed."

        if history_gap:
            flags.append({
                "code": "history_gap_post_accident",
                "severity": "medium",
                "message": "Service record gap following accident suggests off-books repair. "
                           "Repair quality cannot be verified.",
            })
            # Apply additional trust discount
            deduction_cents += int(base_price * 0.02)
            reasoning += " Off-books repair discount applied."

        sub_factors.append({
            "factor": "accident_claim",
            "label": f"Accident claim: ${claim:,}",
            "delta_pct": delta_pct * 100,
            "dollar_impact": -deduction_cents,
            "reasoning": reasoning,
            "near_total_loss": near_total,
        })

    elif accident_type in ("minor", "major"):
        # No dollar amount but type is known
        if accident_type == "minor":
            delta_pct = -0.05
            label = "Minor accident history (no claim amount provided)"
        else:
            delta_pct = -0.18
            label = "Major accident history — structural/airbag (no claim amount provided)"
            flags.append({
                "code": "major_accident",
                "severity": "high",
                "message": "Major structural or airbag deployment accident. Permanent discount applies.",
            })
        sub_factors.append({
            "factor": "accident_type",
            "label": label,
            "delta_pct": delta_pct * 100,
            "dollar_impact": int(base_price * delta_pct),
            "reasoning": label,
        })

    # ── Rebuilt title ─────────────────────────────────────────────────────
    if rebuilt:
        hard_to_sell = True
        dollar_impact = int(base_price * REBUILT_TITLE_DELTA)
        flags.append({
            "code": "rebuilt_title",
            "severity": "high",
            "message": "Rebuilt title drastically narrows buyer pool. Many buyers refuse rebuilt titles entirely.",
        })
        sub_factors.append({
            "factor": "rebuilt_title",
            "label": "Rebuilt title",
            "delta_pct": REBUILT_TITLE_DELTA * 100,
            "dollar_impact": dollar_impact,
            "reasoning": "Rebuilt title. Independent of claim amount — buyer pool severely restricted.",
        })

    # ── Service records ───────────────────────────────────────────────────
    svc_delta = SERVICE_RECORD_DELTAS.get(service, 0.0)
    if svc_delta != 0.0 or service == "full_dealer":
        svc_labels = {
            "full_dealer":  "Full dealer service history",
            "mixed":        "Mixed dealer + third-party service history",
            "third_party":  "Third-party service only",
            "self":         "Self-serviced (owner-maintained)",
            "sparse":       "Sparse service records",
            "none":         "No service records",
        }
        sub_factors.append({
            "factor": "service_records",
            "label": svc_labels.get(service, service),
            "delta_pct": svc_delta * 100,
            "dollar_impact": int(base_price * svc_delta),
            "reasoning": svc_labels.get(service, service),
        })

    # ── Odometer integrity ────────────────────────────────────────────────
    odo_delta = ODOMETER_INTEGRITY_DELTAS.get(odo_integrity, 0.0)
    if odo_delta != 0.0:
        flags.append({
            "code": "odometer_integrity_risk",
            "severity": "medium" if odo_integrity == "risk" else "high",
            "message": "Odometer integrity concerns detected. Mileage benefit discounted.",
        })
        sub_factors.append({
            "factor": "odometer_integrity",
            "label": f"Odometer integrity: {odo_integrity.replace('_', ' ')}",
            "delta_pct": odo_delta * 100,
            "dollar_impact": int(base_price * odo_delta),
            "reasoning": "Rollback risk signals detected — confidence discount applied to mileage.",
        })

    if hard_to_sell:
        flags.append({
            "code": "hard_to_sell",
            "severity": "high",
            "message": "This vehicle has characteristics that significantly restrict the buyer pool.",
        })

    total_delta_pct = sum(sf["delta_pct"] for sf in sub_factors)
    total_dollar = sum(sf["dollar_impact"] for sf in sub_factors)

    reasoning_parts = []
    if not sub_factors:
        reasoning_parts.append("No significant history concerns.")
    else:
        for sf in sub_factors:
            reasoning_parts.append(sf["label"])

    return {
        "factor": "history",
        "label": "Vehicle history",
        "delta_pct": total_delta_pct,
        "dollar_impact": total_dollar,
        "reasoning": " | ".join(reasoning_parts),
        "flags": flags,
        "sub_factors": sub_factors,
        "hard_to_sell": hard_to_sell,
        "near_total_loss": any(f["code"] == "near_total_loss" for f in flags),
    }
