"""
Max Bid Calculator
Given a retail estimate, calculates the maximum bid at each margin tier
accounting for Regal buyer fees and 5% Alberta GST.

Formula: max_bid = (retail_mid - margin - buyer_fee) / 1.05

Usage:
    from engine.max_bid import calculate
    result = calculate(retail_mid_cents=1450000)
"""

# Regal fee schedule (price ranges and fees in CAD dollars)
# price_max is the upper bound of the range (exclusive)
REGAL_FEE_SCHEDULE = [
    (0,       5_000,   285),
    (5_000,   10_000,  385),
    (10_000,  15_000,  535),
    (15_000,  25_000,  685),
    (25_000,  40_000,  835),
    (40_000,  float("inf"), 985),
]

GST_RATE = 0.05  # 5% Alberta GST on (purchase price + buyer fee)

# Margin tiers: (sell_price_threshold_dollars, margin_dollars)
# The tier is selected based on estimated retail sell price
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
    return 985  # fallback to highest tier


def get_margin(retail_mid_dollars: float) -> tuple[int, str]:
    """Return (margin_dollars, tier_label) for a given retail mid price."""
    for low, high, margin, label in MARGIN_TIERS:
        if low <= retail_mid_dollars < high:
            return margin, label
    return 5_000, "Tier 4 ($35k+ sell)"


def calculate_single(retail_mid_cents: int, margin_dollars: int) -> dict:
    """
    Calculate max bid for a single margin level.

    Returns:
        {max_bid_cents, max_bid_dollars, buyer_fee, margin, gst_estimate, total_cost_at_max_bid}
    """
    retail_mid_dollars = retail_mid_cents / 100

    # Buyer fee is based on the max bid price (iterative approximation)
    # Since fee depends on bid price, we estimate: start with mid estimate
    estimated_bid = max(retail_mid_dollars - margin_dollars - 700, 0)  # rough start
    buyer_fee = get_buyer_fee(estimated_bid)

    max_bid_dollars = (retail_mid_dollars - margin_dollars - buyer_fee) / (1 + GST_RATE)
    max_bid_dollars = max(max_bid_dollars, 0)

    # Recalculate fee with refined bid
    buyer_fee = get_buyer_fee(max_bid_dollars)
    max_bid_dollars = (retail_mid_dollars - margin_dollars - buyer_fee) / (1 + GST_RATE)
    max_bid_dollars = max(max_bid_dollars, 0)

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
            tier1, tier2, tier3, tier4   # each is a calculate_single result
        }
    """
    retail_mid_dollars = retail_mid_cents / 100
    default_margin, default_tier_label = get_margin(retail_mid_dollars)

    tiers = {}
    for i, (low, high, margin, label) in enumerate(MARGIN_TIERS, 1):
        tiers[f"tier{i}"] = {
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
    for i in range(1, 5):
        t = result[f"tier{i}"]
        print(f"  {t['label']}: max bid ${t['max_bid_dollars']:,.0f} "
              f"(fee ${t['buyer_fee']}, margin ${t['margin']:,}, GST ${t['gst_estimate']:,.0f})")
