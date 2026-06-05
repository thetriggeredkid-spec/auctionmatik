"""
Vision Assessment — Claude AI photo analysis for Regal listings
Fetches photo URLs from the DB, sends them to Claude's vision API,
and returns a structured condition assessment.

What the vision model does (complements Regal's heat map):
  - Identifies DAMAGE TYPE per panel: dent, scratch, rust, paint fade, crack, missing
  - Assesses INTERIOR condition: cleanliness, seat condition, headliner, dash cracks
  - Flags MECHANICAL concerns visible in photos: fluid leaks, exhaust soot, tire condition
  - Catches issues Regal's written report may have missed

The heat map tells us WHERE and rough severity — vision tells us WHAT and confirms severity.

Usage:
    python3 -m engine.vision --id 429954
    python3 -m engine.vision --id 429954 --table regal_listings

Setup:
    Set ANTHROPIC_API_KEY in .env
    pip install anthropic
"""

import os
import sys
import json
import base64
import argparse
import requests

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Two-tier strategy: Haiku triages every comp cheaply; Sonnet re-checks the vehicle
# you're actually bidding on (pass finalist=True). Both env-overridable.
VISION_MODEL          = os.getenv("VISION_MODEL", "claude-haiku-4-5-20251001")   # triage
VISION_MODEL_FINALIST = os.getenv("VISION_MODEL_FINALIST", "claude-sonnet-4-6")  # finalist

# Send all photos a listing has, up to this safety ceiling (Anthropic allows 100/request;
# 30 covers full FB galleries while bounding latency/cost). Override via VISION_MAX_PHOTOS.
MAX_PHOTOS_FOR_VISION = int(os.getenv("VISION_MAX_PHOTOS", "30"))

# Trimmed, high-signal clue set — each field maps to a pricing factor:
#   exterior/interior_grade -> condition | damage_details -> damage deduction
#   rust_severity -> condition (Alberta) | flood_or_frame_concern -> history/near-total-loss
#   aftermarket_mods -> options/mods
VISION_PROMPT = """You are evaluating a used vehicle (Alberta market) for auction/resale purchase. Analyze these photos and extract a small set of high-signal visual clues.

Be conservative. If you can't clearly see something, use null/"unknown" — do NOT guess or invent.

Respond in this exact JSON format:
{
  "exterior_grade": 1-5 (5=excellent/like-new, 4=above avg, 3=average used, 2=below avg, 1=poor/heavily damaged) or null,
  "interior_grade": 1-5 (same scale: 5=excellent, 3=average, 1=poor) or null,
  "rust_severity": "none|surface|moderate|severe|unknown",
  "hail_severity": "none|light|moderate|severe|unknown",
  "damage_details": [
    {"panel": "panel name", "damage_type": "dent|scratch|rust|crack|paint|missing|other", "severity": "minor|moderate|severe"}
  ],
  "aftermarket_mods": [
    {"type": "e.g. 4in lift kit, aftermarket wheels, light bar, winch, exhaust", "quality": "professional|amateur|unknown"}
  ],
  "flood_or_frame_concern": true/false/null (water lines, mud in interior, bent frame, weld repairs),
  "dash_warning_lights": ["only lights clearly ILLUMINATED in a dashboard/instrument-cluster photo, e.g. check engine, airbag/SRS, ABS, brake, oil, battery, TPMS, traction"],
  "repair_components": [
    {"component": "specific part needing work, e.g. front bumper, left headlight, left front fender, hood, grille, radiator, condenser, cooling fan, left front suspension, tie rod, control arm, alloy wheel, windshield, underbody cover", "action": "replace|repair|refinish", "severity": "minor|moderate|severe"}
  ],
  "confidence": "high|medium|low"
}

repair_components: ONLY for damaged vehicles — list EVERY part a buyer would have to replace or repair to make it sellable, including structural/mechanical parts visible behind the damage (suspension, rad, fans, hoses). For a clean car return []. Be thorough: a single impact often damages many adjacent parts.
DASH WARNING LIGHTS: if any photo shows the instrument cluster with the ignition on, report EVERY illuminated warning light (check engine, airbag/SRS, ABS, brake, oil pressure, battery/charging, TPMS, traction/stability). These signal mechanical/electrical faults a buyer must diagnose. If there's no cluster photo or none are lit, return [].
REPLACEMENT / UNPAINTED PANELS: a panel that is a DIFFERENT COLOUR from the body, in grey/black primer, or clearly a brand-new unpainted replacement is NOT damage — do NOT call it cracked or dented. Record it as a refinish job: a damage_details entry with damage_type "paint", and a repair_components entry with action "refinish" (it needs colour-matched paint + blend). This is a fix-and-flip cost, not collision damage.
HAIL: inspect the horizontal panels (hood, roof, trunk/tailgate) closely for dimpling — many small round
dents, often visible only in light reflections. Hail ranges from near-invisible to a real presentation hit;
grade it in hail_severity. It's cosmetic (paintless dent repair), not structural.

Only include list entries you can clearly see. Empty lists are fine."""


def _fetch_image_b64(url: str, timeout: int = 20) -> tuple[str, str] | None:
    """Download an image and return (media_type, base64_data), or None on failure."""
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
        if ctype not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            ctype = "image/jpeg"
        return ctype, base64.standard_b64encode(r.content).decode("ascii")
    except Exception:
        return None


def assess_vehicle(regal_id: str, photo_urls: list[str], vehicle_summary: str = "",
                   model: str = None) -> dict:
    """
    Send vehicle photos to Claude vision API and return structured assessment.

    Args:
        regal_id: listing ID (for logging)
        photo_urls: list of photo URLs
        vehicle_summary: optional "2024 Kia Sorento AWD" for context
        model: vision model to use (defaults to the fast triage model)

    Returns:
        dict with exterior_grade, interior_grade, rust_severity, damage_details, etc.
    """
    model = model or VISION_MODEL
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed — run: pip install anthropic")

    if not photo_urls:
        return {"error": "No photos available", "confidence": "low"}

    # Use first N photos — typically walk-around exterior shots come first
    selected_urls = photo_urls[:MAX_PHOTOS_FOR_VISION]

    # Download images and send as base64. (Anthropic fetches URL-sourced images
    # server-side and honors robots.txt — Facebook's CDN blocks that — so we fetch.)
    content = []
    if vehicle_summary:
        content.append({"type": "text", "text": f"Vehicle: {vehicle_summary}\n\nAnalyze these photos:"})

    fetched = 0
    for url in selected_urls:
        img = _fetch_image_b64(url)
        if img:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": img[0], "data": img[1]}})
            fetched += 1

    if fetched == 0:
        return {"error": "Could not download any photos", "confidence": "low"}

    content.append({"type": "text", "text": VISION_PROMPT})

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        messages=[{"role": "user", "content": content}]
    )

    raw_text = response.content[0].text

    # Parse JSON response
    try:
        # Extract JSON from response (may have markdown code blocks)
        import re
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(raw_text)
        result["_photos_analyzed"] = fetched
        result["_total_photos"] = len(photo_urls)
        return result
    except json.JSONDecodeError:
        return {
            "error": "Failed to parse vision response",
            "raw_response": raw_text[:500],
            "confidence": "low"
        }


def assess_and_store(regal_id: str, table: str = "regal_sold") -> dict:
    """
    Fetch photo URLs from DB, run vision assessment, store result.
    Requires enrichment to have been run first (photo_urls populated).
    """
    from db.connection import get_conn, get_cursor

    conn = get_conn()
    cursor = get_cursor(conn)

    cursor.execute(f"""
        SELECT regal_id, year, make, model, trim, photo_urls
        FROM {table}
        WHERE regal_id = %s
    """, (regal_id,))
    row = cursor.fetchone()

    if not row:
        raise ValueError(f"Listing {regal_id} not found in {table}")

    photo_urls = row.get("photo_urls") or []
    if not photo_urls:
        print(f"  No photos for {regal_id} — run regal_enrich.py first")
        cursor.close()
        conn.close()
        return {}

    vehicle_summary = " ".join(filter(None, [
        str(row.get("year") or ""),
        row.get("make") or "",
        row.get("model") or "",
        row.get("trim") or "",
    ])).strip()

    print(f"  Analyzing {len(photo_urls)} photos for {vehicle_summary}...")
    result = assess_vehicle(regal_id, photo_urls, vehicle_summary)

    # Store in DB
    cursor.execute(f"""
        UPDATE {table}
        SET vision_assessment = %s
        WHERE regal_id = %s
    """, (json.dumps(result), regal_id))
    conn.commit()
    cursor.close()
    conn.close()

    return result


def assess_retail_listing(external_id: str, finalist: bool = False) -> dict:
    """
    Run vision assessment on a unified retail_listings row (Facebook/Kijiji)
    using the photo_urls captured by the collector, and store it back.

    finalist=True uses the higher-accuracy Sonnet model (for the vehicle you're
    actually bidding on); default uses the fast Haiku triage model.
    """
    from db.connection import get_conn, get_cursor

    model = VISION_MODEL_FINALIST if finalist else VISION_MODEL

    conn = get_conn()
    cursor = get_cursor(conn)
    cursor.execute("""
        SELECT external_id, source, year, make, model, trim, photo_urls
        FROM retail_listings
        WHERE external_id = %s
    """, (external_id,))
    row = cursor.fetchone()

    if not row:
        cursor.close(); conn.close()
        raise ValueError(f"retail_listing {external_id} not found")

    photo_urls = row.get("photo_urls") or []
    if not photo_urls:
        print(f"  No photos for {external_id} — nothing to assess")
        cursor.close(); conn.close()
        return {}

    vehicle_summary = " ".join(filter(None, [
        str(row.get("year") or ""), row.get("make") or "",
        row.get("model") or "", row.get("trim") or "",
    ])).strip()

    print(f"  Analyzing {len(photo_urls)} photos for {vehicle_summary} "
          f"[{row.get('source')}] with {model}...")
    result = assess_vehicle(external_id, photo_urls, vehicle_summary, model=model)
    result["_model"] = model

    cursor.execute(
        "UPDATE retail_listings SET vision_assessment = %s WHERE external_id = %s",
        (json.dumps(result), external_id),
    )
    conn.commit()
    cursor.close(); conn.close()
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Claude vision assessment on vehicle photos")
    parser.add_argument("--id", required=True, type=str, help="Listing ID (regal_id, or retail external_id)")
    parser.add_argument("--table", choices=["regal_sold", "regal_listings", "retail_listings"],
                        default="regal_sold")
    parser.add_argument("--finalist", action="store_true",
                        help="Use the higher-accuracy Sonnet model (retail_listings only)")
    args = parser.parse_args()

    if args.table == "retail_listings":
        result = assess_retail_listing(args.id, finalist=args.finalist)
    else:
        result = assess_and_store(args.id, table=args.table)

    print(f"\nVision Assessment for {args.id}  (model: {result.get('_model', VISION_MODEL)}):")
    print(f"  Exterior grade:  {result.get('exterior_grade')}/5")
    print(f"  Interior grade:  {result.get('interior_grade')}/5")
    print(f"  Rust severity:   {result.get('rust_severity')}")
    print(f"  Flood/frame:     {result.get('flood_or_frame_concern')}")
    print(f"  Confidence:      {result.get('confidence')}")
    print(f"  Photos analyzed: {result.get('_photos_analyzed')}/{result.get('_total_photos')}")

    if result.get("damage_details"):
        print(f"\nDamage ({len(result['damage_details'])} items):")
        for d in result["damage_details"]:
            print(f"  [{d.get('severity','?'):8s}] {d.get('panel','?'):22s} {d.get('damage_type','?')}")

    if result.get("aftermarket_mods"):
        print("\nAftermarket mods:")
        for m in result["aftermarket_mods"]:
            print(f"  + {m.get('type','?')} ({m.get('quality','?')})")
