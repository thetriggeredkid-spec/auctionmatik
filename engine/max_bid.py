"""
Max Bid Calculator
Given a retail estimate, calculates the maximum bid at each margin tier
accounting for Regal buyer fees and 5% Alberta GST.

Formula: max_bid = (retail_mid - margin - buyer_fee) / 1.05

Usage:
    from engine.max_bid import calculate
    result = calculate(retail_mid_cents=1450000)
"""

# Regal fee schedule as (price_low, price_high, fee) bands, all in CAD dollars.
# A band matches when price_low <= price < price_high (high bound is exclusive).
REGAL_FEE_SCHEDULE = [
    (0,       5_000,   285),
    (5_000,   10_000,  385),
    (10_000,  15_000,  535),
    (15_000,  25_000,  685),
    (25_000,  40_000,  835),
    (40_000,  float("inf"), 985),
]

GST_RATE = 0.05  # 5% Alberta GST on (purchase price + buyer fee)

# Margin tiers as (sell_low, sell_high, margin, label), in CAD dollars.
# The tier is selected from the estimated retail sell price using
# sell_low <= price < sell_high (high bound is exclusive).
MARGIN_TIERS = [
    (0,       15_000,  1_500,  "Tier 1 (<$15k sell)"),
    (15_000,  20_000,  2_500,  "Tier 2 ($15k–$20k sell)"),
    (20_000,  35_000,  3_500,  "Tier 3 ($20k–$35k sell)"),
    (35_000,  float("inf"), 5_000, "Tier 4 ($35k+ sell)"),
]


def get_buyer_fee(price_dollars: float) -> int:
    """Return the Regal buyer fee in dollars for a given purchase price."""
    for low, high, fee in REGAL_FEE_SCHEDULE:
        if low <= price_dollars < high:
            return fee
    # Unreachable for non-negative prices (last band runs to infinity);
    # fall back to the top band's fee as a safety net.
    return REGAL_FEE_SCHEDULE[-1][2]


def get_margin(retail_mid_dollars: float) -> tuple[int, str]:
    """Return (margin_dollars, tier_label) for a given retail mid price."""
    for low, high, margin, label in MARGIN_TIERS:
        if low <= retail_mid_dollars < high:
            return margin, label
    # Unreachable for non-negative prices (last tier runs to infinity);
    # fall back to the top tier as a safety net.
    _, _, top_margin, top_label = MARGIN_TIERS[-1]
    return top_margin, top_label


def calculate_single(retail_mid_cents: int, margin_dollars: int) -> dict:
    """
    Calculate max bid for a single margin level.

    The buyer fee depends on the bid price, which in turn depends on the fee,
    so we solve it iteratively: seed the fee from a rough bid estimate, compute
    a max bid, then refine the fee once against that max bid.

    Returns:
        {max_bid_cents, max_bid_dollars, buyer_fee, margin, gst_estimate, total_cost_at_max_bid}
    """
    retail_mid_dollars = retail_mid_cents / 100

    def max_bid_for_fee(fee: int) -> float:
        """Solve the max-bid formula for a given buyer fee, floored at zero."""
        bid = (retail_mid_dollars - margin_dollars - fee) / (1 + GST_RATE)
        return max(bid, 0)

    # Seed the fee from a rough bid estimate (~$700 stands in for the fee).
    rough_bid = max(retail_mid_dollars - margin_dollars - 700, 0)
    buyer_fee = get_buyer_fee(rough_bid)

    # Refine the fee against the resulting max bid, then recompute the bid.
    buyer_fee = get_buyer_fee(max_bid_for_fee(buyer_fee))
    max_bid_dollars = max_bid_for_fee(buyer_fee)

    gst = (max_bid_dollars + buyer_fee) * GST_RATE
    total_cost = max_bid_dollars + buyer_fee + gst

    return {
        "max_bid_cents": int(max_bid_dollars * 100),
        "max_bid_dollars": round(max_bid_dollars, 0),
        "buyer_fee": buyer_fee,
        "margin": margin_dollars,
        "gst_estimate": round(gst, 0),
        "total_cost_at_max_bid": round(total_cost, 0),
    }


def calculate(retail_mid_cents: int) -> dict:
    """
    Calculate max bid at all four margin tiers.

    Returns:
        {
            retail_mid_dollars,
            default_margin, default_tier_label,
            buyer_fee_at_mid,
            tier1, tier2, tier3, tier4   # each is a calculate_single result
        }
    """
    retail_mid_dollars = retail_mid_cents / 100
    default_margin, default_tier_label = get_margin(retail_mid_dollars)

    tiers = {}
    for tier_number, (_low, _high, margin, label) in enumerate(MARGIN_TIERS, start=1):
        tiers[f"tier{tier_number}"] = {
            "label": label,
            "margin": margin,
            **calculate_single(retail_mid_cents, margin),
        }

    return {
        "retail_mid_dollars": retail_mid_dollars,
        "default_margin": default_margin,
        "default_tier_label": default_tier_label,
        "buyer_fee_at_mid": get_buyer_fee(retail_mid_dollars),
        **tiers,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--retail", type=float, required=True, help="Retail mid price in dollars")
    args = parser.parse_args()

    result = calculate(int(args.retail * 100))
    print(f"\nRetail mid: ${result['retail_mid_dollars']:,.0f}")
    print(f"Default tier: {result['default_tier_label']}")
    print()
    for tier_number in range(1, 5):
        tier = result[f"tier{tier_number}"]
        print(f"  {tier['label']}: max bid ${tier['max_bid_dollars']:,.0f} "
              f"(fee ${tier['buyer_fee']}, margin ${tier['margin']:,}, "
              f"GST ${tier['gst_estimate']:,.0f})")
