#!/usr/bin/env python3
"""
Auctionmatik — Main Evaluation CLI

Usage:
    python3 evaluate.py --contract 37316
    python3 evaluate.py --contract 37316 --no-prompt   # skip condition prompts (use defaults)
    python3 evaluate.py --contract 37316 --margin 2    # use tier 2 margin
"""

import sys
import argparse
import json
import requests

from db.connection import get_conn, get_cursor
from engine.valuator import valuate
from engine.max_bid import calculate as calc_max_bid

VEHICLE_TYPES = ["Car", "Truck", "Sport Utility", "Van"]
REGAL_INVENTORY_URL = "https://regalauctions.com/inventory.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://regalauctions.com/inventory.php",
}

SERVICE_RECORD_OPTIONS = {
    "1": "full_dealer",
    "2": "mixed",
    "3": "third_party",
    "4": "self",
    "5": "sparse",
    "6": "none",
}

ODO_INTEGRITY_OPTIONS = {
    "1": "clean",
    "2": "risk",
    "3": "high_risk",
}


# ── Fetch listing ─────────────────────────────────────────────────────────────

def fetch_listing_from_db(contract: str, conn) -> dict | None:
    cursor = get_cursor(conn)
    cursor.execute(
        "SELECT * FROM regal_listings WHERE contract = %s ORDER BY last_updated_at DESC LIMIT 1",
        (contract,)
    )
    row = cursor.fetchone()
    cursor.close()
    return dict(row) if row else None


def fetch_listing_from_api(contract: str) -> dict | None:
    """Search the Regal inventory API for a specific contract."""
    print(f"Searching Regal API for contract {contract}...")
    for vtype in VEHICLE_TYPES:
        page = 1
        while True:
            try:
                params = {
                    "a": "listingdata",
                    "listType": "detail",
                    "sort": "lot-asc",
                    "unitsPerPage": 100,
                    "page": page,
                    "search[vehicle_type][]": vtype,
                }
                resp = requests.get(REGAL_INVENTORY_URL, params=params, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  API error ({vtype} page {page}): {e}")
                break

            records = data.get("list", [])
            total_pages = data.get("totalPages", 1)

            for rec in records:
                if str(rec.get("contract")) == str(contract):
                    print(f"  Found: {rec.get('year')} {rec.get('make')} {rec.get('model')} (contract {contract})")
                    return rec

            if page >= total_pages:
                break
            page += 1

    return None


def parse_truck_style(style: str) -> dict:
    """Parse Regal's `style` string (e.g. 'CREW CAB 4WD 2.7L') into cab / bed /
    driveline / engine. Cab config + bed + engine are primary value drivers on trucks."""
    import re
    out = {}
    t = (style or "").upper()
    if not t:
        return out
    if any(k in t for k in ("SUPERCREW", "CREW CAB", "CREWCAB", "CREWMAX")):
        out["cab"] = "Crew Cab"
    elif any(k in t for k in ("SUPERCAB", "SUPER CAB", "QUAD CAB", "DOUBLE CAB", "KING CAB",
                              "ACCESS CAB", "EXTENDED", "EXT CAB", "EXTRA CAB")):
        out["cab"] = "Extended Cab"
    elif any(k in t for k in ("REGULAR CAB", "REG CAB", "SINGLE CAB", "STANDARD CAB", "STD CAB")):
        out["cab"] = "Regular Cab"
    if "SWB" in t or "SHORT" in t:
        out["bed"] = "Short Box"
    elif "LWB" in t or "LONG" in t:
        out["bed"] = "Long Box"
    else:
        m_bed = re.search(r"(\d(?:\.\d)?)\s*(?:FT|')", t)
        if m_bed:
            out["bed"] = f"{m_bed.group(1)} ft box"
    m_eng = re.search(r"(\d\.\d)\s*L", t)
    if m_eng:
        out["engine"] = f"{m_eng.group(1)}L"
    for dl in ("4WD", "AWD", "RWD", "FWD"):
        if dl in t:
            out["driveline"] = dl
            break
    else:
        if "4X4" in t:
            out["driveline"] = "4WD"
    return out


def parse_listing_to_vehicle(rec: dict) -> dict:
    """Convert raw Regal API/DB record to vehicle spec dict."""
    import re

    def parse_odo(raw):
        if not raw:
            return None
        digits = re.sub(r"[^\d]", "", str(raw).split()[0])
        return int(digits) if digits else None

    # The structured trim/style live in raw_json on a DB row (the parsed columns are
    # often empty) — fall back to it so truck trim/cab/bed aren't lost.
    rj = rec.get("raw_json")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except (ValueError, TypeError):
            rj = {}
    rj = rj or {}

    # Handle both raw API keys and DB column names
    odo_raw = rec.get("odometer") or rec.get("odometer_km")
    if isinstance(odo_raw, int):
        odometer_km = odo_raw
    else:
        odometer_km = parse_odo(odo_raw)

    style = rec.get("style") or rj.get("style")
    spec = parse_truck_style(style)

    trim = rec.get("trim") or rj.get("trim")
    if not trim:
        qa = rec.get("qamodel") or rj.get("qamodel")
        model = rec.get("model") or rj.get("model")
        if qa and (not model or qa.strip().upper() != str(model).strip().upper()):
            trim = qa

    return {
        "year":          int(rec.get("year") or 0) or None,
        "make":          rec.get("adjusted_make") or rec.get("make"),
        "model":         rec.get("model"),
        "trim":          trim,
        "cab":           spec.get("cab"),
        "bed":           spec.get("bed"),
        "style":         style,
        "driveline":     rec.get("driveline") or rj.get("driveline") or spec.get("driveline"),
        "vehicle_type":  rec.get("vehicle_type"),
        "fuel_type":     rec.get("fuel_type"),
        "odometer_km":   odometer_km,
        "color":         rec.get("color"),
        "engine":        rec.get("engine") or rj.get("engine") or spec.get("engine"),
        "transmission":  rec.get("transmission"),
        "seller_type":   rec.get("seller_type"),
        "declarations":  rec.get("declarations"),
        "options_text":  rec.get("options") or rec.get("options_text"),
        "condition_notes": rec.get("other") or rec.get("condition_notes"),
        "vin":           rec.get("vin"),
        "contract":      rec.get("contract"),
        "source_id":     rec.get("id", 0),
        "source_table":  "regal_listings",
    }


# ── Condition prompts ─────────────────────────────────────────────────────────

def prompt_condition(vehicle: dict, skip: bool = False) -> dict:
    """Interactively ask user for condition info not available from the listing."""
    updates = {}

    if skip:
        print("\n[Condition prompts skipped — using defaults (grade 3, no damage, clean history)]\n")
        updates.update({
            "exterior_grade": 3,
            "interior_grade": 3,
            "mechanical_grade": 3,
            "damage_items": [],
            "accident_claim_amount": 0,
            "vehicle_value_at_incident": 0,
            "rebuilt_title": False,
            "history_gap_post_accident": False,
            "service_records": "none",
            "odometer_integrity": "clean",
            "accident_type": "none",
        })
        return updates

    print("\n" + "═" * 60)
    print("CONDITION ASSESSMENT")
    print("(Press Enter to use default — grade 3 = average)")
    print("═" * 60)

    # Grades
    for area in ["Exterior", "Interior", "Mechanical"]:
        while True:
            raw = input(f"\n{area} grade [1=Poor, 2=Below avg, 3=Average, 4=Above avg, 5=Exceptional] (default 3): ").strip()
            if not raw:
                updates[f"{area.lower()}_grade"] = 3
                break
            try:
                g = int(raw)
                if 1 <= g <= 5:
                    updates[f"{area.lower()}_grade"] = g
                    break
            except ValueError:
                pass
            print("  Enter 1–5 or press Enter.")

    # Damage items
    print("\nDamage items (enter each damage, blank line when done):")
    print("  Format: description | location | repair_low | repair_high")
    print("  Example: bumper scuff | front bumper | 400 | 800")
    damage_items = []
    while True:
        raw = input("  Damage item (or Enter to skip): ").strip()
        if not raw:
            break
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 2:
            item = {
                "type": parts[0],
                "location": parts[1] if len(parts) > 1 else "unknown",
                "repair_cost_low": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                "repair_cost_high": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0,
            }
            damage_items.append(item)
            print(f"  Added: {item['type']} at {item['location']}")
        else:
            print("  Need at least: description | location")
    updates["damage_items"] = damage_items

    print("\n" + "─" * 60)
    print("ACCIDENT HISTORY")
    print("─" * 60)

    accident_type_raw = input("\nAccident history [0=None, 1=Minor, 2=Major, 3=Unknown] (default 0): ").strip() or "0"
    type_map = {"0": "none", "1": "minor", "2": "major", "3": "unknown"}
    updates["accident_type"] = type_map.get(accident_type_raw, "none")

    claim_raw = input("Accident claim amount in $ (e.g. 12000, or Enter for none): ").strip()
    updates["accident_claim_amount"] = int(claim_raw) if claim_raw.isdigit() else 0

    if updates["accident_claim_amount"] > 0:
        vv_raw = input("Estimated vehicle value at time of incident $ (or Enter to skip): ").strip()
        updates["vehicle_value_at_incident"] = int(vv_raw) if vv_raw.isdigit() else 0

        gap_raw = input("Service history gap following accident? [y/N]: ").strip().lower()
        updates["history_gap_post_accident"] = gap_raw == "y"
    else:
        updates["vehicle_value_at_incident"] = 0
        updates["history_gap_post_accident"] = False

    rebuilt_raw = input("\nRebuilt title? [y/N]: ").strip().lower()
    updates["rebuilt_title"] = rebuilt_raw == "y"

    print("\nService records:")
    print("  1 = Full dealer history  2 = Mixed  3 = Third party  4 = Self  5 = Sparse  6 = None")
    svc_raw = input("  Choice (default 6=None): ").strip() or "6"
    updates["service_records"] = SERVICE_RECORD_OPTIONS.get(svc_raw, "none")

    print("\nOdometer integrity:")
    print("  1 = Clean  2 = Risk signals  3 = High risk")
    odo_raw = input("  Choice (default 1=Clean): ").strip() or "1"
    updates["odometer_integrity"] = ODO_INTEGRITY_OPTIONS.get(odo_raw, "clean")

    print("\n" + "─" * 60)
    print("OPTIONS & MODIFICATIONS")
    print("─" * 60)
    print("Known options (comma-separated, e.g. sunroof,heated_front_seats,towing_package):")
    print("  Available: sunroof, panoramic_roof, navigation, premium_audio, heated_front_seats,")
    print("             heated_steering, remote_start, blind_spot, lane_assist, parking_sensors,")
    print("             360_camera, backup_camera, power_tailgate, cold_weather_package,")
    print("             leather_seats, towing_package, max_tow_package, spray_in_bedliner,")
    print("             tonneau_cover, running_boards, diesel_engine, third_row_seating, apple_carplay")
    opts_raw = input("  Options (or Enter to skip): ").strip()
    if opts_raw:
        updates["options_present"] = [o.strip() for o in opts_raw.split(",") if o.strip()]
    else:
        updates["options_present"] = []

    mods_raw = input("\nKnown modifications (comma-separated, or Enter to skip): ").strip()
    if mods_raw:
        updates["modifications"] = [m.strip() for m in mods_raw.split(",") if m.strip()]
    else:
        updates["modifications"] = []

    rust_raw = input("\nConfirmed rust-free (Alberta/dry climate only)? [y/N]: ").strip().lower()
    updates["rust_free"] = rust_raw == "y"

    return updates


# ── Report formatting ─────────────────────────────────────────────────────────

def fmt_dollars(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def print_report(vehicle: dict, valuation: dict, listing: dict):
    max_bids = calc_max_bid(valuation["retail_mid"])

    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  AUCTIONMATIK VALUATION REPORT{' ' * 38}║")
    print("╚" + "═" * 68 + "╝")

    print(f"\n  Vehicle:   {valuation['vehicle_summary']}")
    print(f"  Contract:  {vehicle.get('contract', 'N/A')}")
    if vehicle.get("vin"):
        print(f"  VIN:       {vehicle['vin']}")
    print(f"  Odometer:  {vehicle.get('odometer_km', 'N/A'):,} km" if vehicle.get("odometer_km") else "  Odometer:  N/A")
    print(f"  Color:     {vehicle.get('color', 'N/A')}")
    print(f"  Engine:    {vehicle.get('engine', 'N/A')}")
    if listing.get("condition_notes"):
        print(f"\n  Auctioneer notes: {listing['condition_notes']}")
    if vehicle.get("declarations"):
        print(f"  Declarations: {vehicle['declarations']}")

    print(f"\n{'─' * 70}")
    print(f"  RETAIL ESTIMATE:     {fmt_dollars(valuation['retail_low'])} – {fmt_dollars(valuation['retail_high'])}")
    print(f"  Retail mid:          {fmt_dollars(valuation['retail_mid'])}")
    print(f"  WHOLESALE ESTIMATE:  {fmt_dollars(valuation['wholesale_low'])} – {fmt_dollars(valuation['wholesale_high'])}")
    print(f"  Wholesale mid:       {fmt_dollars(valuation['wholesale_mid'])}")
    print(f"\n  Comp pool:  {valuation['comp_count']} comps | Confidence: {valuation['confidence'].upper()}"
          + (" | FALLBACK MATCH" if valuation.get("fallback_used") else ""))
    print(f"  Base median (pre-adjustment): {fmt_dollars(valuation['base_median'])}")

    print(f"\n{'─' * 70}")
    print("  MAX BID CALCULATOR  (Regal fee included, 5% GST)")
    print(f"{'─' * 70}")
    for i in range(1, 5):
        t = max_bids[f"tier{i}"]
        marker = " ◄ default" if t["label"] == max_bids["default_tier_label"] else ""
        print(f"  {t['label']:30s}  Max bid: {fmt_dollars(t['max_bid_cents']):>8}   "
              f"(fee ${t['buyer_fee']}, margin ${t['margin']:,}){marker}")

    print(f"\n{'─' * 70}")
    print("  FACTOR BREAKDOWN")
    print(f"{'─' * 70}")
    print(f"  {'Factor':<40} {'Delta':>8}  {'$ Impact':>10}  Reasoning")
    print(f"  {'─'*40} {'─'*8}  {'─'*10}  {'─'*20}")

    for f in valuation["factor_breakdown"]:
        if f.get("_is_sub"):
            continue  # Skip sub-factors in the summary table
        delta_str = f"{f['delta_pct']:+.1f}%" if f["delta_pct"] != 0 else "  0.0%"
        dollar_str = fmt_dollars(abs(f["dollar_impact"])) if f["dollar_impact"] != 0 else "—"
        sign = "-" if f["dollar_impact"] < 0 else ("+" if f["dollar_impact"] > 0 else " ")
        print(f"  {f['label']:<40} {delta_str:>8}  {sign}{dollar_str:>9}  {f['reasoning'][:60]}")

    # Sub-factors
    has_sub = any(f.get("_is_sub") for f in valuation["factor_breakdown"])
    if has_sub:
        print("\n  Detail breakdown:")
        for f in valuation["factor_breakdown"]:
            if not f.get("_is_sub"):
                continue
            delta_str = f"{f['delta_pct']:+.1f}%" if f["delta_pct"] != 0 else "  0.0%"
            print(f"  {f['label']:<42} {delta_str:>8}  {f['reasoning'][:55]}")

    if valuation["flags"]:
        print(f"\n{'─' * 70}")
        print("  ⚑  FLAGS")
        print(f"{'─' * 70}")
        for flag in valuation["flags"]:
            sev = flag["severity"].upper()
            print(f"  [{sev:^6}] {flag['code']}: {flag['message']}")

    print(f"\n{'─' * 70}")
    print("  TOP COMPS USED")
    print(f"{'─' * 70}")
    for c in valuation["comp_list"]:
        # wholesale comps have sale_price+sold_date; retail comps have asking_price+posted_at
        price = c.get("sale_price") or c.get("asking_price") or 0
        date_label = c.get("sold_date") or c.get("posted_at") or "?"
        score = c.get("_combined_weight") or c.get("_similarity") or 0.0
        source_tag = f" [{c['source']}]" if c.get("source") not in (None, "regal_market_report") else ""
        print(f"  {c.get('year')} {c.get('make')} {c.get('model')} {(c.get('trim') or ''):15} | "
              f"{(c.get('odometer_km') or 0):>7,} km | "
              f"{fmt_dollars(price):>8} | "
              f"sold {date_label}{source_tag} | "
              f"score {score:.2f}")

    print(f"\n{'═' * 70}\n")


# ── Vision integration ────────────────────────────────────────────────────────

def _get_subject_vision(conn, contract: str) -> dict:
    """Fetch the subject's stored vision_assessment (or {} if none)."""
    cursor = get_cursor(conn)
    cursor.execute(
        "SELECT vision_assessment FROM regal_listings WHERE contract = %s "
        "ORDER BY last_updated_at DESC LIMIT 1",
        (contract,),
    )
    row = cursor.fetchone()
    cursor.close()
    return (row.get("vision_assessment") if row else None) or {}


def _apply_vision_spec(vehicle: dict, va: dict):
    """Overlay a vision_assessment onto the vehicle spec."""
    from engine.vision_factors import vision_to_spec
    if not va:
        print("  [--vision] No vision_assessment stored for this contract yet — "
              "run photo enrichment + `python3 -m engine.vision` first. Using defaults.")
        return
    spec = vision_to_spec(va, vehicle)
    vehicle.update(spec)
    summary = ", ".join(f"{k}={v}" for k, v in spec.items() if k != "damage_items")
    print(f"  [--vision] Applied from photos: {summary or '(no priced clues)'}")
    if spec.get("damage_items"):
        print(f"             + {len(spec['damage_items'])} damage item(s) costed from photos")


# ── Recommendation Engine integration ─────────────────────────────────────────

def _advisor_anchor(conn, vehicle: dict, valuation: dict):
    """As-is retail anchor: per-comp scrutiny of retail listings if we have them,
    else fall back to the valuator's anchor. Returns (anchor_cents, clean_cents, source)."""
    from engine.comp_scrutiny import scrutinize
    yr = vehicle.get("year")
    make = (vehicle.get("make") or "").upper()
    model = (vehicle.get("model") or "").upper()
    comps = []
    if yr and make and model:
        cur = get_cursor(conn)
        cur.execute("""SELECT external_id, year, make, model, trim, odometer_km, asking_price, posted_at,
                              title, description, listing_url, source, main_photo_url
                       FROM retail_listings
                       WHERE UPPER(make) = %s AND UPPER(COALESCE(model, '')) LIKE %s
                         AND year BETWEEN %s AND %s AND asking_price >= 300000 AND is_sold = FALSE
                         AND external_id NOT IN (SELECT external_id FROM comp_feedback WHERE status = 'bad')
                       ORDER BY (odometer_km IS NOT NULL) DESC, collected_at DESC LIMIT 25""",
                    (make, model.split()[0] + "%", yr - 2, yr + 2))
        comps = [dict(r) for r in cur.fetchall()]
        cur.close()
    if len(comps) >= 3:
        res = scrutinize(vehicle, comps)
        if res.get("anchor"):
            return (res["anchor"], res["anchor"],
                    f"retail comp-scrutiny ({len(res['clean'])} comps, {res['confidence']})", res)
    # Fallback to the RAW comp anchor (base_median), never retail_mid — retail_mid carries the
    # factor adjustments (incl. the broken-on-cheap/wreck condition math) and can be negative.
    base = valuation.get("base_median") or valuation.get("retail_mid")
    return base, base, "wholesale-derived (no retail comps — scrape for a better anchor)", None


def _run_advisor(conn, vehicle: dict, va: dict, valuation: dict,
                 ai: bool = False, deep: bool = False, auto: bool = False):
    from engine.declarations import analyze_declarations
    from engine.advisor import advise, render

    decl = analyze_declarations(vehicle.get("declarations") or "", vehicle.get("condition_notes") or "")
    anchor, clean, source, scrutiny = _advisor_anchor(conn, vehicle, valuation)

    cur = get_cursor(conn)
    cur.execute("SELECT carfax_report FROM regal_listings WHERE contract = %s "
                "ORDER BY last_updated_at DESC LIMIT 1", (vehicle.get("contract"),))
    row = cur.fetchone()
    cur.close()
    carfax = (row.get("carfax_report") if row else None) or None

    print(f"\n{'═' * 70}")
    print(f"  RECOMMENDATION (Advisor)   [anchor: {source}]")
    print(f"{'═' * 70}")
    ch = advise(vehicle, anchor_cents=anchor, clean_value_cents=clean, decl=decl, vision=va,
                carfax=carfax, profile_key="charles")
    print(render(ch))
    me = advise(vehicle, anchor_cents=anchor, clean_value_cents=clean, decl=decl, vision=va,
                carfax=carfax, profile_key="mechanic")
    print(f"\n👤 CROSS-PROFILE — {me['profile']}: {me['verdict']}  max bid ${me['max_bid_cents'] / 100:,.0f}")

    if ai:
        from engine.advisor import PROFILES
        from engine.repair_estimate import estimate_repair
        from engine.appraiser import appraise, render as ai_render, REASONING_MODEL

        rc = PROFILES["charles"]["repair"]
        comps_rc = (va or {}).get("repair_components") or []
        repair_est = estimate_repair(comps_rc, buffer=PROFILES["charles"]["repair_buffer"],
                                     small_factor=rc["small_factor"], large_factor=rc["large_factor"])
        # Pre-compute all sourcings + pull stored Carfax so the deep pass rarely needs a tool round-trip.
        repair_alternatives = None
        if comps_rc:
            repair_alternatives = {
                "oem_shop": estimate_repair(comps_rc, small_factor=1.0, large_factor=1.0),
                "middle": estimate_repair(comps_rc, small_factor=0.65, large_factor=1.0),
                "used_diy": estimate_repair(comps_rc, small_factor=0.5, large_factor=0.55),
            }
        prof = {**PROFILES["charles"], "label": "Charles (flipper)"}

        def _call(m):
            return appraise(
                vehicle,
                comp_narrative=(scrutiny or {}).get("narrative") or [],
                comp_anchor_cents=anchor,
                comp_confidence=(scrutiny or {}).get("confidence", "low"),
                declarations=decl, vision=va, repair_est=repair_est,
                deterministic=ch, profile=prof, mode=m,
                carfax=carfax, repair_alternatives=repair_alternatives,
                tool_ctx=({"conn": conn, "subject": vehicle, "vision": va,
                           "profile": PROFILES["charles"]} if m == "deep" else None),
            )

        try:
            if auto:
                # Funnel: fast triage everything; auto-deep-dive only buy candidates with thin evidence.
                print(f"\n{'═' * 70}\n  AI APPRAISER (triage — {REASONING_MODEL})\n{'═' * 70}")
                t = _call("triage")
                print(ai_render(t))
                if t.get("needs_deep_dive") and t.get("verdict") in ("BID", "BID_TO_FIX"):
                    print(f"\n{'═' * 70}\n  AUTO-ESCALATE → deep agentic pass (buy candidate, thin evidence)\n{'═' * 70}")
                    print(ai_render(_call("deep")))
                else:
                    print("\n(no deep dive — triage was decisive)")
            else:
                m = "deep" if deep else "triage"
                print(f"\n{'═' * 70}\n  AI APPRAISER ({m} — {REASONING_MODEL})\n{'═' * 70}")
                print(ai_render(_call(m)))
        except Exception as e:
            print(f"  AI appraiser unavailable: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auctionmatik — evaluate a Regal listing")
    parser.add_argument("--contract", required=True, help="Regal contract number")
    parser.add_argument("--no-prompt", action="store_true", help="Skip condition prompts, use defaults")
    parser.add_argument("--margin", type=int, choices=[1, 2, 3, 4], default=None,
                        help="Preferred margin tier (1–4)")
    parser.add_argument("--log", action="store_true", help="Log valuation to DB")
    parser.add_argument("--vision", action="store_true",
                        help="Use stored vision_assessment for condition/mods (skips prompts)")
    parser.add_argument("--advise", action="store_true",
                        help="Print the Advisor recommendation (verdict, max bid, recon, sale plan)")
    parser.add_argument("--ai", action="store_true",
                        help="Run the AI Appraiser — fast triage pass (Sonnet) alongside the rules engine")
    parser.add_argument("--deep", action="store_true",
                        help="Run the AI Appraiser deep pass (full narration + escalation tools)")
    parser.add_argument("--auto", action="store_true",
                        help="Triage, then auto-escalate to a deep pass only for thin-evidence buy candidates")
    args = parser.parse_args()

    conn = get_conn()

    # Apply saved settings (edited profiles / margins / fees / GST / toggles) so the CLI
    # produces the same numbers as the dashboard — important for overnight batch jobs.
    try:
        from engine import settings as _settings
        _settings.apply_from_db(conn)
    except Exception as _e:  # noqa: BLE001 — fall back to hardcoded defaults
        print(f"[settings] not applied ({_e}); using defaults")

    # 1. Fetch listing
    listing_raw = fetch_listing_from_db(args.contract, conn)
    if listing_raw:
        print(f"Found in local DB: contract {args.contract}")
    else:
        listing_raw = fetch_listing_from_api(args.contract)
        if not listing_raw:
            print(f"\nError: No listing found for contract {args.contract}")
            sys.exit(1)

    # 2. Parse into vehicle spec
    vehicle = parse_listing_to_vehicle(listing_raw)

    print(f"\n{'═' * 60}")
    print(f"Evaluating: {vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}")
    print(f"  Driveline: {vehicle.get('driveline', 'N/A')}")
    print(f"  Odometer:  {vehicle.get('odometer_km', 'N/A'):,} km" if vehicle.get("odometer_km") else "  Odometer: N/A")
    print(f"  Seller:    {vehicle.get('seller_type', 'N/A')} | Declarations: {vehicle.get('declarations', 'N/A')}")
    if vehicle.get("condition_notes"):
        print(f"  Notes:     {vehicle['condition_notes']}")
    print(f"{'═' * 60}")

    # 3. Condition inputs — from photos (--vision) or prompts/defaults
    condition_updates = prompt_condition(vehicle, skip=args.no_prompt or args.vision)
    vehicle.update(condition_updates)
    va = {}
    if args.vision:
        va = _get_subject_vision(conn, args.contract)
        _apply_vision_spec(vehicle, va)

    # A Carfax report exists for any VIN'd Regal unit — don't assume "no service history".
    # Treat as unknown (0%) until the report is actually read (see local Carfax agent).
    if vehicle.get("vin") and vehicle.get("service_records") in (None, "none"):
        vehicle["service_records"] = "unknown"

    # 4. Run valuator
    print("\nRunning valuation engine...")
    valuation = valuate(vehicle, conn=conn, log_to_db=args.log)

    if "error" in valuation:
        print(f"\nValuation error: {valuation['error']}")
        print(f"Comp count: {valuation.get('comp_count', 0)}")
        sys.exit(1)

    # 5. Print report
    print_report(vehicle, valuation, listing_raw if isinstance(listing_raw, dict) else {})

    # 6. Recommendation (Advisor + optional AI Appraiser) — the actionable output
    if args.vision or args.advise or args.ai or args.deep or args.auto:
        if not va:
            va = _get_subject_vision(conn, args.contract)
        _run_advisor(conn, vehicle, va, valuation,
                     ai=args.ai or args.deep or args.auto, deep=args.deep, auto=args.auto)

    conn.close()


if __name__ == "__main__":
    main()
