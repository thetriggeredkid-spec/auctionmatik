"""
Ad ingestion — turn a pasted listing URL into a subject vehicle for appraisal.

Sources (Phase D): Facebook Marketplace, Kijiji, AutoTrader.ca. Each ad is messy in
its own way, so we gather the best structured data we can per source, then run ONE
cheap Haiku extraction to normalize/fill the spec (year/make/model/trim/km/vin) from
all available text. The caller (mapper.appraise_subject) hardens the VIN via NHTSA and
runs vision over the photos.

  ingest_ad(url) -> {
    vehicle: {year, make, model, trim, driveline, engine, cab, odometer_km, vin},
    asking_price_dollars: float|None,
    photos: [url], seller_type: 'private'|'dealer', source: str, listing_url: str,
  }

FB needs the Apify actor (its VDP is JS/login-gated); Kijiji + AutoTrader are fetched
directly (they embed schema.org JSON-LD).
"""

import os
import re
import json
from urllib.parse import urlparse

import requests

_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
}


# ── source detection ──────────────────────────────────────────────────────────


def ingest_ad(url: str) -> dict:
    host = (urlparse(url).netloc or "").lower()
    if "facebook." in host:
        data, source = _fetch_fb(url), "facebook"
    elif "kijiji." in host:
        data, source = _fetch_kijiji(url), "kijiji"
    elif "autotrader." in host:
        data, source = _fetch_autotrader(url), "autotrader"
    else:
        raise RuntimeError(f"unsupported ad source: {host or url}")

    vehicle = _extract_spec(source, data)
    # When the ad exposes a VIN (AutoTrader always does), decode it to fill blanks — this is
    # far more reliable than parsing make/model/year out of a sparse title/slug.
    if vehicle.get("vin"):
        try:
            from collector.vin_decode import decode_vin

            dec = decode_vin(vehicle["vin"]) or {}
            for k in ("year", "make", "model", "trim", "driveline", "engine", "cab"):
                if not vehicle.get(k) and dec.get(k):
                    vehicle[k] = dec[k]
        except Exception as e:  # noqa: BLE001
            print(f"[ad_ingest vin] {e}")
    return {
        "vehicle": vehicle,
        "asking_price_dollars": data.get("price"),
        "photos": (data.get("photos") or [])[:12],
        "seller_type": data.get("seller_type") or "private",
        "source": source,
        "listing_url": url,
    }


# ── per-source fetch → a common bundle {title, description, jsonld[], price, photos,
#    seller_type, slug, structured{}} ───────────────────────────────────────────


def _fetch_fb(url: str) -> dict:
    from collector.retail_comps import (
        _run_actor,
        FB_ACTOR_ID,
        _fb_text,
        _parse_fb_price,
        _extract_fb_photos,
    )

    items = _run_actor(
        FB_ACTOR_ID,
        {"startUrls": [{"url": url}], "resultsLimit": 1, "includeListingDetails": True},
        timeout_secs=180,
    )
    if not items:
        raise RuntimeError("Facebook actor returned no listing for that URL")
    it = items[0]
    photos, _main = _extract_fb_photos(it)
    cents = _parse_fb_price(it.get("listingPrice"))
    return {
        "title": _fb_text(it.get("listingTitle"))
        or _fb_text(it.get("customTitle"))
        or "",
        "description": _fb_text(it.get("description")) or "",
        "jsonld": [],
        "price": (cents / 100) if cents else None,
        "photos": photos,
        "seller_type": "private",  # FB Marketplace is overwhelmingly private
        "slug": "",
        "structured": {},
    }


def _fetch_kijiji(url: str) -> dict:
    html = requests.get(url, headers=_UA, timeout=20).text
    ld = _jsonld(html)
    veh = _first_ld(ld, ("Vehicle", "Car", "Product")) or {}
    offers = veh.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    structured = {}
    if veh.get("vehicleModelDate"):
        structured["year"] = veh["vehicleModelDate"]
    if (
        (veh.get("brand") or {}).get("name")
        if isinstance(veh.get("brand"), dict)
        else veh.get("brand")
    ):
        structured["make"] = (
            veh["brand"].get("name")
            if isinstance(veh.get("brand"), dict)
            else veh.get("brand")
        )
    if veh.get("model"):
        structured["model"] = veh["model"]
    mfo = veh.get("mileageFromOdometer") or {}
    if isinstance(mfo, dict) and mfo.get("value"):
        structured["odometer_km"] = mfo["value"]
    price = _to_price(offers.get("price"))
    photos = _ld_images(veh) or _og_images(html)
    seller = (
        "dealer"
        if re.search(r'"dealerName"|/b-cars-trucks/.*?/dealer|isDealer', html, re.I)
        else "private"
    )
    return {
        "title": veh.get("name") or _og(html, "title") or "",
        "description": veh.get("description") or "",
        "jsonld": ld,
        "price": price,
        "photos": photos,
        "seller_type": seller,
        "slug": urlparse(url).path,
        "structured": structured,
    }


def _fetch_autotrader(url: str) -> dict:
    html = requests.get(url, headers=_UA, timeout=20).text
    ld = _jsonld(html)
    prod = _first_ld(ld, ("Car", "Vehicle", "Product")) or {}
    offers = prod.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = _to_price(offers.get("price"))
    # JSON-LD on AutoTrader lacks year/km/vin — pull them from the page HTML. VIN is the
    # big win: appraise_subject's NHTSA decode then fills year/driveline/engine reliably.
    structured = {}
    ym = re.search(r'"modelYear"\s*:\s*"?(\d{4})', html)
    if ym:
        structured["year"] = ym.group(1)
    km = _find_km(html)
    if km:
        structured["odometer_km"] = km
    vin = _find_vin(html)
    if vin:
        structured["vin"] = vin
    photos = _autotrader_photos(html) or _ld_images(prod) or _og_images(html)
    return {
        "title": prod.get("name") or _og(html, "title") or "",
        "description": prod.get("description") or "",
        "jsonld": ld,
        "price": price,
        "photos": photos,
        "seller_type": "dealer",  # AutoTrader is overwhelmingly dealer inventory
        "slug": urlparse(url).path,  # e.g. /offers/audi-sq5-technik-gasoline-white-...
        "structured": structured,
    }


# ── HTML helpers ────────────────────────────────────────────────────────────


def _find_vin(text: str) -> str | None:
    """First 17-char VIN-shaped token that contains a letter (excludes all-digit ids/timestamps)."""
    for m in re.findall(r"\b([A-HJ-NPR-Z0-9]{17})\b", text or "", re.I):
        if re.search(r"[A-HJ-NPR-Z]", m, re.I):
            return m.upper()
    return None


def _find_km(text: str) -> int | None:
    """First plausible '<n> km' reading in free text (1k–1M)."""
    for m in re.findall(r"([\d,]{3,})\s*km\b", text or "", re.I):
        try:
            n = int(re.sub(r"[^\d]", "", m))
        except ValueError:
            continue
        if 1000 <= n <= 1_000_000:
            return n
    return None


def _autotrader_photos(html: str) -> list:
    """De-duped AutoScout gallery image URLs (prefer the 1280x960 size)."""
    urls = re.findall(
        r"https://[^\"\\]*pictures\.autoscout24\.net/[^\"\\]+", html or ""
    )
    big = [u for u in urls if "1280x960" in u]
    seen, out = set(), []
    for u in big or urls:
        key = u.rsplit("/", 1)[0]  # listing-image id, ignoring the size suffix
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def _jsonld(html: str) -> list:
    out = []
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            obj = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        out.extend(obj if isinstance(obj, list) else [obj])
    return out


def _first_ld(blocks: list, types: tuple) -> dict | None:
    for o in blocks:
        if not isinstance(o, dict):
            continue
        t = o.get("@type")
        if t and any(x in str(t) for x in types):
            return o
    return None


def _ld_images(obj: dict) -> list:
    img = obj.get("image")
    if isinstance(img, str):
        return [img]
    if isinstance(img, list):
        return [
            i if isinstance(i, str) else (i.get("url") or i.get("contentUrl"))
            for i in img
            if i
        ]
    return []


def _og(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta property="og:{prop}" content="([^"]+)"', html)
    return m.group(1) if m else None


def _og_images(html: str) -> list:
    return [u for u in [_og(html, "image")] if u]


def _to_price(v):
    if v is None:
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(v)) or 0) or None
    except (ValueError, TypeError):
        return None


# ── spec extraction (Haiku) ───────────────────────────────────────────────────

_EXTRACT_MODEL = os.getenv("AD_EXTRACT_MODEL", "claude-haiku-4-5-20251001")

_EXTRACT_PROMPT = """Extract the vehicle's build spec from this used-car listing. Use ONLY what's stated/implied; use null when unknown — do NOT guess.

Return EXACTLY this JSON:
{"year": int|null, "make": "UPPERCASE"|null, "model": "UPPERCASE"|null, "trim": str|null,
 "driveline": "FWD|RWD|AWD|4WD"|null, "engine": str|null, "cab": "reg|ext|crew"|null,
 "odometer_km": int|null, "vin": str|null}

Notes: titles may be "Make Model Year" OR "Year Make Model". km may be in the description ("214,000 km", "139k"). cab only for pickups. Output ONLY the JSON."""


def _extract_spec(source: str, data: dict) -> dict:
    """One Haiku call to normalize the spec from the ad's text, seeded with any clean
    structured fields (which win over the model's read)."""
    bundle = "\n".join(
        filter(
            None,
            [
                f"SOURCE: {source}",
                f"TITLE: {data.get('title')}",
                f"URL SLUG: {data.get('slug')}",
                f"DESCRIPTION: {(data.get('description') or '')[:1500]}",
                "JSON-LD: " + json.dumps(data.get("jsonld") or [])[:1500],
            ],
        )
    )
    spec = {
        k: None
        for k in (
            "year",
            "make",
            "model",
            "trim",
            "driveline",
            "engine",
            "cab",
            "odometer_km",
            "vin",
        )
    }
    try:
        import anthropic

        if os.getenv("ANTHROPIC_API_KEY"):
            resp = anthropic.Anthropic().messages.create(
                model=_EXTRACT_MODEL,
                max_tokens=400,
                messages=[
                    {"role": "user", "content": _EXTRACT_PROMPT + "\n\n" + bundle}
                ],
            )
            text = resp.content[0].text
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                got = json.loads(m.group())
                for k in spec:
                    if got.get(k) not in (None, "", "null"):
                        spec[k] = got[k]
    except (
        Exception
    ) as e:  # noqa: BLE001 — extraction is best-effort; structured fields still apply
        print(f"[ad_ingest extract] {e}")

    # Clean structured fields (e.g. Kijiji JSON-LD) override the model's read.
    for k, v in (data.get("structured") or {}).items():
        if v not in (None, ""):
            spec[k] = v
    # Normalize types
    for k in ("year", "odometer_km"):
        try:
            spec[k] = (
                int(re.sub(r"[^\d]", "", str(spec[k])))
                if spec[k] not in (None, "")
                else None
            )
        except (ValueError, TypeError):
            spec[k] = None
    for k in ("make", "model"):
        if spec.get(k):
            spec[k] = str(spec[k]).strip().upper()
    return spec


if __name__ == "__main__":
    import sys

    print(json.dumps(ingest_ad(sys.argv[1]), indent=2, default=str))
