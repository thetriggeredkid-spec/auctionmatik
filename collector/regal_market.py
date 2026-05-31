"""
Regal Auctions Market Report Collector
Paginates the Regal JSON API and stores all sold vehicle records to DB.

Usage:
    python -m collector.regal_market              # full backfill
    python -m collector.regal_market --pages 5    # first 5 pages only (for testing)
    python -m collector.regal_market --recent     # only last 30 days
"""

import re
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from db.connection import get_conn, get_cursor

BASE_URL = "https://regalauctions.com/marketreport/"
VEHICLE_TYPES = ["Car", "Truck", "Sport Utility", "Van"]
PAGE_SIZE = 100
DELAY_SECONDS = 0.5  # be polite — half second between requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://regalauctions.com/marketReport.php",
}


def fetch_page(vehicle_type: str, page: int) -> dict:
    params = {
        "a": "listingdata",
        "listType": "detail",
        "sort": "sold_date-desc",
        "unitsPerPage": PAGE_SIZE,
        "page": page,
        "search[vehicle_type][]": vehicle_type,
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_odometer(raw: str) -> int | None:
    """Extract integer KM from strings like '129,472 KM' or '0 '."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw.split()[0]) if raw.strip() else ""
    return int(digits) if digits else None


def parse_price(raw: str | int) -> int | None:
    """Convert price to CAD cents. Regal returns dollar strings or ints."""
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) * 100 if digits else None


def parse_reserve(raw: str) -> int | None:
    """Convert '$15,000' -> 1500000 cents."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) * 100 if digits else None


def parse_trim_and_body(qamodel: str, model: str) -> tuple[str | None, str | None]:
    """
    qamodel examples:
      '200  4D SEDAN'
      'WRANGLER UNLIMITED 4D UTILITY 4WD'
      'F-150  CREW CAB'
    Strip the model prefix and extract body style keywords.
    """
    if not qamodel:
        return None, None

    text = qamodel.upper().strip()
    # Remove the model name from the front
    if model:
        text = text.replace(model.upper(), "", 1).strip()

    body_keywords = ["4D SEDAN", "2D COUPE", "4D UTILITY", "2D UTILITY",
                     "CREW CAB", "EXTENDED CAB", "REGULAR CAB", "SUPER CAB",
                     "4D VAN", "4D WAGON", "HATCHBACK", "CONVERTIBLE", "PICKUP"]
    body_style = None
    trim = text
    for kw in body_keywords:
        if kw in text:
            body_style = kw
            trim = text.replace(kw, "").strip(" -")
            break

    # Clean up trim — remove drivetrain suffixes that are already in driveline field
    trim = re.sub(r"\b(4WD|AWD|FWD|2WD|4X4|4X2)\b", "", trim).strip(" -")
    return (trim if trim else None), body_style


def record_exists(cursor, regal_id: str) -> bool:
    cursor.execute("SELECT 1 FROM regal_sold WHERE regal_id = %s", (regal_id,))
    return cursor.fetchone() is not None


def insert_record(conn, cursor, record: dict):
    trim, body_style = parse_trim_and_body(
        record.get("qamodel", ""), record.get("model", "")
    )

    cursor.execute("""
        INSERT INTO regal_sold (
            regal_id, contract, year, make, model, trim, body_style,
            vin, color, engine, transmission, driveline, fuel_type,
            vehicle_type, odometer_km, sale_price, reserve_price,
            sold_date, seller_type, declarations, options_text,
            condition_notes, photo_count, carproof_available,
            main_photo_url, raw_json
        ) VALUES (
            %(regal_id)s, %(contract)s, %(year)s, %(make)s, %(model)s,
            %(trim)s, %(body_style)s, %(vin)s, %(color)s, %(engine)s,
            %(transmission)s, %(driveline)s, %(fuel_type)s,
            %(vehicle_type)s, %(odometer_km)s, %(sale_price)s,
            %(reserve_price)s, %(sold_date)s, %(seller_type)s,
            %(declarations)s, %(options_text)s, %(condition_notes)s,
            %(photo_count)s, %(carproof_available)s, %(main_photo_url)s,
            %(raw_json)s
        )
        ON CONFLICT (regal_id) DO NOTHING
    """, {
        "regal_id":          record.get("id"),
        "contract":          record.get("contract"),
        "year":              int(record["year"]) if record.get("year") else None,
        "make":              record.get("adjusted_make") or record.get("make"),
        "model":             record.get("model"),
        "trim":              trim,
        "body_style":        body_style,
        "vin":               record.get("vin") or None,
        "color":             record.get("color") or None,
        "engine":            record.get("engine") or None,
        "transmission":      record.get("transmission") or None,
        "driveline":         record.get("driveline") or None,
        "fuel_type":         record.get("fuel_type") or None,
        "vehicle_type":      record.get("vehicle_type"),
        "odometer_km":       parse_odometer(record.get("odometer", "")),
        "sale_price":        parse_price(record.get("price")),
        "reserve_price":     parse_reserve(record.get("reserve")),
        "sold_date":         record.get("sold_date") or None,
        "seller_type":       record.get("seller_type") or None,
        "declarations":      record.get("declarations") or None,
        "options_text":      record.get("options") or None,
        "condition_notes":   record.get("other") or None,
        "photo_count":       record.get("photos"),
        "carproof_available": bool(record.get("carproof") == "1" or record.get("carproof") == 1),
        "main_photo_url":    record.get("main_photo_url") or None,
        "raw_json":          json.dumps(record),
    })
    conn.commit()


def collect(vehicle_types=None, max_pages=None, recent_days=None):
    vehicle_types = vehicle_types or VEHICLE_TYPES
    conn = get_conn()
    cursor = get_cursor(conn)

    cutoff_date = None
    if recent_days:
        cutoff_date = (datetime.now() - timedelta(days=recent_days)).date()

    total_inserted = 0
    total_skipped = 0

    for vtype in vehicle_types:
        print(f"\n── Collecting: {vtype} ──")
        page = 1

        while True:
            if max_pages and page > max_pages:
                break

            try:
                data = fetch_page(vtype, page)
            except Exception as e:
                print(f"  Page {page} error: {e}")
                break

            records = data.get("list", [])
            total_pages = data.get("totalPages", 1)

            if not records:
                break

            for rec in records:
                # Stop if we've hit records older than cutoff
                if cutoff_date and rec.get("sold_date"):
                    try:
                        rec_date = datetime.strptime(rec["sold_date"], "%Y-%m-%d").date()
                        if rec_date < cutoff_date:
                            print(f"  Reached cutoff date ({cutoff_date}). Stopping.")
                            goto_next_type = True
                            break
                    except ValueError:
                        pass

                regal_id = rec.get("id")
                if not regal_id:
                    continue

                if record_exists(cursor, regal_id):
                    total_skipped += 1
                    continue

                try:
                    insert_record(conn, cursor, rec)
                    total_inserted += 1
                except Exception as e:
                    print(f"  Insert error for {regal_id}: {e}")
                    conn.rollback()
            else:
                goto_next_type = False

            print(f"  Page {page}/{total_pages} — +{total_inserted} inserted, {total_skipped} skipped")

            if goto_next_type or page >= total_pages:
                break

            page += 1
            time.sleep(DELAY_SECONDS)

    cursor.close()
    conn.close()
    print(f"\nDone. Total inserted: {total_inserted}, skipped (already exist): {total_skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect Regal Auctions market report data")
    parser.add_argument("--pages", type=int, help="Max pages per vehicle type (default: all)")
    parser.add_argument("--recent", type=int, metavar="DAYS", help="Only collect last N days")
    parser.add_argument("--type", type=str, help="Single vehicle type (Car, Truck, Sport Utility, Van)")
    args = parser.parse_args()

    vtypes = [args.type] if args.type else None
    collect(vehicle_types=vtypes, max_pages=args.pages, recent_days=args.recent)
