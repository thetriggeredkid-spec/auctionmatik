"""
Regal Auctions Active Listings Collector
Paginates the Regal inventory API and upserts current listings to regal_listings table.
Run on a schedule to keep listings fresh.

Usage:
    python -m collector.regal_listings                   # all vehicle types
    python -m collector.regal_listings --type Car        # single type
    python -m collector.regal_listings --pages 3         # test run
"""

import re
import sys
import json
import time
import argparse
import requests
from datetime import datetime

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from db.connection import get_conn, get_cursor

BASE_URL = "https://regalauctions.com/inventory/"
VEHICLE_TYPES = ["Car", "Truck", "Sport Utility", "Van"]
PAGE_SIZE = 100
DELAY_SECONDS = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://regalauctions.com/inventory.php",
}


def fetch_page(vehicle_type: str, page: int) -> dict:
    params = {
        "a": "listingdata",
        "listType": "detail",
        "sort": "lot-asc",
        "unitsPerPage": PAGE_SIZE,
        "page": page,
        "search[vehicle_type][]": vehicle_type,
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_odometer(raw: str) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw.split()[0]) if raw.strip() else ""
    return int(digits) if digits else None


def parse_price(raw) -> int | None:
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) * 100 if digits else None


def parse_reserve(raw: str) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) * 100 if digits else None


def parse_trim_and_body(qamodel: str, model: str) -> tuple[str | None, str | None]:
    if not qamodel:
        return None, None
    text = qamodel.upper().strip()
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
    trim = re.sub(r"\b(4WD|AWD|FWD|2WD|4X4|4X2)\b", "", trim).strip(" -")
    return (trim if trim else None), body_style


def upsert_record(conn, cursor, record: dict):
    trim, body_style = parse_trim_and_body(
        record.get("qamodel", ""), record.get("model", "")
    )

    # Try to extract auction date from record fields
    auction_date = record.get("auction_date") or record.get("sale_date") or None
    if auction_date == "":
        auction_date = None

    cursor.execute("""
        INSERT INTO regal_listings (
            regal_id, contract, year, make, model, trim, body_style,
            vin, color, engine, transmission, driveline, fuel_type,
            vehicle_type, odometer_km, reserve_price, seller_type,
            declarations, options_text, condition_notes, photo_count,
            carproof_available, main_photo_url, auction_date, status,
            raw_json, last_updated_at
        ) VALUES (
            %(regal_id)s, %(contract)s, %(year)s, %(make)s, %(model)s,
            %(trim)s, %(body_style)s, %(vin)s, %(color)s, %(engine)s,
            %(transmission)s, %(driveline)s, %(fuel_type)s,
            %(vehicle_type)s, %(odometer_km)s, %(reserve_price)s,
            %(seller_type)s, %(declarations)s, %(options_text)s,
            %(condition_notes)s, %(photo_count)s, %(carproof_available)s,
            %(main_photo_url)s, %(auction_date)s, %(status)s,
            %(raw_json)s, NOW()
        )
        ON CONFLICT (regal_id) DO UPDATE SET
            contract         = EXCLUDED.contract,
            year             = EXCLUDED.year,
            make             = EXCLUDED.make,
            model            = EXCLUDED.model,
            trim             = EXCLUDED.trim,
            body_style       = EXCLUDED.body_style,
            vin              = EXCLUDED.vin,
            color            = EXCLUDED.color,
            engine           = EXCLUDED.engine,
            transmission     = EXCLUDED.transmission,
            driveline        = EXCLUDED.driveline,
            fuel_type        = EXCLUDED.fuel_type,
            vehicle_type     = EXCLUDED.vehicle_type,
            odometer_km      = EXCLUDED.odometer_km,
            reserve_price    = EXCLUDED.reserve_price,
            seller_type      = EXCLUDED.seller_type,
            declarations     = EXCLUDED.declarations,
            options_text     = EXCLUDED.options_text,
            condition_notes  = EXCLUDED.condition_notes,
            photo_count      = EXCLUDED.photo_count,
            carproof_available = EXCLUDED.carproof_available,
            main_photo_url   = EXCLUDED.main_photo_url,
            auction_date     = EXCLUDED.auction_date,
            status           = EXCLUDED.status,
            raw_json         = EXCLUDED.raw_json,
            last_updated_at  = NOW()
    """, {
        "regal_id":           record.get("id"),
        "contract":           record.get("contract"),
        "year":               int(record["year"]) if record.get("year") else None,
        "make":               record.get("adjusted_make") or record.get("make"),
        "model":              record.get("model"),
        "trim":               trim,
        "body_style":         body_style,
        "vin":                record.get("vin") or None,
        "color":              record.get("color") or None,
        "engine":             record.get("engine") or None,
        "transmission":       record.get("transmission") or None,
        "driveline":          record.get("driveline") or None,
        "fuel_type":          record.get("fuel_type") or None,
        "vehicle_type":       record.get("vehicle_type"),
        "odometer_km":        parse_odometer(record.get("odometer", "")),
        "reserve_price":      parse_reserve(record.get("reserve")),
        "seller_type":        record.get("seller_type") or None,
        "declarations":       record.get("declarations") or None,
        "options_text":       record.get("options") or None,
        "condition_notes":    record.get("other") or None,
        "photo_count":        record.get("photos"),
        "carproof_available": bool(record.get("carproof") in ("1", 1)),
        "main_photo_url":     record.get("main_photo_url") or None,
        "auction_date":       auction_date,
        "status":             "ACTIVE",
        "raw_json":           json.dumps(record),
    })
    conn.commit()


def collect(vehicle_types=None, max_pages=None):
    vehicle_types = vehicle_types or VEHICLE_TYPES
    conn = get_conn()
    cursor = get_cursor(conn)

    total_upserted = 0

    for vtype in vehicle_types:
        print(f"\n── Collecting listings: {vtype} ──")
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
                regal_id = rec.get("id")
                if not regal_id:
                    continue
                try:
                    upsert_record(conn, cursor, rec)
                    total_upserted += 1
                except Exception as e:
                    print(f"  Upsert error for {regal_id}: {e}")
                    conn.rollback()

            print(f"  Page {page}/{total_pages} — {total_upserted} upserted total")

            if page >= total_pages:
                break

            page += 1
            time.sleep(DELAY_SECONDS)

    cursor.close()
    conn.close()
    print(f"\nDone. Total upserted: {total_upserted}")


def fetch_by_contract(contract: str) -> dict | None:
    """Fetch a single active listing by contract number directly from the API."""
    for vtype in VEHICLE_TYPES:
        page = 1
        while True:
            try:
                data = fetch_page(vtype, page)
            except Exception:
                break
            records = data.get("list", [])
            total_pages = data.get("totalPages", 1)
            for rec in records:
                if str(rec.get("contract")) == str(contract):
                    return rec
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.3)
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect Regal Auctions active listings")
    parser.add_argument("--pages", type=int, help="Max pages per vehicle type (default: all)")
    parser.add_argument("--type", type=str, help="Single vehicle type (Car, Truck, Sport Utility, Van)")
    args = parser.parse_args()

    vtypes = [args.type] if args.type else None
    collect(vehicle_types=vtypes, max_pages=args.pages)
