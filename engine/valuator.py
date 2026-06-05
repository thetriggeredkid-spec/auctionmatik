"""
Valuator — Orchestrates all factor modules and produces a structured valuation.

Usage:
    from engine.valuator import valuate
    result = valuate(vehicle_spec, conn=conn)

vehicle_spec dict keys:
    # Identity
    year, make, model, trim, driveline, vehicle_type, fuel_type, odometer_km
    # Condition
    exterior_grade (1-5), interior_grade (1-5), mechanical_grade (1-5)
    damage_items: [{type, location, repair_cost_low, repair_cost_high}]
    # History
    accident_claim_amount, vehicle_value_at_incident, rebuilt_title,
    history_gap_post_accident, service_records, odometer_integrity, accident_type
    # Options/Mods
    options_present: [str], modifications: [str | {type, quality}]
    # Market context
    active_comp_count, seller_type, declarations, days_on_market, price_relative_to_comps
    # Location
    rust_free: bool
"""

import sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))

from engine.comps import get_comp_pool
from engine.retail_comps import get_retail_comp_pool
from engine.factors import mileage, condition, history, options, market_context, location, model_year

# Retail uncertainty band: mid ± this
RETAIL_UNCERTAINTY = 0.08

# Wholesale is derived FROM retail (not the other way)
# wholesale ≈ retail minus dealer margin and reconditioning — ~82% of retail
WHOLESALE_RATIO = 0.82
WHOLESALE_UNCERTAINTY = 0.05


def _near_total_loss_ceiling_compress(result: dict) -> dict:
    """If near-total-loss flag present, compress the retail high."""
    from engine.factors.history import NEAR_TOTAL_LOSS_CEILING_COMPRESS
    if result.get("near_total_loss"):
        compress = NEAR_TOTAL_LOSS_CEILING_COMPRESS
        result["retail_high"] = int(result["retail_high"] * (1 - compress))
        result["wholesale_high"] = int(result["wholesale_high"] * (1 - compress))
    return result


def valuate(vehicle: dict, conn=None, log_to_db: bool = False) -> dict:
    """
    Main valuation function.

    Returns a structured result dict with:
        base_median, adjusted_estimate, retail_{low,mid,high},
        wholesale_{low,mid,high}, confidence, comp_count,
        factor_breakdown (list), flags (list), comp_list (top 5)
    """
    # ── Step 1: Build comp pools ──────────────────────────────────────────
    # PRIMARY: Retail comps from Facebook Marketplace + Kijiji
    # These are active retail listings — asking prices reflect what the market expects.
    # FALLBACK: Regal sold comps (wholesale auction data) — used only when retail data
    # is sparse. If falling back, we treat Regal median as wholesale and back-calculate retail.
    retail_pool = get_retail_comp_pool(vehicle, conn=conn)
    wholesale_pool = get_comp_pool(vehicle, conn=conn)

    using_retail_primary = retail_pool.get("has_data") and retail_pool.get("retail_median")

    if using_retail_primary:
        # Retail comps are available — use as primary anchor
        base_median = retail_pool["retail_median"]
        comp_pool = retail_pool  # for mileage percentiles etc.
        comp_pool["comp_list"] = retail_pool["comp_list"]  # for display
        price_source = "retail_market"
    elif wholesale_pool.get("base_median"):
        # Fallback: derive retail from wholesale Regal auction data
        # wholesale_median / 0.82 → implied retail
        base_median = int(wholesale_pool["base_median"] / WHOLESALE_RATIO)
        comp_pool = wholesale_pool
        price_source = "wholesale_derived"
    else:
        return {
            "error": "Insufficient comp data to produce a valuation.",
            "comp_count": 0,
            "confidence": "low",
        }

    if not base_median:
        return {
            "error": "Insufficient comp data to produce a valuation.",
            "comp_count": comp_pool.get("comp_count", 0),
            "confidence": "low",
        }

    # ── Step 2: Apply each factor ─────────────────────────────────────────
    factor_results = []

    factor_results.append(model_year.evaluate(vehicle, comp_pool, base_median))
    factor_results.append(mileage.evaluate(vehicle, comp_pool, base_median))
    factor_results.append(condition.evaluate(vehicle, comp_pool, base_median))
    factor_results.append(history.evaluate(vehicle, comp_pool, base_median))
    factor_results.append(options.evaluate(vehicle, comp_pool, base_median))
    factor_results.append(market_context.evaluate(vehicle, comp_pool, base_median))
    factor_results.append(location.evaluate(vehicle, comp_pool, base_median))

    # ── Step 3: Multiply all deltas ───────────────────────────────────────
    # Flatten factor results including sub_factors for breakdown
    factor_breakdown = []
    all_flags = []
    near_total_loss = False
    hard_to_sell = False

    combined_multiplier = 1.0
    for fr in factor_results:
        delta_pct = fr.get("delta_pct", 0.0)
        combined_multiplier *= (1 + delta_pct / 100)

        # Collect flags
        for flag in fr.get("flags", []):
            all_flags.append(flag)

        if fr.get("near_total_loss"):
            near_total_loss = True
        if fr.get("hard_to_sell"):
            hard_to_sell = True

        # Add top-level factor to breakdown
        factor_breakdown.append({
            "factor": fr["factor"],
            "label": fr["label"],
            "delta_pct": fr["delta_pct"],
            "dollar_impact": fr["dollar_impact"],
            "reasoning": fr["reasoning"],
        })

        # Add sub-factors for full transparency
        for sf in fr.get("sub_factors", []):
            factor_breakdown.append({
                "factor": sf["factor"],
                "label": "  → " + sf["label"],
                "delta_pct": sf["delta_pct"],
                "dollar_impact": sf["dollar_impact"],
                "reasoning": sf.get("reasoning", ""),
                "_is_sub": True,
            })

    # ── Step 4: Build output price bands ─────────────────────────────────
    adjusted_estimate = int(base_median * combined_multiplier)

    retail_mid = adjusted_estimate
    retail_low = int(retail_mid * (1 - RETAIL_UNCERTAINTY))
    retail_high = int(retail_mid * (1 + RETAIL_UNCERTAINTY))

    wholesale_mid = int(retail_mid * WHOLESALE_RATIO)
    wholesale_low = int(wholesale_mid * (1 - WHOLESALE_UNCERTAINTY))
    wholesale_high = int(wholesale_mid * (1 + WHOLESALE_UNCERTAINTY))

    # Expand uncertainty range for low confidence
    confidence = comp_pool["confidence"]
    if confidence == "low":
        retail_low = int(retail_mid * 0.85)
        retail_high = int(retail_mid * 1.15)

    result = {
        "vehicle_summary": f"{vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')} "
                           f"{vehicle.get('trim', '')} {vehicle.get('driveline', '')}".strip(),
        "price_source": price_source,           # 'retail_market' | 'wholesale_derived'
        "retail_comp_count": retail_pool.get("comp_count", 0),
        "wholesale_comp_count": wholesale_pool.get("comp_count", 0),
        "base_median": base_median,
        "adjusted_estimate": adjusted_estimate,
        "combined_multiplier": combined_multiplier,
        "retail_low": retail_low,
        "retail_mid": retail_mid,
        "retail_high": retail_high,
        "wholesale_low": wholesale_low,
        "wholesale_mid": wholesale_mid,
        "wholesale_high": wholesale_high,
        "confidence": confidence,
        "comp_count": comp_pool["comp_count"],
        "fallback_used": comp_pool["fallback_used"],
        "factor_breakdown": factor_breakdown,
        "flags": all_flags,
        "near_total_loss": near_total_loss,
        "hard_to_sell": hard_to_sell or near_total_loss,
        "comp_list": comp_pool["comp_list"][:5],  # top 5 for display
    }

    # Apply near-total-loss ceiling compression
    if near_total_loss:
        result = _near_total_loss_ceiling_compress(result)

    # ── Step 5: Log to DB if requested ───────────────────────────────────
    if log_to_db and conn:
        _log_valuation(conn, vehicle, result)

    return result


def _log_valuation(conn, vehicle: dict, result: dict):
    import json
    try:
        from db.connection import get_cursor
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO valuations (
                source_table, source_id, contract, model_version,
                comp_count, comp_pool_desc, base_median,
                retail_low, retail_mid, retail_high,
                wholesale_low, wholesale_mid, wholesale_high,
                confidence, factor_breakdown, flags
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            vehicle.get("source_table", "regal_listings"),
            vehicle.get("source_id", 0),
            vehicle.get("contract"),
            "0.1",
            result["comp_count"],
            result["vehicle_summary"],
            result["base_median"],
            result["retail_low"], result["retail_mid"], result["retail_high"],
            result["wholesale_low"], result["wholesale_mid"], result["wholesale_high"],
            result["confidence"],
            json.dumps(result["factor_breakdown"]),
            json.dumps(result["flags"]),
        ))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Warning: failed to log valuation to DB: {e}")
