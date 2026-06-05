"""
Retail Comp Pool Builder
Queries retail_listings (Facebook Marketplace + Kijiji) for comparable active listings.
Returns a retail price anchor — the PRIMARY input to valuation.

Logic mirrors comps.py but operates on retail_listings instead of regal_sold,
and returns asking prices (not sale prices — these are retail listings).
"""

import sys
import psycopg2
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from db.connection import get_conn, get_cursor

_NO_DATA = {
    "retail_median": None,
    "comp_count": 0,
    "confidence": "low",
    "fallback_used": False,
    "comp_list": [],
    "odometer_percentiles": {},
    "has_data": False,
}

MIN_RETAIL_COMP_COUNT = 5  # Below this, fall back to regal_sold wholesale anchor


def _fetch_retail_primary(cursor, vehicle: dict) -> list[dict]:
    """Year ±2, same make, same model, same driveline, active listings."""
    year = vehicle.get("year")
    make = (vehicle.get("make") or "").upper()
    model = (vehicle.get("model") or "").upper()
    driveline = (vehicle.get("driveline") or "").upper()

    cursor.execute("""
        SELECT id, external_id, source, year, make, model, trim,
               driveline, odometer_km, asking_price, location_city,
               location_province, seller_type, listing_url, posted_at,
               is_sold, collected_at
        FROM retail_listings
        WHERE year BETWEEN %s AND %s
          AND UPPER(COALESCE(make, ''))  = %s
          AND UPPER(COALESCE(model, '')) = %s
          AND UPPER(COALESCE(driveline, '')) = %s
          AND asking_price > 0
          AND is_sold = FALSE
        ORDER BY collected_at DESC
        LIMIT 200
    """, (year - 2, year + 2, make, model, driveline))
    return cursor.fetchall() or []


def _fetch_retail_model_only(cursor, vehicle: dict) -> list[dict]:
    """Fallback: year ±3, same make + model, any driveline."""
    year = vehicle.get("year")
    make = (vehicle.get("make") or "").upper()
    model = (vehicle.get("model") or "").upper()

    cursor.execute("""
        SELECT id, external_id, source, year, make, model, trim,
               driveline, odometer_km, asking_price, location_city,
               location_province, seller_type, listing_url, posted_at,
               is_sold, collected_at
        FROM retail_listings
        WHERE year BETWEEN %s AND %s
          AND UPPER(COALESCE(make, ''))  = %s
          AND UPPER(COALESCE(model, '')) = %s
          AND asking_price > 0
          AND is_sold = FALSE
        ORDER BY collected_at DESC
        LIMIT 200
    """, (year - 3, year + 3, make, model))
    return cursor.fetchall() or []


def _similarity_score(vehicle: dict, comp: dict) -> float:
    """Score 0.0–1.0 similarity between vehicle spec and retail comp."""
    score = 0.5

    v_trim = (vehicle.get("trim") or "").upper().strip()
    c_trim = (comp.get("trim") or "").upper().strip()
    if v_trim and c_trim and v_trim == c_trim:
        score += 0.3
    elif v_trim and c_trim and (v_trim in c_trim or c_trim in v_trim):
        score += 0.1

    v_year = vehicle.get("year")
    c_year = comp.get("year")
    if v_year and c_year:
        diff = abs(int(v_year) - int(c_year))
        if diff == 0:
            score += 0.15
        elif diff == 1:
            score += 0.05

    v_odo = vehicle.get("odometer_km")
    c_odo = comp.get("odometer_km")
    if v_odo and c_odo and v_odo > 0:
        ratio = abs(v_odo - c_odo) / v_odo
        if ratio < 0.1:
            score += 0.1
        elif ratio < 0.25:
            score += 0.05

    # Private seller = more comparable to what we'll list at
    if comp.get("seller_type") == "private":
        score += 0.05

    return min(score, 1.0)


def _median(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) // 2


def get_retail_comp_pool(vehicle: dict, conn=None) -> dict:
    """
    Main entry point.
    Returns:
    {
        retail_median:   int (CAD cents) — the asking-price median from active retail listings
        comp_count:      int
        confidence:      'high' | 'medium' | 'low'
        fallback_used:   bool
        comp_list:       [comp dicts with _similarity score, top 50]
        odometer_percentiles: {p10, p30, p50, p70, p90}
        has_data:        bool — False if no retail listings found at all
    }
    """
    close_conn = conn is None
    if conn is None:
        conn = get_conn()
    cursor = get_cursor(conn)

    try:
        try:
            raw = _fetch_retail_primary(cursor, vehicle)
        except psycopg2.errors.UndefinedTable:
            # retail_listings table not yet created — fall back to wholesale comps
            conn.rollback()
            return dict(_NO_DATA)

        fallback_used = False

        if len(raw) < MIN_RETAIL_COMP_COUNT:
            raw_fb = _fetch_retail_model_only(cursor, vehicle)
            if len(raw_fb) >= len(raw):
                raw = raw_fb
                fallback_used = True

        if not raw:
            return {
                "retail_median": None,
                "comp_count": 0,
                "confidence": "low",
                "fallback_used": fallback_used,
                "comp_list": [],
                "odometer_percentiles": {},
                "has_data": False,
            }

        # Score and sort
        scored = []
        for row in raw:
            comp = dict(row)
            comp["_similarity"] = _similarity_score(vehicle, comp)
            scored.append(comp)
        scored.sort(key=lambda x: x["_similarity"], reverse=True)

        # Simple median of asking prices (no recency weighting — these are live)
        prices = [c["asking_price"] for c in scored if c.get("asking_price") and c["asking_price"] > 0]
        retail_median = _median(prices) if prices else None

        n = len(scored)
        if n >= 20:
            confidence = "high"
        elif n >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        odos = sorted([c["odometer_km"] for c in scored if c.get("odometer_km") and c["odometer_km"] > 0])
        percentiles = {}
        if odos:
            def pct(lst, p):
                idx = min(int(len(lst) * p / 100), len(lst) - 1)
                return lst[idx]
            percentiles = {
                "p10": pct(odos, 10), "p30": pct(odos, 30),
                "p50": pct(odos, 50), "p70": pct(odos, 70),
                "p90": pct(odos, 90),
            }

        return {
            "retail_median": retail_median,
            "comp_count": n,
            "confidence": confidence,
            "fallback_used": fallback_used,
            "comp_list": scored[:50],
            "odometer_percentiles": percentiles,
            "has_data": True,
        }

    finally:
        cursor.close()
        if close_conn:
            conn.close()
