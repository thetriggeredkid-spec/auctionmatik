"""
Market Context Factor
Assesses active supply dynamics, seller type signals, and days-on-market.

Inputs (from vehicle dict):
    active_comp_count:          int — how many similar vehicles are listed right now
    seller_type:                str — from Regal API field
    declarations:               str — from Regal API (e.g. 'FR' = Finance Repo)
    days_on_market:             int — days since listed
    price_relative_to_comps:    float — pct above (+) or below (-) comp median
                                        e.g. -0.10 means 10% below median

Output:
    {delta_pct, dollar_impact, reasoning, flags, sub_factors}
"""

# Supply pressure thresholds (number of active comparable listings)
SUPPLY_BANDS = [
    (0,  3,  +0.06, "Very low supply — seller's market"),
    (4,  7,  +0.03, "Low supply — mild seller advantage"),
    (8, 15,   0.0,  "Normal supply — balanced market"),
    (16, 30, -0.03, "High supply — buyer has options"),
    (31, 9999, -0.06, "Very high supply — buyer's market"),
]

# Days-on-market penalty: -0.2% per day after 14 days
DOM_FREE_DAYS = 14
DOM_PENALTY_PER_DAY = -0.002

# Finance Repo: NOT a value penalty. At Regal these are same-day / quick release —
# a motivated-SELLER (buy-side) signal, not a hold burden or a resale-value defect.
# Charles (domain expert): do not penalize a finance repo. Kept as an informational
# 0% signal only.
FR_DELTA = 0.0

# Dealer-at-auction signal (retail failed)
DEALER_AUCTION_DELTA = -0.04


def _supply_factor(active_comp_count: int, base_price: int) -> dict | None:
    if active_comp_count is None:
        return None
    for low, high, delta, label in SUPPLY_BANDS:
        if low <= active_comp_count <= high:
            return {
                "factor": "market_supply",
                "label": label,
                "delta_pct": delta * 100,
                "dollar_impact": int(base_price * delta),
                "reasoning": f"{active_comp_count} active comparable listings. {label}.",
            }
    return None


def evaluate(vehicle: dict, comp_pool: dict, base_price: int) -> dict:
    active_comp_count = vehicle.get("active_comp_count")
    seller_type = (vehicle.get("seller_type") or "").upper()
    declarations = (vehicle.get("declarations") or "").upper()
    days_on_market = vehicle.get("days_on_market") or 0
    price_relative = vehicle.get("price_relative_to_comps") or 0.0

    sub_factors = []
    flags = []

    # ── Supply dynamics ───────────────────────────────────────────────────
    supply_sf = _supply_factor(active_comp_count, base_price)
    if supply_sf:
        sub_factors.append(supply_sf)

    # ── Seller urgency signals ────────────────────────────────────────────
    # Finance Repo
    if "FR" in declarations or "FINANCE REPO" in declarations or "REPO" in declarations:
        sub_factors.append({
            "factor": "seller_urgency",
            "label": "Finance Repo (motivated seller)",
            "delta_pct": FR_DELTA * 100,
            "dollar_impact": int(base_price * FR_DELTA),
            "reasoning": "Declared Finance Repo — same-day/quick release at Regal; motivated seller "
                         "(buy-side signal). No resale-value penalty applied.",
        })
        flags.append({
            "code": "finance_repo",
            "severity": "low",
            "message": "Finance Repo — quick same-day release, motivated seller (priced to move). "
                       "Not a value defect or a hold-time penalty.",
        })

    # Dealer listing at auction (retail exit failure signal)
    dealer_types = {"DEALER", "DEALERSHIP", "FLEET", "BROKER", "WHOLESALE"}
    is_dealer = any(dt in seller_type for dt in dealer_types)
    if is_dealer:
        sub_factors.append({
            "factor": "dealer_at_auction",
            "label": "Dealer selling through auction",
            "delta_pct": DEALER_AUCTION_DELTA * 100,
            "dollar_impact": int(base_price * DEALER_AUCTION_DELTA),
            "reasoning": "Dealer/fleet selling at auction suggests retail channel failed. "
                         "Seller likely willing to exit at or near breakeven.",
        })
        flags.append({
            "code": "dealer_at_auction",
            "severity": "low",
            "message": "Dealer/fleet listing at auction — retail exit failure signal.",
        })

    # ── Days on market ────────────────────────────────────────────────────
    if days_on_market and days_on_market > DOM_FREE_DAYS:
        extra_days = days_on_market - DOM_FREE_DAYS
        dom_delta = DOM_PENALTY_PER_DAY * extra_days
        dom_delta = max(dom_delta, -0.15)  # cap at -15%
        sub_factors.append({
            "factor": "days_on_market",
            "label": f"Days on market: {days_on_market} days",
            "delta_pct": dom_delta * 100,
            "dollar_impact": int(base_price * dom_delta),
            "reasoning": f"{days_on_market} days listed. {extra_days} days past 14-day threshold "
                         f"→ {dom_delta*100:.1f}% discount applied.",
        })

    # ── Price relative to comps ───────────────────────────────────────────
    if abs(price_relative) > 0.15:
        direction = "above" if price_relative > 0 else "below"
        if price_relative < -0.15:
            # Significantly below median — investigate for hidden issues
            flags.append({
                "code": "priced_well_below_comps",
                "severity": "medium",
                "message": f"Listed {abs(price_relative)*100:.0f}% below comp median. "
                           f"Investigate for hidden defects — or genuine motivated seller.",
            })
        elif price_relative > 0.15:
            flags.append({
                "code": "priced_above_comps",
                "severity": "low",
                "message": f"Listed {price_relative*100:.0f}% above comp median. "
                           f"Seller has leverage expectations.",
            })

    total_delta_pct = sum(sf["delta_pct"] for sf in sub_factors)
    total_dollar = sum(sf["dollar_impact"] for sf in sub_factors)

    reasoning_parts = []
    if active_comp_count is not None:
        reasoning_parts.append(f"{active_comp_count} active comps")
    if days_on_market:
        reasoning_parts.append(f"{days_on_market}d on market")
    if not reasoning_parts:
        reasoning_parts.append("No market context data")

    return {
        "factor": "market_context",
        "label": "Market context",
        "delta_pct": total_delta_pct,
        "dollar_impact": total_dollar,
        "reasoning": " | ".join(reasoning_parts),
        "flags": flags,
        "sub_factors": sub_factors,
    }
