"""
Retail Comps Collector — Apify Integration
Pulls active vehicle listings from Facebook Marketplace and Kijiji via Apify actors,
parses them into a normalized schema, and upserts into the retail_listings table.

Actors used:
  Facebook Marketplace: apify/facebook-marketplace-scraper  ($2.60/1000 listings)
  Kijiji:               calm_builder/kijiji-scraper         ($0.50/1000 listings)

Usage:
    python3 -m collector.retail_comps --source facebook --location edmonton --query "toyota rav4"
    python3 -m collector.retail_comps --source kijiji --url "https://www.kijiji.ca/b-cars-trucks/edmonton/toyota-rav4/k0c174l1700203"
    python3 -m collector.retail_comps --source all --location edmonton --query "jeep wrangler"

Setup:
    Set APIFY_TOKEN in your .env file (get from https://console.apify.com/account/integrations)
"""

import os
import re
import sys
import time
import argparse
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
from db.connection import get_conn, get_cursor

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_BASE = "https://api.apify.com/v2"

# Actor IDs
FB_ACTOR_ID = "apify~facebook-marketplace-scraper"
KIJIJI_ACTOR_ID = "calm_builder~kijiji-scraper"

# Hard cap on results per request — we want a few richly-detailed comps, not hundreds.
# The methodology values a vehicle off a small, well-matched comp set; pulling more just
# burns Apify credit. Every collect_* entrypoint clamps its limit to this.
MAX_RESULTS_CAP = 40

# Alberta FB Marketplace city URLs
FB_CITY_URLS = {
    "edmonton": "https://www.facebook.com/marketplace/edmonton/",
    "calgary": "https://www.facebook.com/marketplace/calgary/",
    "alberta": "https://www.facebook.com/marketplace/edmonton/",
}

KIJIJI_AB_CARS_URL = "https://www.kijiji.ca/b-cars-trucks/alberta/c174l9003"


# ── Apify helpers ────────────────────────────────────────────────────────────


def _run_actor(actor_id: str, input_data: dict, timeout_secs: int = 300) -> list[dict]:
    """Run an Apify actor and return the dataset items."""
    if not APIFY_TOKEN:
        raise RuntimeError(
            "APIFY_TOKEN not set in .env — get yours at https://console.apify.com/account/integrations"
        )

    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

    run_url = f"{APIFY_BASE}/acts/{actor_id}/runs"
    resp = requests.post(run_url, json=input_data, headers=headers, timeout=30)
    resp.raise_for_status()
    run = resp.json()["data"]
    run_id = run["id"]
    print(f"  Actor run started: {run_id} (status: {run['status']})")

    status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout_secs:
            raise TimeoutError(f"Actor run {run_id} timed out after {timeout_secs}s")

        time.sleep(5)
        resp = requests.get(status_url, headers=headers, timeout=10)
        resp.raise_for_status()
        status_data = resp.json()["data"]
        status = status_data["status"]
        print(f"  [{int(elapsed):3d}s] Status: {status}")

        if status == "SUCCEEDED":
            break
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Actor run {run_id} ended with status: {status}")

    dataset_id = status_data["defaultDatasetId"]
    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?format=json&limit=1000"
    resp = requests.get(items_url, headers=headers, timeout=30)
    resp.raise_for_status()
    items = resp.json()
    print(f"  Fetched {len(items)} items from dataset {dataset_id}")
    return items


# ── Facebook Marketplace ─────────────────────────────────────────────────────


def _build_fb_url(
    location: str,
    query: str,
    min_year=None,
    max_year=None,
    min_price=None,
    max_price=None,
) -> str:
    base = FB_CITY_URLS.get(
        location.lower(), f"https://www.facebook.com/marketplace/{location.lower()}/"
    )
    url = f"{base}search/?query={query.replace(' ', '+')}&exact=false"
    # FB Marketplace honours these as URL params — lets us target the subject's generation.
    for k, v in (
        ("minPrice", min_price),
        ("maxPrice", max_price),
        ("minYear", min_year),
        ("maxYear", max_year),
    ):
        if v:
            url += f"&{k}={v}"
    return url


def _parse_fb_price(price_obj) -> int | None:
    """Parse FB listingPrice object to CAD cents. Prefers the plain dollar `amount`."""
    if not isinstance(price_obj, dict):
        return None
    try:
        amount = price_obj.get("amount")
        if amount is not None:
            return int(round(float(str(amount).replace(",", "")) * 100))
        formatted = (
            price_obj.get("formatted_amount") or price_obj.get("formatted_price") or ""
        )
        cleaned = re.sub(r"[^\d.]", "", formatted)
        if cleaned:
            return int(round(float(cleaned) * 100))
    except (ValueError, TypeError):
        pass
    return None


def _parse_km_text(text: str) -> int | None:
    """Parse an odometer from free text. Handles '259K km', '140,000 km',
    European '72.000 km' (= 72,000 — NOT 72), '72 000 km', '12.5k km', and miles.
    Sanity-bounded to 100–1,000,000 km so the European-decimal bug can't slip a 72 through.
    """
    if not text:
        return None
    m = re.search(
        r"(\d[\d.,\s]*?)\s*([kK])?\s*(km|kms|kilometre?s?|mi|miles)\b", text, re.I
    )
    if not m:
        return None
    num_raw, k_suffix, unit = m.group(1).strip(), m.group(2), m.group(3)
    try:
        if k_suffix:  # '139k' / '12.5k' → ×1000
            num = float(num_raw.replace(",", "").replace(" ", "")) * 1000
        else:  # strip thousands separators (, . space)
            cleaned = re.sub(r"[.,\s]", "", num_raw)
            if not cleaned.isdigit():
                return None
            num = float(cleaned)
    except ValueError:
        return None
    if unit.lower().startswith("mi"):  # miles → km
        num *= 1.60934
    km = int(num)
    return km if 100 <= km <= 1_000_000 else None


def _parse_odometer_from_subtitles(subtitles) -> int | None:
    """FB shows mileage in the listing subtitle, e.g. '259K km' or '140,000 km'."""
    for s in subtitles or []:
        text = (s.get("subtitle") if isinstance(s, dict) else str(s)) or ""
        km = _parse_km_text(text)
        if km is not None:
            return km
    return None


def _fb_odometer(item: dict, title: str | None, desc: str | None) -> int | None:
    """Odometer from the subtitle block first (most reliable), then the title/description
    as a fallback — many search-level rows carry km only in the title."""
    return (
        _parse_odometer_from_subtitles(item.get("customSubTitlesWithRenderingFlags"))
        or _parse_km_text(title or "")
        or _parse_km_text(desc or "")
    )


def _extract_fb_photos(item: dict) -> tuple[list[str], str | None]:
    """Pull image URLs from listingPhotos + primaryListingPhoto."""
    urls = []
    for p in item.get("listingPhotos") or []:
        if isinstance(p, dict):
            uri = (p.get("image") or {}).get("uri") or p.get("uri")
            if uri:
                urls.append(uri)
    main = ((item.get("primaryListingPhoto") or {}).get("image") or {}).get("uri")
    if not main and urls:
        main = urls[0]
    return urls, main


def _fb_text(value) -> str | None:
    """Several FB fields arrive as {'text': '...'} wrappers; unwrap to a plain string."""
    if isinstance(value, dict):
        value = value.get("text")
    return value if isinstance(value, str) else None


def _parse_fb_item(item: dict) -> dict | None:
    """Normalize a FB Marketplace listing (includeListingDetails schema) to our table."""
    price_cents = _parse_fb_price(item.get("listingPrice"))
    if not price_cents or price_cents <= 0:
        return None

    title = (
        _fb_text(item.get("listingTitle")) or _fb_text(item.get("customTitle")) or ""
    )
    year, make, model = _parse_vehicle_title(title)

    # Location: prefer "Edmonton, AB" locationText, fall back to reverse_geocode
    city, province = None, None
    loc_text = _fb_text(item.get("locationText")) or ""
    if "," in loc_text:
        parts = [x.strip() for x in loc_text.split(",", 1)]
        city, province = parts[0] or None, parts[1] or None
    elif loc_text:
        city = loc_text
    if not city:
        geo = (item.get("location") or {}).get("reverse_geocode") or {}
        city, province = geo.get("city"), geo.get("state")

    desc = _fb_text(item.get("description"))

    odometer_km = _fb_odometer(item, title, desc)

    posted_at = None
    ts = item.get("timestamp")
    if ts:
        try:
            posted_at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    photo_urls, main_photo = _extract_fb_photos(item)

    return {
        "external_id": f"fb_{item.get('id', '')}",
        "source": "facebook_marketplace",
        "year": year,
        "make": make,
        "model": model,
        "trim": None,
        "body_style": None,
        "vin": None,
        "color": None,
        "engine": None,
        "transmission": None,
        "driveline": None,
        "fuel_type": None,
        "odometer_km": odometer_km,
        "title": title or None,
        "asking_price": price_cents,
        "location_city": city,
        "location_province": province,
        "seller_type": None,  # not exposed by this actor; left for vision/enrichment
        "listing_url": item.get("itemUrl"),
        "description": desc,
        "is_sold": bool(item.get("isSold", False)),
        "posted_at": posted_at,
        "photo_urls": photo_urls or None,
        "photo_count": len(photo_urls),
        "main_photo_url": main_photo,
        "raw_json": item,
    }


def collect_facebook(
    location: str,
    query: str,
    max_listings: int = 20,
    min_year=None,
    max_year=None,
    min_price=None,
    max_price=None,
) -> int:
    """Collect FB Marketplace listings for a vehicle query (targeted + capped + detailed)."""
    cap = max(1, min(int(max_listings), MAX_RESULTS_CAP))
    print(f"\n[Facebook Marketplace] Searching: '{query}' in {location} (limit {cap})")
    url = _build_fb_url(location, query, min_year, max_year, min_price, max_price)
    print(f"  URL: {url}")

    # resultsLimit is the actor's real cap (maxItems is ignored); includeListingDetails
    # returns odometer subtitle, description, and full-res photos.
    input_data = {
        "startUrls": [{"url": url}],
        "resultsLimit": cap,
        "includeListingDetails": True,
    }

    items = _run_actor(FB_ACTOR_ID, input_data)
    parsed = [_parse_fb_item(i) for i in items]
    valid = [p for p in parsed if p is not None]
    return _upsert_listings(valid, source="facebook_marketplace")


# ── Kijiji ───────────────────────────────────────────────────────────────────


def _parse_kijiji_price(item: dict) -> int | None:
    """
    Extract price from Kijiji item in CAD cents.
    calm_builder actor stores price inside schemaOrgCar.offers.price (a string like "11800").
    Falls back to top-level price field for safety.
    """
    # Primary: schemaOrgCar.offers.price
    car = item.get("schemaOrgCar") or {}
    offers = car.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price_str = offers.get("price")
    currency = offers.get("priceCurrency", "CAD")
    if price_str and currency == "CAD":
        try:
            return int(float(str(price_str).replace(",", "").strip()) * 100)
        except (ValueError, TypeError):
            pass

    # Fallback: top-level price field
    price = item.get("price")
    if price is None:
        return None
    try:
        if isinstance(price, (int, float)):
            return int(price * 100)
        if isinstance(price, str):
            clean = price.replace("$", "").replace(",", "").strip()
            return int(float(clean) * 100)
        if isinstance(price, dict):
            amount = price.get("amount") or price.get("value")
            if amount is not None:
                return int(float(amount) * 100)
    except (ValueError, TypeError):
        pass
    return None


def _km_from_schema(item: dict) -> int | None:
    """Extract odometer km from schemaOrgCar.mileageFromOdometer."""
    car = item.get("schemaOrgCar") or {}
    mfo = car.get("mileageFromOdometer") or {}
    if isinstance(mfo, dict):
        val = mfo.get("value")
        unit = mfo.get("unitCode", "KMT")
        if val:
            km = int(float(val))
            # Convert miles to km if needed
            if unit in ("SMI", "MI"):
                km = int(km * 1.60934)
            return km
    return None


def _km_from_mileage_analysis(item: dict) -> int | None:
    ma = item.get("mileageAnalysis")
    if ma and isinstance(ma, dict):
        v = ma.get("value")
        if v:
            return int(v)
    return None


def _normalize_driveline(raw: str) -> str | None:
    """Normalize Kijiji driveWheelConfiguration to our 4WD/AWD/FWD/RWD schema."""
    if not raw:
        return None
    r = raw.upper().strip()
    if "4WD" in r or "FOUR" in r or "4X4" in r:
        return "4WD"
    if "AWD" in r or "ALL" in r:
        return "AWD"
    if "FWD" in r or "FRONT" in r:
        return "FWD"
    if "RWD" in r or "REAR" in r:
        return "RWD"
    return None


def _extract_kijiji_photos(item: dict) -> tuple[list[str], str | None]:
    """Pull image URLs from schemaOrgCar.image[*]; main photo from meta.image."""
    urls = []
    for img in (item.get("schemaOrgCar") or {}).get("image") or []:
        if isinstance(img, dict):
            uri = img.get("contentUrl") or img.get("url")
            if uri:
                urls.append(uri)
        elif isinstance(img, str):
            urls.append(img)
    main = (item.get("meta") or {}).get("image") or (urls[0] if urls else None)
    return urls, main


def _parse_kijiji_item(item: dict) -> dict | None:
    price_cents = _parse_kijiji_price(item)
    if not price_cents or price_cents <= 0:
        return None

    car = item.get("schemaOrgCar") or {}

    year_raw = car.get("vehicleModelDate") or item.get("year")
    year = int(year_raw) if year_raw else None

    make = (car.get("brand", {}) or {}).get("name") or item.get("make") or ""
    make = make.strip() or None

    model = (car.get("model") or item.get("model") or "").strip() or None
    trim = (car.get("vehicleConfiguration") or item.get("trim") or "").strip() or None
    vin = (
        car.get("vehicleIdentificationNumber") or item.get("vin") or ""
    ).strip() or None
    color = (car.get("color") or item.get("color") or "").strip() or None
    transmission = (
        car.get("vehicleTransmission") or item.get("transmission") or ""
    ).strip() or None
    body_style = (car.get("bodyType") or item.get("body_style") or "").strip() or None
    fuel_type = (car.get("fuelType") or item.get("fuel_type") or "").strip() or None

    # Driveline: prefer schemaOrgCar.driveWheelConfiguration
    driveline_raw = car.get("driveWheelConfiguration") or item.get("driveline") or ""
    driveline = _normalize_driveline(driveline_raw)

    # Odometer: prefer schemaOrgCar.mileageFromOdometer, fallback to mileageAnalysis
    odometer_km = (
        _km_from_schema(item)
        or _km_from_mileage_analysis(item)
        or item.get("odometer_km")
        or item.get("mileage")
    )

    # Location
    loc = item.get("location") or {}
    if isinstance(loc, str):
        city, province = loc, "AB"
    else:
        city = loc.get("city") or loc.get("mapAddress") or ""
        province = loc.get("province") or loc.get("regionName") or "AB"

    # Seller type: check userType first, then infer from websiteUrl / numberOfListings
    seller_profile = item.get("sellerProfile") or {}
    user_type = seller_profile.get("userType") or ""
    if user_type.upper() in ("BUSINESS", "DEALER", "PROFESSIONAL"):
        seller_type = "dealer"
    elif seller_profile.get("websiteUrl"):
        seller_type = "dealer"
    elif (seller_profile.get("numberOfListings") or 0) > 5:
        seller_type = "dealer"
    else:
        seller_type = "private"

    # Title and URL from meta
    meta = item.get("meta") or {}
    if isinstance(meta, dict):
        title = meta.get("title") or item.get("url") or ""
        url = meta.get("url") or item.get("url") or ""
    else:
        title = item.get("title") or item.get("url") or ""
        url = item.get("url") or ""

    # Trim: vehicleConfiguration often has the full trim string; strip make/model if present
    if trim and model and model.upper() in trim.upper():
        trim = trim.replace(model, "").replace(model.upper(), "").strip(" |,-")
    if not trim:
        trim = None

    # If year/make missing from structured fields, parse from title
    if not year or not make:
        t_year, t_make, t_model = _parse_vehicle_title(title or "")
        year = year or t_year
        make = make or t_make
        model = model or t_model

    listing_id = str(item.get("listingId") or item.get("id") or "")
    if not listing_id:
        return None

    posted_at = None
    activation_date = item.get("lastPostedAt") or item.get("activationDate")
    if activation_date:
        try:
            posted_at = datetime.fromisoformat(activation_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    photo_urls, main_photo = _extract_kijiji_photos(item)

    return {
        "external_id": f"kijiji_{listing_id}",
        "source": "kijiji",
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "body_style": body_style or None,
        "vin": vin or None,
        "color": color or None,
        "engine": None,
        "transmission": transmission or None,
        "driveline": driveline or None,
        "fuel_type": fuel_type or None,
        "odometer_km": int(odometer_km) if odometer_km else None,
        "title": title or None,
        "asking_price": price_cents,
        "location_city": city or None,
        "location_province": province or "AB",
        "seller_type": seller_type,
        "listing_url": url or None,
        "description": item.get("description"),
        "is_sold": False,
        "posted_at": posted_at,
        "photo_urls": photo_urls or None,
        "photo_count": len(photo_urls),
        "main_photo_url": main_photo,
        "raw_json": item,
    }


def collect_kijiji(url: str = None, max_listings: int = 20) -> int:
    """Collect Kijiji listings from a category/search URL."""
    target_url = url or KIJIJI_AB_CARS_URL
    cap = max(1, min(int(max_listings), MAX_RESULTS_CAP))
    print(f"\n[Kijiji] Scraping: {target_url} (limit {cap})")

    input_data = {
        "startUrls": [{"url": target_url}],
        "maxListings": cap,
        "fetchDetails": True,
        "fetchNewListings": True,
        "fetchMileageAnalysis": True,
        "fetchSellerProfile": True,
        "fetchSellerMetrics": True,
    }

    items = _run_actor(KIJIJI_ACTOR_ID, input_data)
    parsed = [_parse_kijiji_item(i) for i in items]
    valid = [p for p in parsed if p is not None]
    skipped = len(items) - len(valid)
    if skipped:
        print(f"  Skipped {skipped} items (no price or no listing ID)")
    return _upsert_listings(valid, source="kijiji")


# ── Title parser ─────────────────────────────────────────────────────────────

_COMMON_MAKES = {
    "toyota",
    "honda",
    "ford",
    "chevrolet",
    "chevy",
    "dodge",
    "jeep",
    "hyundai",
    "kia",
    "nissan",
    "mazda",
    "subaru",
    "volkswagen",
    "vw",
    "bmw",
    "mercedes",
    "audi",
    "lexus",
    "infiniti",
    "acura",
    "ram",
    "gmc",
    "cadillac",
    "buick",
    "lincoln",
    "chrysler",
    "mitsubishi",
    "volvo",
    "land rover",
    "landrover",
    "porsche",
}


def _parse_vehicle_title(title: str) -> tuple[int | None, str | None, str | None]:
    """Best-effort extraction of year, make, model from a listing title."""
    if not title:
        return None, None, None
    parts = title.strip().split()
    year = None
    make = None
    model = None

    for i, part in enumerate(parts):
        if part.isdigit() and 1990 <= int(part) <= 2030:
            year = int(part)
            remaining = parts[i + 1 :]
            for make_name in sorted(_COMMON_MAKES, key=len, reverse=True):
                mk_parts = make_name.split()
                chunk = " ".join(remaining[: len(mk_parts)]).lower()
                if chunk == make_name:
                    make = " ".join(remaining[: len(mk_parts)]).title()
                    model_parts = remaining[len(mk_parts) :]
                    if model_parts:
                        model = " ".join(model_parts[:2]).title()
                    break
            break

    return year, make, model


# ── DB upsert ────────────────────────────────────────────────────────────────


def _upsert_listings(listings: list[dict], source: str) -> int:
    """Upsert parsed listings into retail_listings table. Returns count inserted/updated."""
    import json

    if not listings:
        print(f"  No valid listings to upsert for {source}")
        return 0

    conn = get_conn()
    cursor = get_cursor(conn)
    upserted = 0

    for row in listings:
        try:
            cursor.execute(
                """
                INSERT INTO retail_listings (
                    external_id, source,
                    year, make, model, trim, body_style, vin, color, engine,
                    transmission, driveline, fuel_type, odometer_km,
                    title, asking_price, location_city, location_province,
                    seller_type, listing_url, description, is_sold, posted_at,
                    photo_urls, photo_count, main_photo_url,
                    raw_json, collected_at, last_seen_at
                ) VALUES (
                    %(external_id)s, %(source)s,
                    %(year)s, %(make)s, %(model)s, %(trim)s, %(body_style)s,
                    %(vin)s, %(color)s, %(engine)s,
                    %(transmission)s, %(driveline)s, %(fuel_type)s, %(odometer_km)s,
                    %(title)s, %(asking_price)s, %(location_city)s, %(location_province)s,
                    %(seller_type)s, %(listing_url)s, %(description)s, %(is_sold)s,
                    %(posted_at)s,
                    %(photo_urls)s, %(photo_count)s, %(main_photo_url)s,
                    %(raw_json)s, NOW(), NOW()
                )
                ON CONFLICT (external_id) DO UPDATE SET
                    asking_price    = EXCLUDED.asking_price,
                    is_sold         = EXCLUDED.is_sold,
                    year            = COALESCE(EXCLUDED.year, retail_listings.year),
                    make            = COALESCE(EXCLUDED.make, retail_listings.make),
                    model           = COALESCE(EXCLUDED.model, retail_listings.model),
                    odometer_km     = COALESCE(EXCLUDED.odometer_km, retail_listings.odometer_km),
                    title           = COALESCE(EXCLUDED.title, retail_listings.title),
                    description     = COALESCE(EXCLUDED.description, retail_listings.description),
                    location_city   = COALESCE(EXCLUDED.location_city, retail_listings.location_city),
                    location_province = COALESCE(EXCLUDED.location_province, retail_listings.location_province),
                    posted_at       = COALESCE(EXCLUDED.posted_at, retail_listings.posted_at),
                    photo_urls      = EXCLUDED.photo_urls,
                    photo_count     = EXCLUDED.photo_count,
                    main_photo_url  = EXCLUDED.main_photo_url,
                    last_seen_at    = NOW(),
                    raw_json        = EXCLUDED.raw_json
            """,
                {
                    "photo_urls": None,
                    "photo_count": None,
                    "main_photo_url": None,
                    **row,
                    "raw_json": json.dumps(row["raw_json"]),
                },
            )
            upserted += 1
        except Exception as e:
            print(f"  Warning: failed to upsert {row.get('external_id')}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cursor.close()
    conn.close()
    print(f"  Upserted {upserted} listings into retail_listings ({source})")
    return upserted


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect retail vehicle comps via Apify"
    )
    parser.add_argument(
        "--source", choices=["facebook", "kijiji", "all"], default="all"
    )
    parser.add_argument(
        "--location", default="edmonton", help="City for FB Marketplace (e.g. edmonton)"
    )
    parser.add_argument(
        "--query", default="used cars trucks", help="Search query for FB Marketplace"
    )
    parser.add_argument(
        "--url", default=None, help="Specific Kijiji category/search URL"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        help=f"Max listings per source (hard-capped at {MAX_RESULTS_CAP})",
    )
    parser.add_argument(
        "--min-year", type=int, default=None, help="FB: minimum model year"
    )
    parser.add_argument(
        "--max-year", type=int, default=None, help="FB: maximum model year"
    )
    parser.add_argument(
        "--min-price", type=int, default=None, help="FB: minimum price ($)"
    )
    args = parser.parse_args()

    total = 0
    if args.source in ("facebook", "all"):
        total += collect_facebook(
            args.location,
            args.query,
            args.max,
            min_year=args.min_year,
            max_year=args.max_year,
            min_price=args.min_price,
        )
    if args.source in ("kijiji", "all"):
        total += collect_kijiji(args.url, args.max)

    print(f"\nDone. Total upserted: {total}")
