"""
Comp Pool Builder (Wholesale — Regal Sold Data)
Given a vehicle spec dict, queries regal_sold for comparable sold records,
scores them by similarity AND condition quality, applies recency weighting,
and returns a structured result with tiered medians.

KEY DESIGN: Comps are tiered by condition signal:
  'clean'     — no major damage declarations, no severe condition notes
  'distressed'— damage declarations, known mechanical issues (NOT finance repo)
  'unknown'   — insufficient data to classify

The PRIMARY price anchor is the CLEAN-tier weighted median.
The distressed median is shown separately as a floor reference.
This prevents damage-sale comps from dragging down the base price for
a clean vehicle, and prevents inflated comps from being used when
evaluating a distressed vehicle.

Usage (standalone test):
    python -m engine.comps --year 2018 --make Toyota --model RAV4 --driveline AWD
"""

import sys
import re
import argparse
from datetime import date

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from db.connection import get_conn, get_cursor
from engine.factors.model_year import get_cross_gen_comp_penalty

# Recency weight thresholds
WEIGHT_30D = 3.0
WEIGHT_90D = 1.5
WEIGHT_OLD = 1.0

MIN_COMP_COUNT = 10  # below this, widen search or flag low confidence

# ── Declarations that signal distressed sale ──────────────────────────────────
# These mean the comp sold at a price driven by urgency/damage, not fair market.
DISTRESSED_DECLARATIONS = {
    # NOTE: Finance Repo (FR) is intentionally NOT here — at Regal it's a same-day/quick
    # release that sells at market, not a duress price. Treating FR comps as distressed
    # would wrongly segment valid market sales out of the clean anchor. (Charles.)
    "CH1000",   # Collision Damage $1,000–$2,500
    "CH2500",   # Collision Damage $2,500–$5,000
    "CH5000",   # Collision Damage $5,000+
    "MP",       # Mechanical Problem
    "OOPSK",    # Missing keys / no keys
    "FLOOD",    # Flood damage
}

# Keywords in condition_notes that signal distressed condition
DISTRESSED_NOTE_PATTERNS = [
    r"\bframe\b.*\bdamage\b",
    r"\bframe\b.*\bbent\b",
    r"\bflood\b",
    r"\bsalvage\b",
    r"\bfire\b.*\bdamage\b",
    r"\bengine\b.*\bknock\b",
    r"\bengine\b.*\bseized\b",
    r"\btransmission\b.*\bfail\b",
    r"\bnot\s+drivable\b",
    r"\bdoes\s+not\s+start\b",
    r"\bno\s+start\b",
    r"\bmajor\b.*\bdamage\b",
    r"\bseverely?\b.*\bdamage\b",
    r"\brollover\b",
    r"\bwrite.?off\b",
]


def _days_ago(sold_date) -> int:
    """Return how many days ago the sold_date was."""
    if sold_date is None:
        return 9999
    if isinstance(sold_date, str):
        from datetime import datetime
        sold_date = datetime.strptime(sold_date, "%Y-%m-%d").date()
    return (date.today() - sold_date).days


def _recency_weight(sold_date) -> float:
    days = _days_ago(sold_date)
    if days <= 30:
        return WEIGHT_30D
    if days <= 90:
        return WEIGHT_90D
    return WEIGHT_OLD


def _comp_tier(comp: dict) -> str:
    """
    Classify a comp as 'clean', 'distressed', or 'unknown'.

    clean      → no distress signals; price reflects fair-market conditions
    distressed → sold under duress (declared damage, mechanical failure; NOT finance repo)
    unknown    → no condition data available to classify
    """
    declarations = (comp.get("declarations") or "").upper()
    notes = (comp.get("condition_notes") or "").lower()
    seller_type = (comp.get("seller_type") or "").upper()

    # Check declarations for distress signals
    decl_parts = {d.strip() for d in re.split(r"[,;\s]+", declarations) if d.strip()}
    if decl_parts & DISTRESSED_DECLARATIONS:
        return "distressed"

    # Check condition notes for severe language
    for pattern in DISTRESSED_NOTE_PATTERNS:
        if re.search(pattern, notes):
            return "distressed"

    # Dealer selling through auction = retail failure exit (below market)
    # but NOT distressed — just a motivated seller, price still reflects market floor
    # We flag it but don't demote to distressed

    # If we have condition data and it's clean
    if notes and len(notes) > 20:
        return "clean"

    # No condition data — can't classify
    if not declarations and not notes:
        return "unknown"

    return "clean"


def _norm_cab(*texts) -> str | None:
    """Canonical truck cab from any trim/style/body text: 'crew' | 'ext' | 'reg'."""
    t = " ".join(str(x or "") for x in texts).upper()
    if any(k in t for k in ("SUPERCREW", "CREW CAB", "CREWCAB", "CREWMAX", "CREW")):
        return "crew"
    if any(k in t for k in ("SUPERCAB", "SUPER CAB", "QUAD", "DOUBLE CAB", "KING CAB",
                            "ACCESS CAB", "EXTENDED", "EXT CAB")):
        return "ext"
    if any(k in t for k in ("REGULAR CAB", "REG CAB", "SINGLE CAB", "STANDARD CAB", "STD CAB")):
        return "reg"
    return None


def _similarity_score(vehicle: dict, comp: dict) -> float:
    """
    Score 0.0–1.0 representing how similar a comp is to the target vehicle.
    Higher = more similar.

    Factors:
    - Trim match (most impactful — trim drives spec and buyer pool)
    - Exact year match vs. adjacent years
    - Mileage proximity
    - Driveline match (already filtered in SQL, but secondary score if fallback used)
    - Generation match (if model_year_intel available — handled in caller)
    """
    score = 0.5  # base

    # Trim match
    v_trim = (vehicle.get("trim") or "").upper().strip()
    c_trim = (comp.get("trim") or "").upper().strip()
    if v_trim and c_trim and v_trim == c_trim:
        score += 0.3
    elif v_trim and c_trim and (v_trim in c_trim or c_trim in v_trim):
        score += 0.1

    # Exact year match vs. year range
    v_year = vehicle.get("year")
    c_year = comp.get("year")
    if v_year and c_year:
        diff = abs(int(v_year) - int(c_year))
        if diff == 0:
            score += 0.15
        elif diff == 1:
            score += 0.05
        # diff >= 2: no bonus (already within ±2 filter)

    # Truck cab configuration — a primary value driver. A crew cab is a different
    # vehicle from a regular cab; reward a match, penalize a mismatch.
    v_cab = vehicle.get("cab") or _norm_cab(vehicle.get("trim"), vehicle.get("style"))
    c_cab = _norm_cab(comp.get("trim"), comp.get("body_style"))
    if v_cab and c_cab:
        v_cab_n = _norm_cab(v_cab) or v_cab
        score += 0.2 if v_cab_n == c_cab else -0.25

    # Mileage proximity — closer mileage = slightly higher score
    v_odo = vehicle.get("odometer_km")
    c_odo = comp.get("odometer_km")
    if v_odo and c_odo and v_odo > 0:
        ratio = abs(v_odo - c_odo) / v_odo
        if ratio < 0.1:
            score += 0.1
        elif ratio < 0.25:
            score += 0.05

    # Generation penalty — cross-gen comps are less representative
    # e.g. a 2018 RAV4 comp is a poor reference for a 2019 RAV4 (different gen)
    v_year = vehicle.get("year")
    c_year = comp.get("year")
    make = vehicle.get("make", "")
    model = vehicle.get("model", "")
    if v_year and c_year and make and model:
        gen_penalty = get_cross_gen_comp_penalty(make, model, int(v_year), int(c_year))
        score = max(0.0, score - gen_penalty * 0.5)  # scale: full gen gap = -0.5 on score

    return min(score, 1.0)


def _weighted_median(prices_and_weights: list[tuple[int, float]]) -> int:
    """Compute a weighted median from (price, weight) pairs."""
    if not prices_and_weights:
        return 0
    sorted_pw = sorted(prices_and_weights, key=lambda x: x[0])
    total_weight = sum(w for _, w in sorted_pw)
    cumulative = 0.0
    for price, weight in sorted_pw:
        cumulative += weight
        if cumulative >= total_weight / 2:
            return price
    return sorted_pw[-1][0]


def _fetch_comps_primary(cursor, vehicle: dict) -> list[dict]:
    """Year ±2, same make, same model, same driveline."""
    year = vehicle.get("year")
    make = vehicle.get("make", "").upper()
    model = vehicle.get("model", "").upper()
    driveline = vehicle.get("driveline", "").upper()

    cursor.execute("""
        SELECT id, regal_id, contract, year, make, model, trim, body_style, driveline,
               odometer_km, sale_price, sold_date, seller_type, declarations,
               condition_notes, options_text, vin, color, engine, transmission
        FROM regal_sold
        WHERE year BETWEEN %s AND %s
          AND UPPER(make)  = %s
          AND UPPER(model) = %s
          AND UPPER(COALESCE(driveline, '')) = %s
          AND sale_price > 0
        ORDER BY sold_date DESC
        LIMIT 200
    """, (year - 2, year + 2, make, model, driveline))
    return cursor.fetchall() or []


def _fetch_comps_model_only(cursor, vehicle: dict) -> list[dict]:
    """Fallback: year ±3, same make + model, any driveline."""
    year = vehicle.get("year")
    make = vehicle.get("make", "").upper()
    model = vehicle.get("model", "").upper()

    cursor.execute("""
        SELECT id, regal_id, contract, year, make, model, trim, body_style, driveline,
               odometer_km, sale_price, sold_date, seller_type, declarations,
               condition_notes, options_text, vin, color, engine, transmission
        FROM regal_sold
        WHERE year BETWEEN %s AND %s
          AND UPPER(make)  = %s
          AND UPPER(model) = %s
          AND sale_price > 0
        ORDER BY sold_date DESC
        LIMIT 200
    """, (year - 3, year + 3, make, model))
    return cursor.fetchall() or []


def _score_and_tier(vehicle: dict, raw_comps: list) -> list[dict]:
    """Attach similarity score, recency weight, combined weight, and condition tier."""
    result = []
    for row in raw_comps:
        comp = dict(row)
        comp["_similarity"] = _similarity_score(vehicle, comp)
        comp["_recency_weight"] = _recency_weight(comp.get("sold_date"))
        comp["_combined_weight"] = comp["_similarity"] * comp["_recency_weight"]
        comp["_tier"] = _comp_tier(comp)
        result.append(comp)
    result.sort(key=lambda x: x["_combined_weight"], reverse=True)
    return result


def _tier_stats(scored: list[dict]) -> dict:
    """Compute count and price stats per tier."""
    tiers = {"clean": [], "distressed": [], "unknown": []}
    for c in scored:
        tiers[c["_tier"]].append(c["sale_price"])

    def stats(prices):
        if not prices:
            return {"count": 0, "median": None, "low": None, "high": None}
        s = sorted(prices)
        n = len(s)
        med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2
        return {"count": n, "median": med, "low": s[0], "high": s[-1]}

    return {tier: stats(prices) for tier, prices in tiers.items()}


def get_comp_pool(vehicle: dict, conn=None) -> dict:
    """
    Main entry point. Returns:
    {
        base_median:         int (CAD cents) — weighted median of CLEAN comps (primary anchor)
        base_median_all:     int — weighted median of ALL comps (for reference)
        comp_count:          int — total comps found
        clean_count:         int — comps classified as clean condition
        distressed_count:    int — comps classified as distressed
        tier_stats:          dict — {clean, distressed, unknown} with count/median/low/high
        confidence:          'high' | 'medium' | 'low'
        fallback_used:       bool
        comp_list:           [comp dicts with scores and tier, top 50]
        odometer_percentiles: {p10, p30, p50, p70, p90}
    }
    """
    close_conn = conn is None
    if conn is None:
        conn = get_conn()
    cursor = get_cursor(conn)

    try:
        raw = _fetch_comps_primary(cursor, vehicle)
        fallback_used = False

        if len(raw) < MIN_COMP_COUNT:
            raw_fb = _fetch_comps_model_only(cursor, vehicle)
            if len(raw_fb) >= len(raw):
                raw = raw_fb
                fallback_used = True

        scored = _score_and_tier(vehicle, raw)

        if not scored:
            return {
                "base_median": None,
                "base_median_all": None,
                "comp_count": 0,
                "clean_count": 0,
                "distressed_count": 0,
                "tier_stats": {},
                "confidence": "low",
                "fallback_used": fallback_used,
                "comp_list": [],
                "odometer_percentiles": {},
            }

        # Tier stats
        stats = _tier_stats(scored)

        # PRIMARY: weighted median of clean comps only
        # If too few clean comps, fall back to all (with a confidence penalty)
        clean_comps = [c for c in scored if c["_tier"] == "clean"]
        if len(clean_comps) >= 3:
            pw_clean = [(c["sale_price"], c["_combined_weight"]) for c in clean_comps]
            base_median = _weighted_median(pw_clean)
            anchor_note = f"clean comps ({len(clean_comps)} of {len(scored)})"
        elif scored:
            # Not enough clean comps — use all, but note this in reasoning
            pw_all = [(c["sale_price"], c["_combined_weight"]) for c in scored]
            base_median = _weighted_median(pw_all)
            anchor_note = f"all comps — insufficient clean tier ({len(clean_comps)} clean of {len(scored)} total)"
        else:
            base_median = None
            anchor_note = "no comps"

        # ALL-comps median (for reference / floor comparison)
        pw_all = [(c["sale_price"], c["_combined_weight"]) for c in scored]
        base_median_all = _weighted_median(pw_all)

        # Confidence tier (based on clean comp count)
        effective_n = len(clean_comps) if len(clean_comps) >= 3 else len(scored)
        if effective_n >= 20:
            confidence = "high"
        elif effective_n >= 10:
            confidence = "medium"
        else:
            confidence = "low"

        # Odometer percentiles from the full comp pool
        odos = sorted([c["odometer_km"] for c in scored if c.get("odometer_km") and c["odometer_km"] > 0])
        percentiles = {}
        if odos:
            def pct(lst, p):
                idx = int(len(lst) * p / 100)
                idx = min(idx, len(lst) - 1)
                return lst[idx]
            percentiles = {
                "p10": pct(odos, 10), "p30": pct(odos, 30),
                "p50": pct(odos, 50), "p70": pct(odos, 70),
                "p90": pct(odos, 90),
            }

        return {
            "base_median":      base_median,
            "base_median_all":  base_median_all,
            "anchor_note":      anchor_note,
            "comp_count":       len(scored),
            "clean_count":      len(clean_comps),
            "distressed_count": len([c for c in scored if c["_tier"] == "distressed"]),
            "unknown_count":    len([c for c in scored if c["_tier"] == "unknown"]),
            "tier_stats":       stats,
            "confidence":       confidence,
            "fallback_used":    fallback_used,
            "comp_list":        scored[:50],
            "odometer_percentiles": percentiles,
        }

    finally:
        cursor.close()
        if close_conn:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--make", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--driveline", default="")
    parser.add_argument("--odometer", type=int, default=None)
    args = parser.parse_args()

    vehicle = {
        "year": args.year, "make": args.make,
        "model": args.model, "driveline": args.driveline,
        "odometer_km": args.odometer,
    }

    result = get_comp_pool(vehicle)
    print(f"\nComp pool: {result['anchor_note']}")
    print(f"  Clean median:  ${result['base_median'] / 100:,.0f}" if result['base_median'] else "  Clean median: N/A")
    print(f"  All median:    ${result['base_median_all'] / 100:,.0f}" if result['base_median_all'] else "  All median: N/A")
    print(f"  Total comps:   {result['comp_count']}  (clean={result['clean_count']}, distressed={result['distressed_count']}, unknown={result['unknown_count']})")
    print(f"  Confidence:    {result['confidence']}")
    print(f"  Fallback used: {result['fallback_used']}")

    ts = result.get("tier_stats", {})
    for tier in ("clean", "distressed", "unknown"):
        s = ts.get(tier, {})
        if s.get("count"):
            lo = f"${s['low']/100:,.0f}" if s['low'] else "?"
            hi = f"${s['high']/100:,.0f}" if s['high'] else "?"
            med = f"${s['median']/100:,.0f}" if s['median'] else "?"
            print(f"  [{tier:12s}] n={s['count']:3d}  range={lo}–{hi}  median={med}")

    print(f"\nTop 5 comps:")
    for c in result["comp_list"][:5]:
        decl = c.get('declarations') or '-'
        print(f"  [{c['_tier']:12s}] {c['year']} {c['make']} {c['model']} {c.get('trim',''):15s} "
              f"{c.get('odometer_km','?'):>7} km  ${c['sale_price']/100:>8,.0f}  "
              f"sold {c.get('sold_date','?')}  decl={decl}  score={c['_combined_weight']:.2f}")
