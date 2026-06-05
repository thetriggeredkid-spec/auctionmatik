"""
Recommendation Engine ("Advisor") — Theme 7
Turns the analysis (declarations, vision, repair estimate, comp-scrutiny anchor,
valuation mode) into an actionable recommendation for a specific user:

    VERDICT (PASS / BID / BID-TO-FIX) + tailored max bid
    deal thesis · verify-before-bidding · recon ROI plan · sale plan
    profit projection · cross-profile ("worth $X to a mechanic")

It does NOT re-derive value — callers pass the as-is anchor (Mode A) and a clean
after-fix value (Mode B). Reuses engine.max_bid for fee/GST/margin.
"""

from engine.max_bid import get_buyer_fee, get_margin, GST_RATE
from engine.valuation_modes import route_mode, TITLE_FACTOR_REBUILT, MECHANICAL_RESERVE_UNKNOWN
from engine.repair_estimate import estimate_repair

# Buyer profiles. margin = max(floor, tier_margin × scale).
#   mech_reserve_factor: scales the unknown-mechanical reserve (a DIY mechanic holds back less).
#   repair {small_factor, large_factor}: sourcing/labour cost multipliers passed to estimate_repair
#     (small bolt-on jobs vs big/structural; used-parts/DIY profiles drop large_factor below 1.0).
PROFILES = {
    "charles":  {"label": "Charles (flipper)", "margin_floor": 1500, "margin_scale": 1.0,
                 "repair_buffer": 0.20, "hold_time": "low", "diy": "some",
                 "mech_reserve_factor": 1.0, "repair": {"small_factor": 0.65, "large_factor": 1.0}},
    "mechanic": {"label": "DIY mechanic",      "margin_floor": 800,  "margin_scale": 0.5,
                 "repair_buffer": 0.15, "hold_time": "high", "diy": "full",
                 "mech_reserve_factor": 0.2, "repair": {"small_factor": 0.50, "large_factor": 0.55}},
}

LOW_VALUE_THRESHOLD = 4000   # below this (as-is $), sell as-is — don't chase cosmetic recon
MIN_VIABLE_BID      = 300    # max bid under this ⇒ "not worth the effort"


def _margin(profile: dict, sale_dollars: float) -> int:
    tier_margin, _ = get_margin(sale_dollars)
    return int(max(profile["margin_floor"], tier_margin * profile["margin_scale"]))


def _max_bid_cents(expected_sale_cents: int, deductions_cents: int, profile: dict) -> dict:
    """max_bid = (sale − recon/repair − margin − buyer_fee) / 1.05 ; floored at 0."""
    sale = expected_sale_cents / 100
    deductions = deductions_cents / 100
    margin = _margin(profile, sale)
    net = sale - deductions - margin  # proceeds before buyer fee + GST

    # Buyer fee depends on the bid price, so iterate like max_bid.calculate_single:
    # seed the fee from a rough bid, then recompute once it converges.
    seed_bid = max(net - 700, 0)
    fee = get_buyer_fee(seed_bid)
    bid = max((net - fee) / (1 + GST_RATE), 0)
    fee = get_buyer_fee(bid)
    bid = max((net - fee) / (1 + GST_RATE), 0)
    return {"max_bid_cents": int(bid * 100), "margin": margin, "buyer_fee": fee}


def _recon_plan(anchor_cents: int, decl: dict, vision: dict, profile: dict) -> dict:
    """Decide which work to do (ROI) and the held-back reserve. Returns plan + total cost."""
    anchor = anchor_cents / 100
    repair_cfg = profile["repair"]
    items = []
    cost_cents = 0

    # Unknown/declared mechanical → reserve (held back from the bid, not 'value-add').
    # Profile-aware: a DIY mechanic fixes it cheap, so holds back far less than a flipper.
    mech_reserve = 0
    if decl.get("mechanical_risk"):
        mech_reserve = int(MECHANICAL_RESERVE_UNKNOWN * profile.get("mech_reserve_factor", 1.0))
        items.append({"work": "Mechanical reserve (unknown/declared issue)", "cost": mech_reserve,
                      "decision": "RESERVE", "why": "Unspecified mechanical risk — hold this back from your bid."})
        cost_cents += mech_reserve * 100

    # Cosmetic recon from vision damage — only do it if the value tier justifies the ROI.
    damage = (vision or {}).get("damage_details") or []
    if damage:
        cosmetic = estimate_repair(
            [{"component": d.get("panel", ""), "action": "repair", "severity": d.get("severity")} for d in damage],
            buffer=profile["repair_buffer"],
            small_factor=repair_cfg["small_factor"], large_factor=repair_cfg["large_factor"])
        cosmetic_mid = (cosmetic["total_low"] + cosmetic["total_high"]) // 2
        work_label = f"Cosmetic repairs ({len(damage)} item/s)"
        if anchor < LOW_VALUE_THRESHOLD:
            items.append({"work": work_label, "cost": cosmetic_mid,
                          "decision": "SKIP", "why": "Low-value unit — sell as-is; repairs won't return their cost."})
        else:
            items.append({"work": work_label, "cost": cosmetic_mid,
                          "decision": "DO", "why": "Worth it on this value tier for saleability/curb appeal."})
            cost_cents += cosmetic_mid * 100

    return {"items": items, "cost_cents": cost_cents, "mechanical_reserve": mech_reserve}


# Claims deduction (Charles's rule): the deduction is a FRACTION of the claim amount,
# and the fraction shrinks as the vehicle gets cheaper (a $20k claim on a $5k Civic
# barely moves it). Capped at a % of value so cheap cars never get gutted by a big claim.
# Calibrated to: clean Wrangler ~$15,750, CH $15–20k → ~$1,750 off → ~$14,000. TUNABLE.
def _claim_fraction(value_dollars: float) -> float:
    if value_dollars < 8000:
        return 0.05
    if value_dollars < 20000:
        return 0.10
    if value_dollars < 35000:
        return 0.18
    return 0.25


def _value_cap(value_dollars: float) -> float:
    return 0.03 if value_dollars < 8000 else 0.12   # max deduction as % of value


def _history_deduction(decl: dict, carfax: dict | None, value_cents: int) -> tuple[int, str]:
    """Dollar deduction (cents) for accident/claims history. Carfax (precise) overrides the
    CH claims-total band. Applied to the CLEAN value so we don't double-count the comp anchor."""
    value = max(value_cents / 100, 1)

    # Prefer a precise Carfax claim total; otherwise fall back to the CH declaration band.
    claim = None
    if carfax and carfax.get("total_claims_cad"):
        claim = carfax["total_claims_cad"]
    elif decl.get("claims_total_low"):
        claim = decl["claims_total_low"] + 2500   # CH band midpoint (e.g. CH15000 → ~$17.5k)

    # No dollar claim figure: deduct per Carfax accident count if we have one.
    if claim is None:
        if carfax and carfax.get("accidents_reported"):
            accidents = carfax["accidents_reported"]
            deduction = min(_value_cap(value) * value, 1500 * accidents)
            return int(deduction * 100), f"Carfax: {accidents} accident(s)"
        return 0, ""

    # Deduct a value-scaled fraction of the claim, capped at a % of vehicle value.
    fraction = _claim_fraction(value)
    cap = _value_cap(value) * value
    deduction = min(claim * fraction, cap)
    is_capped = deduction >= cap
    reason = f"claim ~${claim:,.0f} × {int(fraction * 100)}% (cheaper-car-scaled)"
    if is_capped:
        reason += f", capped at {int(_value_cap(value) * 100)}% of value"
    return int(deduction * 100), reason


def advise(subject: dict, *, anchor_cents: int, clean_value_cents: int | None,
           decl: dict, vision: dict, carfax: dict | None = None,
           profile_key: str = "charles") -> dict:
    profile = PROFILES[profile_key]
    repair_cfg = profile["repair"]
    # Repair quote is profile-aware: used-parts/DIY profiles price the big jobs cheaper.
    repair_est = estimate_repair((vision or {}).get("repair_components") or [],
                                 buffer=profile["repair_buffer"],
                                 small_factor=repair_cfg["small_factor"],
                                 large_factor=repair_cfg["large_factor"])
    clean_value_cents = clean_value_cents or anchor_cents
    mode = route_mode(decl, vision, repair_est, clean_value_cents)
    verify = list(decl.get("verify_before_bid") or [])
    hist_ded, hist_reason = 0, ""

    if mode == "B":
        rebuilt = decl.get("rebuilt")
        after_fix = int(clean_value_cents * (TITLE_FACTOR_REBUILT if rebuilt else 1.0))
        hist_ded, hist_reason = _history_deduction(decl, carfax, after_fix)
        after_fix -= hist_ded  # pre-existing claims/accidents reduce after-fix resale
        repair_cents = (repair_est.get("total_mid", 0) if repair_est else 0) * 100
        if repair_cents >= after_fix:
            verdict, max_bid = "PARTS_ONLY / PASS", 0
            thesis = (f"Repair ~${repair_cents/100:,.0f} exceeds after-fix value ~${after_fix/100:,.0f}"
                      f"{' (rebuilt title)' if rebuilt else ''} — write-off; parts/scrap only.")
        else:
            mb = _max_bid_cents(after_fix, repair_cents, profile)
            max_bid = mb["max_bid_cents"]
            verdict = "BID-TO-FIX" if max_bid >= MIN_VIABLE_BID * 100 else "PASS (thin margin)"
            thesis = (f"Buy-to-fix: after-fix ~${after_fix/100:,.0f}"
                      f"{' (rebuilt ×0.78)' if rebuilt else ''} − repair ~${repair_cents/100:,.0f} "
                      f"− margin ${mb['margin']:,} − Regal fee ${mb['buyer_fee']:,} & 5% GST "
                      f"⇒ bid ≤ ${max_bid/100:,.0f}.")
        recon = {"items": [{"work": "Full repair (see component quote)",
                            "cost": repair_cents // 100, "decision": "REQUIRED", "why": "Salvage project."}],
                 "cost_cents": repair_cents, "mechanical_reserve": 0}
        expected_sale = after_fix
    else:
        recon = _recon_plan(anchor_cents, decl, vision, profile)
        hist_ded, hist_reason = _history_deduction(decl, carfax, anchor_cents)
        expected_sale = anchor_cents - hist_ded
        mb = _max_bid_cents(expected_sale, recon["cost_cents"], profile)
        max_bid = mb["max_bid_cents"]
        verdict = "BID" if max_bid >= MIN_VIABLE_BID * 100 else "PASS (not worth the effort)"
        thesis = (f"As-is flip: sells ~${expected_sale/100:,.0f}, "
                  f"recon/reserve ${recon['cost_cents']/100:,.0f}, margin ${mb['margin']:,}, "
                  f"Regal fee ${mb['buyer_fee']:,} & 5% GST "
                  f"⇒ bid ≤ ${max_bid/100:,.0f}.")

    # Profit projection (rough): sale − bid − buyer fee − GST − recon costs.
    bid_dollars = max_bid / 100
    fee = get_buyer_fee(bid_dollars)
    gst = (bid_dollars + fee) * GST_RATE
    projected_net = expected_sale / 100 - bid_dollars - fee - gst - recon["cost_cents"] / 100

    # Sale plan: drivable retail-grade units sell retail; everything else wholesales.
    drivable = "not_drivable" not in (decl.get("remark_signals") or [])
    if mode == "A" and expected_sale / 100 >= LOW_VALUE_THRESHOLD and drivable:
        channel = "Retail (FB/Kijiji)"
    elif mode == "A":
        channel = "Wholesale / quick flip"
    else:
        channel = "Sell repaired retail, or wholesale as-is to a rebuilder"
    list_price = int(expected_sale * 1.05)
    floor_price = int(expected_sale * 0.92)

    return {
        "profile": profile["label"],
        "mode": mode,
        "verdict": verdict,
        "max_bid_cents": max_bid,
        "thesis": thesis,
        "verify_before_bid": verify,
        "recon": recon,
        "history": {"deduction_cents": hist_ded, "reason": hist_reason},
        "sale_plan": {"channel": channel, "list_price_cents": list_price,
                      "floor_price_cents": floor_price,
                      "hold_note": "You prefer fast turns — avoid long-DOM units." if profile["hold_time"] == "low" else ""},
        "projected_net": int(projected_net),
        "expected_sale_cents": expected_sale,
    }


def render(advice: dict) -> str:
    """Format an advise() result as a human-readable, multi-line report."""
    lines = [
        f"VERDICT:   {advice['verdict']}   |   YOUR MAX BID: ${advice['max_bid_cents']/100:,.0f}   "
        f"[{advice['profile']}, Mode {advice['mode']}]",
        f"THESIS:    {advice['thesis']}",
    ]

    history = advice.get("history") or {}
    if history.get("deduction_cents"):
        lines.append(f"HISTORY:   −${history['deduction_cents'] / 100:,.0f} — {history['reason']}")

    if advice["verify_before_bid"]:
        lines.append("\n⚠ VERIFY BEFORE BIDDING")
        for item in advice["verify_before_bid"]:
            lines.append(f"   - {item}")

    lines.append("\n🔧 RECON PLAN")
    for item in advice["recon"]["items"]:
        lines.append(f"   [{item['decision']:8}] ${item['cost']:>6,}  {item['work']} — {item['why']}")

    sale_plan = advice["sale_plan"]
    lines.append("\n💰 SALE PLAN")
    lines.append(f"   channel: {sale_plan['channel']}")
    lines.append(f"   list at ${sale_plan['list_price_cents']/100:,.0f}, "
                 f"floor ${sale_plan['floor_price_cents']/100:,.0f}"
                 + (f"  ({sale_plan['hold_note']})" if sale_plan['hold_note'] else ""))

    lines.append(f"\n📈 PROJECTED NET (rough): ${advice['projected_net']:,}")
    return "\n".join(lines)
