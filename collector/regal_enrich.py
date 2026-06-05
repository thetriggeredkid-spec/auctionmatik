"""
Regal Listing Enricher
Fetches the full details page for each Regal listing and extracts:
  - All photo URLs (800x600w from CloudFront, via data-splide-lazy attributes)
  - Heat map damage data: {panel, severity} from overlay image filenames
    (severity: yellow=minor, orange=moderate, red=severe)
  - At-a-glance condition: windshield, keys, starts, drivable, battery, tire tread
  - Carfax URL (constructed from regal_id + vin)

Stores results in regal_sold.photo_urls, .heat_map_damage, .condition_detail, .carfax_url
Can also run against regal_listings (active listings).

Usage:
    python3 -m collector.regal_enrich                    # enrich all un-enriched regal_sold records
    python3 -m collector.regal_enrich --id 429954        # single listing
    python3 -m collector.regal_enrich --table listings   # enrich regal_listings instead
    python3 -m collector.regal_enrich --limit 100        # enrich next 100 un-enriched
    python3 -m collector.regal_enrich --re-enrich        # re-enrich already-enriched records

Requires: pip install beautifulsoup4 lxml
"""

import re
import sys
import json
import time
import argparse
import requests

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from db.connection import get_conn, get_cursor

SITE_BASE = "https://regalauctions.com"
DELAY_SECONDS = 0.5  # polite delay between requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": "https://regalauctions.com/marketReport.php",
}

# Heat map severity colour → human label
SEVERITY_MAP = {
    "yellow": "minor",
    "orange": "moderate",
    "red":    "severe",
}


# ── HTML fetch ───────────────────────────────────────────────────────────────

def _fetch_details_html(details_link: str) -> str:
    """
    Fetch the public .htm detail page — it carries the full photo gallery
    (data-splide-lazy CloudFront URLs). The old marketReport.php?a=details
    endpoint no longer serves photos.
    """
    url = details_link if details_link.startswith("http") else SITE_BASE + details_link
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


# ── Photo URLs ───────────────────────────────────────────────────────────────

def _extract_photo_urls(html: str) -> list[str]:
    """
    Extract the full photo gallery as clean 800x600w CloudFront URLs.
    The .htm page lists each photo as a thumbnail (100x75) and a splide slide;
    the first slide is the overlay-repo (heat-map) version. We normalize every
    CloudFront jpg to the clean /800x600w/ form and dedupe, preserving order.
    """
    raw = re.findall(r"https://d2qmx62gg6ysq0\.cloudfront\.net/\d+/[^\s\"'<>]+\.jpg", html)
    urls, seen = [], set()
    for u in raw:
        u = u.replace("/overlay-repo/", "/")           # drop heat-map overlay → clean photo
        u = re.sub(r"/\d+x\d+w?/", "/800x600w/", u)    # upscale any thumbnail size
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


# ── Heat map damage ──────────────────────────────────────────────────────────

def _extract_heat_map(html: str) -> list[dict]:
    """
    Parse damage heat map from overlay image filenames.
    URL pattern: /images/heat-map/{type}/hm-{type}-{color}-{panel}.png
    Returns: [{panel: str, severity: str, color: str}]
    """
    # Match overlay images (not the base image)
    pattern = r'/images/heat-map/[^/]+/hm-[^-]+-([a-z]+)-([^"\']+)\.png'
    matches = re.findall(pattern, html)
    damage = []
    seen = set()
    for color, panel_raw in matches:
        panel = panel_raw.replace("_", " ")
        key = f"{color}:{panel}"
        if key in seen:
            continue
        seen.add(key)
        damage.append({
            "panel":    panel,
            "color":    color,
            "severity": SEVERITY_MAP.get(color, color),
        })
    # Sort by severity (red first, then orange, then yellow)
    sev_order = {"red": 0, "orange": 1, "yellow": 2}
    damage.sort(key=lambda x: sev_order.get(x["color"], 9))
    return damage


# ── At-a-glance + tire tread ─────────────────────────────────────────────────

def _extract_condition_detail(html: str) -> dict:
    """
    Parse the 'AT A GLANCE' section from the details page HTML.
    Returns dict with windshield, keys, starts, drivable, battery,
    tire_lf, tire_rf, tire_lr, tire_rr (all in 32nds as strings).
    """
    detail = {}

    # Windshield condition
    m = re.search(r'Windshield.*?<[^>]+>([^<]{2,50})</[^>]+>', html, re.IGNORECASE | re.DOTALL)
    if m:
        detail["windshield"] = m.group(1).strip()

    # Number of keys
    m = re.search(r'# of Keys.*?<[^>]+>(\d+)</[^>]+>', html, re.IGNORECASE | re.DOTALL)
    if m:
        detail["keys"] = int(m.group(1))

    # Engine starts
    m = re.search(r'Engine Starts.*?<[^>]+>(Yes|No)</[^>]+>', html, re.IGNORECASE | re.DOTALL)
    if m:
        detail["starts"] = m.group(1).lower() == "yes"

    # Drivable
    m = re.search(r'Drivable.*?<[^>]+>(Yes|No)</[^>]+>', html, re.IGNORECASE | re.DOTALL)
    if m:
        detail["drivable"] = m.group(1).lower() == "yes"

    # Battery condition
    m = re.search(r'Battery Condition.*?<[^>]+>([^<]{2,30})</[^>]+>', html, re.IGNORECASE | re.DOTALL)
    if m:
        detail["battery"] = m.group(1).strip()

    # Tire tread depths — pattern "LF:\s*5/32"
    for corner in ("LF", "RF", "LR", "RR"):
        m = re.search(rf'{corner}:.*?(\d+/32)', html, re.IGNORECASE | re.DOTALL)
        if m:
            detail[f"tire_{corner.lower()}"] = m.group(1)

    return detail


# ── Carfax URL ───────────────────────────────────────────────────────────────

def _build_carfax_url(regal_id: str, vin: str) -> str | None:
    """Construct Regal's Carfax redirect URL from regal_id and VIN."""
    if not vin or not regal_id:
        return None
    return f"https://regalauctions.com/carfax.php?id={regal_id}&vin={vin}&loc=declarations"


def _extract_carfax_url(html: str, regal_id: str, vin: str) -> str | None:
    """Try to extract direct Carfax URL from HTML, fall back to constructed URL."""
    # Look for direct carfax.ca link
    m = re.search(r'href="(https://vhr\.carfax\.ca/[^"]+)"', html)
    if m:
        return m.group(1)
    # Look for Regal's own carfax redirect
    m = re.search(r'href="(/carfax\.php[^"]+)"', html)
    if m:
        return "https://regalauctions.com" + m.group(1)
    # Construct from known pattern
    return _build_carfax_url(regal_id, vin)


# ── DB update ────────────────────────────────────────────────────────────────

def _update_record(conn, cursor, regal_id: str, table: str, enrichment: dict):
    photos = enrichment["photo_urls"] or []
    main_photo = photos[0] if photos else None
    cursor.execute(f"""
        UPDATE {table} SET
            photo_urls       = %s,
            photo_count      = %s,
            main_photo_url   = COALESCE(%s, main_photo_url),
            heat_map_damage  = %s,
            condition_detail = %s,
            carfax_url       = %s,
            enriched_at      = NOW()
        WHERE regal_id = %s
    """, (
        photos or None,
        len(photos),
        main_photo,
        json.dumps(enrichment["heat_map_damage"]) if enrichment["heat_map_damage"] else None,
        json.dumps(enrichment["condition_detail"]) if enrichment["condition_detail"] else None,
        enrichment["carfax_url"],
        regal_id,
    ))
    conn.commit()


# ── Main enrichment logic ────────────────────────────────────────────────────

def _get_details_link(cursor, regal_id: str, table: str) -> str | None:
    cursor.execute(f"SELECT raw_json->>'detailsLink' AS dl FROM {table} WHERE regal_id = %s LIMIT 1",
                   (regal_id,))
    row = cursor.fetchone()
    return row.get("dl") if row else None


def enrich_one(regal_id: str, vin: str = None, table: str = "regal_sold", conn=None,
               details_link: str = None) -> dict:
    """
    Enrich a single listing by regal_id. Needs the listing's detailsLink (.htm page)
    to reach the photo gallery — looked up from raw_json if not supplied.
    Returns the enrichment dict (also updates DB if conn provided).
    """
    if conn is not None and (not details_link or not vin):
        cur = get_cursor(conn)
        cur.execute(f"SELECT raw_json->>'detailsLink' AS dl, vin FROM {table} WHERE regal_id = %s LIMIT 1",
                    (regal_id,))
        row = cur.fetchone()
        cur.close()
        if row:
            details_link = details_link or row.get("dl")
            vin = vin or row.get("vin")
    if not details_link:
        raise RuntimeError(f"no detailsLink for {regal_id} — cannot reach photo gallery")

    html = _fetch_details_html(details_link)

    photo_urls = _extract_photo_urls(html)
    heat_map = _extract_heat_map(html)
    condition = _extract_condition_detail(html)
    carfax_url = _extract_carfax_url(html, regal_id, vin or "")

    enrichment = {
        "photo_urls":      photo_urls,
        "heat_map_damage": heat_map,
        "condition_detail": condition,
        "carfax_url":      carfax_url,
    }

    if conn:
        cursor = conn.cursor()
        _update_record(conn, cursor, regal_id, table, enrichment)
        cursor.close()

    return enrichment


def enrich_batch(table: str = "regal_sold", limit: int = None, re_enrich: bool = False):
    """
    Enrich a batch of un-enriched records from regal_sold or regal_listings.
    """
    conn = get_conn()
    cursor = get_cursor(conn)

    where = "" if re_enrich else "WHERE enriched_at IS NULL"
    limit_clause = f"LIMIT {limit}" if limit else ""

    cursor.execute(f"""
        SELECT regal_id, vin, raw_json->>'detailsLink' AS details_link
        FROM {table}
        {where}
        ORDER BY regal_id DESC
        {limit_clause}
    """)
    records = cursor.fetchall()
    print(f"Enriching {len(records)} records from {table}...")

    enriched = 0
    failed = 0

    for row in records:
        regal_id = row["regal_id"]
        vin = row.get("vin") or ""
        try:
            result = enrich_one(regal_id, vin=vin, table=table, conn=conn,
                                details_link=row.get("details_link"))
            enriched += 1
            photo_count = len(result["photo_urls"])
            damage_count = len(result["heat_map_damage"])
            print(f"  [{enriched:4d}] {regal_id} — {photo_count} photos, "
                  f"{damage_count} damage panels, "
                  f"carfax={'yes' if result['carfax_url'] else 'no'}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {regal_id}: {e}")

        time.sleep(DELAY_SECONDS)

    cursor.close()
    conn.close()
    print(f"\nDone. Enriched: {enriched}, Failed: {failed}")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich Regal listings with photos, heat map, and condition data")
    parser.add_argument("--id", type=str, help="Single regal_id to enrich (for testing)")
    parser.add_argument("--vin", type=str, default="", help="VIN (used with --id)")
    parser.add_argument("--table", choices=["regal_sold", "regal_listings"], default="regal_sold")
    parser.add_argument("--limit", type=int, help="Max records to enrich")
    parser.add_argument("--re-enrich", action="store_true", help="Re-enrich already-enriched records")
    args = parser.parse_args()

    if args.id:
        # Single record — connect to DB and update
        conn = get_conn()
        result = enrich_one(args.id, vin=args.vin, table=args.table, conn=conn)
        conn.close()
        print(f"\nResult for {args.id}:")
        print(f"  Photos:        {len(result['photo_urls'])}")
        print(f"  Damage panels: {len(result['heat_map_damage'])}")
        for d in result["heat_map_damage"]:
            print(f"    {d['severity']:8s}  {d['panel']}")
        print(f"  Condition:     {result['condition_detail']}")
        print(f"  Carfax URL:    {result['carfax_url']}")
        print(f"\nPhoto URLs (first 5):")
        for u in result["photo_urls"][:5]:
            print(f"  {u}")
    else:
        enrich_batch(table=args.table, limit=args.limit, re_enrich=args.re_enrich)
