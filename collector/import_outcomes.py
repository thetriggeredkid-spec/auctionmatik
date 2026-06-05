"""
Outcome importer — turn realized Regal auction results into calibration data.

For historical sold vehicles (regal_sold), run the deterministic engine on each
(EXCLUDING the car from its own comp pool) and record the engine's call alongside
the actual hammer price in listing_feedback. The dashboard's Calibration view then
shows the engine's **max-bid vs the price it actually took** — by make and price
band — which is the bias signal for tuning the methodology.

Auto-imported rows are tagged "[auto]" in notes and leave corrected_value NULL, so
they populate the max-bid track without polluting the human retail-correction track.

Usage:
    python3 -m collector.import_outcomes --limit 100
    python3 -m collector.import_outcomes --limit 200 --make FORD --min-comps 5
    python3 -m collector.import_outcomes --limit 50 --dry-run
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.connection import get_conn, get_cursor
from engine import settings as settings_mod
from engine.valuator import valuate
from engine.advisor import advise
from engine.declarations import analyze_declarations

AUTO_TAG = "[auto] engine call vs realized auction price"


def _vehicle_from_sold(rec: dict) -> dict:
    """Map a regal_sold row to the vehicle spec the engine consumes."""
    return {
        "year": rec.get("year"), "make": rec.get("make"), "model": rec.get("model"),
        "trim": rec.get("trim"), "driveline": rec.get("driveline"),
        "vehicle_type": rec.get("vehicle_type"), "fuel_type": rec.get("fuel_type"),
        "odometer_km": rec.get("odometer_km"), "engine": rec.get("engine"),
        "transmission": rec.get("transmission"), "color": rec.get("color"),
        "seller_type": rec.get("seller_type"), "declarations": rec.get("declarations"),
        "condition_notes": rec.get("condition_notes"), "vin": rec.get("vin"),
        "contract": rec.get("contract"),
        # neutral condition defaults (we have no inspection for a historical sale)
        "exterior_grade": 3, "interior_grade": 3, "mechanical_grade": 3,
        "damage_items": [], "options_present": [], "accident_type": "none",
        "accident_claim_amount": 0, "rebuilt_title": False,
        "service_records": "unknown", "odometer_integrity": "clean",
    }


def _engine_call(conn, rec: dict) -> dict | None:
    """Run the deterministic engine on a sold record (self-excluded). Returns
    {verdict, value_cents, max_bid_cents, comp_count} or None if unpriceable."""
    vehicle = _vehicle_from_sold(rec)
    valuation = valuate(vehicle, conn=conn, exclude_ids={rec.get("id")})
    if "error" in valuation:
        return None
    anchor = valuation.get("base_median") or valuation.get("retail_mid")
    if not anchor:
        return None
    decl = analyze_declarations(vehicle.get("declarations") or "",
                               vehicle.get("condition_notes") or "")
    ch = advise(vehicle, anchor_cents=anchor, clean_value_cents=anchor, decl=decl,
                vision={}, carfax=None, profile_key="charles")
    return {
        "verdict": ch["verdict"],
        "value_cents": ch.get("expected_sale_cents", anchor),
        "max_bid_cents": ch["max_bid_cents"],
        "comp_count": valuation.get("comp_count", 0),
    }


def _feedback_params(rec: dict, call: dict) -> tuple:
    """Build the SQL params for the listing_feedback upsert (cents in DB)."""
    return (
        str(rec.get("contract")), rec.get("year"), rec.get("make"), rec.get("model"),
        _norm_verdict(call["verdict"]), call["value_cents"], call["max_bid_cents"],
        rec.get("sale_price"),  # actual_sale_price (already CAD cents in regal_sold)
        AUTO_TAG,
    )


def _norm_verdict(s: str) -> str:
    s = (s or "").upper()
    if "FIX" in s:
        return "BID_TO_FIX"
    if s.startswith("BID"):
        return "BID"
    return "PASS"


def _bid_err_pct(max_bid_cents: int, actual_cents: int) -> float | None:
    if not actual_cents:
        return None
    return round((max_bid_cents - actual_cents) / actual_cents * 100, 1)


def import_outcomes(limit=100, make=None, min_comps=3, dry_run=False) -> dict:
    conn = get_conn()
    settings_mod.apply_from_db(conn)
    cur = get_cursor(conn)
    where = "sale_price > 0 AND make IS NOT NULL AND year IS NOT NULL"
    params = []
    if make:
        where += " AND UPPER(make) = %s"
        params.append(make.upper())
    cur.execute(f"SELECT * FROM regal_sold WHERE {where} ORDER BY sold_date DESC LIMIT %s",
                (*params, limit))
    records = [dict(r) for r in cur.fetchall()]
    cur.close()

    imported = skipped = 0
    errs = []
    for rec in records:
        try:
            call = _engine_call(conn, rec)
        except Exception as e:  # noqa: BLE001
            print(f"  #{rec.get('contract')} error: {e}")
            call = None
        if not call or call["comp_count"] < min_comps:
            skipped += 1
            continue
        be = _bid_err_pct(call["max_bid_cents"], rec.get("sale_price"))
        if be is not None:
            errs.append(be)
        if not dry_run:
            wcur = get_cursor(conn)
            wcur.execute("""
                INSERT INTO listing_feedback (contract, year, make, model, engine_verdict,
                    engine_value, engine_max_bid, actual_sale_price, notes, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                ON CONFLICT (contract) DO UPDATE SET
                    engine_verdict=EXCLUDED.engine_verdict, engine_value=EXCLUDED.engine_value,
                    engine_max_bid=EXCLUDED.engine_max_bid, actual_sale_price=EXCLUDED.actual_sale_price,
                    notes=EXCLUDED.notes, updated_at=NOW()
                WHERE listing_feedback.notes LIKE '[auto]%%'
            """, _feedback_params(rec, call))
            conn.commit()
            wcur.close()
        imported += 1

    mae = round(sum(abs(e) for e in errs) / len(errs), 1) if errs else None
    bias = round(sum(errs) / len(errs), 1) if errs else None
    print(f"\n{'DRY RUN — ' if dry_run else ''}imported {imported}, skipped {skipped} "
          f"(thin comps / unpriceable) of {len(records)} sold records")
    if mae is not None:
        print(f"max-bid vs actual auction price — MAE {mae}% · bias {bias}% "
              f"(negative = engine bids below the realized price, expected from margin)")
    conn.close()
    return {"imported": imported, "skipped": skipped, "mae": mae, "bias": bias}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Import realized auction outcomes into calibration")
    ap.add_argument("--limit", type=int, default=100, help="Max sold records (most recent)")
    ap.add_argument("--make", default=None, help="Restrict to one make (e.g. FORD)")
    ap.add_argument("--min-comps", type=int, default=3, help="Skip records with fewer comps")
    ap.add_argument("--dry-run", action="store_true", help="Compute + summarize; don't write")
    a = ap.parse_args()
    import_outcomes(limit=a.limit, make=a.make, min_comps=a.min_comps, dry_run=a.dry_run)
