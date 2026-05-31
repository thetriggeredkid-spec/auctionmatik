"""
Comp Pool Builder
Given a vehicle spec dict, queries regal_sold for comparable sold records,
scores them by similarity, applies recency weighting, and returns a structured result.

Usage (standalone test):
    python -m engine.comps --year 2018 --make Toyota --model RAV4 --driveline AWD
"""

import sys
import argparse
import statistics
from datetime import date, timedelta

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from db.connection import get_conn, get_cursor

# Recency weight thresholds
WEIGHT_30D = 3.0
WEIGHT_90D = 1.5
WEIGHT_OLD = 1.0

MIN_COMP_COUNT = 10  # below this, widen search or flag low confidence


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


def _similarity_score(vehicle: dict, comp: dict) -> float:
    """
    Score 0.0–1.0 representing how similar a comp is to the target vehicle.
    Higher = more similar.
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

    # Mileage proximity — closer mileage = slightly higher score
    v_odo = vehicle.get("odometer_km")
    c_odo = comp.get("odometer_km")
    if v_odo and c_odo and v_odo > 0:
        ratio = abs(v_odo - c_odo) / v_odo
        if ratio < 0.1:
            score += 0.1
        elif ratio < 0.25:
            score += 0.05

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
        SELECT id, year, make, model, trim, body_style, driveline,
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
        SELECT id, year, make, model, trim, body_style, driveline,
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


def _score_and_weight(vehicle: dict, raw_comps: list) -> list[dict]:
    """Attach similarity score and recency weight to each comp row."""
    result = []
    for row in raw_comps:
        comp = dict(row)
        comp["_similarity"] = _similarity_score(vehicle, comp)
        comp["_recency_weight"] = _recency_weight(comp.get("sold_date"))
        comp["_combined_weight"] = comp["_similarity"] * comp["_recency_weight"]
        result.append(comp)
    result.sort(key=lambda x: x["_combined_weight"], reverse=True)
    return result


def get_comp_pool(vehicle: dict, conn=None) -> dict:
    """
    Main entry point. Returns:
    {
        base_median:  int (CAD cents),
        comp_count:   int,
        confidence:   'high' | 'medium' | 'low',
        fallback_used: bool,
        comp_list:    [comp dicts with scores, top 50],
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

        scored = _score_and_weight(vehicle, raw)

        if not scored:
            return {
                "base_median": None,
                "comp_count": 0,
                "confidence": "low",
                "fallback_used": fallback_used,
                "comp_list": [],
                "odometer_percentiles": {},
            }

        # Weighted median price
        pw_pairs = [(c["sale_price"], c["_combined_weight"]) for c in scored]
        base_median = _weighted_median(pw_pairs)

        # Confidence tier
        n = len(scored)
        if n >= 20:
            confidence = "high"
        elif n >= 10:
            confidence = "medium"
        else:
            confidence = "low"

        # Odometer percentiles from the comp pool
        odos = sorted([c["odometer_km"] for c in scored if c.get("odometer_km") and c["odometer_km"] > 0])
        percentiles = {}
        if odos:
            def pct(lst, p):
                idx = int(len(lst) * p / 100)
                idx = min(idx, len(lst) - 1)
                return lst[idx]
            percentiles = {
                "p10": pct(odos, 10),
                "p30": pct(odos, 30),
                "p50": pct(odos, 50),
                "p70": pct(odos, 70),
                "p90": pct(odos, 90),
            }

        return {
            "base_median": base_median,
            "comp_count": n,
            "confidence": confidence,
            "fallback_used": fallback_used,
            "comp_list": scored[:50],
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
        "year": args.year,
        "make": args.make,
        "model": args.model,
        "driveline": args.driveline,
        "odometer_km": args.odometer,
    }

    result = get_comp_pool(vehicle)
    print(f"\nComp pool result:")
    print(f"  Base median:    ${result['base_median'] / 100:,.0f}" if result['base_median'] else "  Base median: N/A")
    print(f"  Comp count:     {result['comp_count']}")
    print(f"  Confidence:     {result['confidence']}")
    print(f"  Fallback used:  {result['fallback_used']}")
    print(f"  Odo percentiles: {result['odometer_percentiles']}")
    print(f"\nTop 5 comps:")
    for c in result["comp_list"][:5]:
        print(f"  {c['year']} {c['make']} {c['model']} {c.get('trim','')} | "
              f"{c.get('odometer_km','?')} km | "
              f"${c['sale_price']/100:,.0f} | "
              f"sold {c.get('sold_date','?')} | "
              f"score {c['_combined_weight']:.2f}")
