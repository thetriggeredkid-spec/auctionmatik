"""
Dashboard mapper — runs the Auctionmatik engine for a contract and shapes the
result into the design's vehicle object (the shape `dashboard/static/data.js`
documents and the hi-fi React components bind to).

One function does the work: `evaluate(conn, contract, profile, ai_mode)`.
  - ai_mode=None     → deterministic only (fast/free) — used for The Lane.
  - ai_mode="triage" → + the Sonnet triage pass (cheap).
  - ai_mode="deep"   → + the deep agentic appraisal (full reasoning, slow).

Identity, comps, vision, repair, recon, declarations and the rules-engine
sanity band always come from the deterministic engine; the AI pass (when run)
overrides verdict/value/max-bid/confidence and adds the narrated reasoning,
key adjustments, conditional bid and run metadata.
"""

import re
import json
import time
from datetime import date

from db.connection import get_cursor
from engine.valuator import valuate
from engine.comps import get_comp_pool
from engine.declarations import analyze_declarations
from engine.advisor import (
    advise,
    _margin,
    purchase_context,
    AUCTION_CTX,
    PROFILES as ADV_PROFILES,
)
from engine.repair_estimate import estimate_repair

# reuse the CLI's listing/anchor/vision plumbing rather than duplicating it
from evaluate import (
    fetch_listing_from_db,
    parse_listing_to_vehicle,
    prompt_condition,
    _get_subject_vision,
    _apply_vision_spec,
    _advisor_anchor,
    apply_vin_decode,
)

REGAL_DETAIL_URL = "https://regalauctions.com/inventory.php?a=details&contract="

# Sonnet 4.6 pricing ($/1M tokens) for the rough cost estimate in the footer.
_PRICE_IN, _PRICE_CACHE, _PRICE_OUT = 3.0, 0.30, 15.0

_HI_CODES = ("FD", "SALV", "NR", "RS")
_MED_CODES = ("MP", "OOP", "HD", "FR", "TMU", "OOC")

# Regal's two recurring sale brands, keyed by the auction date's weekday.
# Tuesday = Timed (online) Auction · Saturday = Super Sale. Any other day is a
# different sale type we deliberately exclude from the lane.
_SALE_LABELS = {1: "Tuesday Timed Auction", 5: "Saturday Super Sale"}
_DAY_ABBR = {1: "Tue", 5: "Sat"}

# Deterministic results cache (contract -> design vehicle) so re-loading a sale or
# re-opening a card is instant. Only the free/fast deterministic pass is cached.
_DET_CACHE: dict = {}


# ── verdict / severity helpers ────────────────────────────────────────────────


def _norm_verdict(s: str) -> str:
    s = (s or "").upper()
    if "FIX" in s:
        return "BID_TO_FIX"
    if s.startswith("BID"):
        return "BID"
    return "PASS"


def _carfax_url(raw: dict) -> str | None:
    """The Regal Carfax link (redirects to the real Carfax Canada VHR). Prefer the
    enriched column, fall back to raw_json, else construct it from regal_id + VIN."""
    if raw.get("carfax_url"):
        return raw["carfax_url"]
    rj = raw.get("raw_json")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except (ValueError, TypeError):
            rj = {}
    rj = rj or {}
    if rj.get("carfax_url"):
        return rj["carfax_url"]
    rid = raw.get("regal_id") or rj.get("id")
    vin = raw.get("vin") or rj.get("vin")
    if rid and vin:
        return f"https://regalauctions.com/carfax.php?id={rid}&vin={vin}&loc=list"
    return None


def _photo_fields(row: dict) -> dict:
    """Cover thumbnail (for the lane) + a larger gallery (for the detail).
    Regal CloudFront serves the same shot at multiple sizes; we upscale the
    160x120 cover to 800x600 for the detail when no enriched gallery exists."""
    main = row.get("main_photo_url")
    arr = list(row.get("photo_urls") or [])
    big = lambda u: (u or "").replace("/160x120/", "/800x600w/")
    gallery = arr if arr else ([big(main)] if main else [])
    return {"photo": main or (gallery[0] if gallery else None), "photos": gallery}


def _lot_of(raw: dict) -> tuple[str, int]:
    """Regal lot, e.g. '601DT' → ('601DT', 601). Lots sort by their numeric prefix
    (the auction running order); lot-less rows sort last."""
    rj = raw.get("raw_json")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except Exception:  # noqa: BLE001
            rj = {}
    lot = str((rj or {}).get("lot") or "").strip()
    # Regal placeholders ("NOTSET-43", "RXXX") aren't real lots — hide + sort last.
    if not lot or "NOTSET" in lot.upper() or re.fullmatch(r"[Rr][Xx]+", lot):
        return "", 10**9
    m = re.search(r"(\d+)", lot)  # numeric part anywhere ("300R"→300, "R019"→19)
    return lot, (int(m.group(1)) if m else 10**9)


def _code_sev(code: str, decl: dict) -> str:
    if code.startswith("CH"):
        return "hi" if (decl.get("claims_total_low") or 0) >= 10000 else "med"
    if any(code.startswith(k) for k in _HI_CODES):
        return "hi"
    if any(code.startswith(k) for k in _MED_CODES):
        return "med"
    return "lo"


# ── sub-mappers ───────────────────────────────────────────────────────────────


def _decl_to_design(decl: dict, raw_declarations: str) -> dict:
    chips, codes = [], []
    for c in decl.get("codes", []):
        code = c["code"]
        short = "CH" if code.startswith("CH") else code
        chips.append({"code": short, "label": c["label"], "sev": _code_sev(code, decl)})
        codes.append({"code": code, "label": c["label"], "meaning": c["meaning"]})
    flags = [{"sev": f["severity"], "msg": f["message"]} for f in decl.get("flags", [])]
    return {
        "raw": raw_declarations or "",
        "chips": chips,
        "codes": codes,
        "claimsLow": decl.get("claims_total_low") or 0,
        "flags": flags,
    }


def _topflags(decl: dict) -> list:
    return [c["label"] for c in decl.get("codes", [])][:4]


def _fee_gst(max_bid_dollars: int) -> tuple[int, int]:
    """Regal buyer fee + 5% GST for a given max bid (the same basis the engine uses).
    Read live from engine.max_bid so edited Settings are honoured."""
    from engine.max_bid import get_buyer_fee, GST_RATE

    fee = get_buyer_fee(max_bid_dollars or 0)
    gst = round(((max_bid_dollars or 0) + fee) * GST_RATE)
    return int(fee), int(gst)


# Higher trims under/over-fit badly against generic comps — worth a deep run.
_PREMIUM_TRIMS = (
    "lariat",
    "limited",
    "platinum",
    "king ranch",
    "high country",
    "denali",
    "laramie",
    "summit",
    "calligraphy",
    "titanium",
    "rubicon",
    "overland",
    "raptor",
    "tremor",
    "redline",
    "ltz",
    "avalanche",
)


def _deep_recommended(
    vehicle: dict, scrutiny: dict, comps: dict
) -> tuple[bool, str | None]:
    """Cheap heuristic for the lane: flag rows where triage is likely under/over-fit and a
    deep run would pay off — thin/absent comps, or a premium trim the comps may not match.
    """
    reasons = []
    used = (comps or {}).get("used") or []
    conf = (scrutiny or {}).get("confidence")
    if not comps or comps.get("empty") or not used:
        reasons.append("no retail comps — anchor is wholesale-derived")
    elif conf in ("low", "medium"):
        reasons.append(f"{conf} comp confidence")
    trim = (vehicle.get("trim") or "").lower()
    if trim and any(t in trim for t in _PREMIUM_TRIMS):
        same = sum(
            1
            for c in used
            if (c.get("trim") or "").lower() and (c.get("trim") or "").lower() in trim
        )
        if same < 2:
            reasons.append("premium trim — comps may not match")
    return bool(reasons), ("; ".join(reasons[:2]) or None)


def _append_dash_lights(notes, va: dict):
    """Fold vision-detected dashboard warning lights into the condition text so the
    declarations parser (check_engine/airbag) and the AI both see them — a second
    source beyond the written remarks."""
    lights = (va or {}).get("dash_warning_lights") or []
    if not lights:
        return notes
    # phrase each as "<light> light on" so the declarations patterns latch reliably
    clauses = "; ".join(f"{x} light on" for x in lights)
    return ((notes or "") + " Dash warning: " + clauses + ".").strip()


def _vision_to_design(va: dict) -> dict | None:
    if not va or va.get("error"):
        return None
    damage = []
    for d in va.get("damage_details") or []:
        damage.append(
            {
                "panel": d.get("panel", "unknown"),
                "type": d.get("damage_type") or d.get("type") or "damage",
                "sev": (d.get("severity") or "moderate").lower(),
            }
        )
    mods = [
        {"type": m.get("type", "mod"), "quality": m.get("quality") or "unknown"}
        for m in va.get("aftermarket_mods") or []
    ]
    out = {
        "extGrade": int(va.get("exterior_grade") or 3),
        "intGrade": int(va.get("interior_grade") or 3),
        "rust": (va.get("rust_severity") or "unknown"),
        "hail": (va.get("hail_severity") or "none"),
        "flood": bool(va.get("flood_or_frame_concern")),
        "dashLights": va.get("dash_warning_lights") or [],
        "damage": damage,
        "mods": mods,
        "conf": va.get("confidence") or "medium",
        "analyzed": va.get("_photos_analyzed")
        or va.get("photos_analyzed")
        or va.get("analyzed")
        or 0,
        "total": va.get("_total_photos")
        or va.get("photo_count")
        or va.get("total")
        or 0,
        "model": va.get("_model") or va.get("model") or "claude-haiku-4-5",
    }
    rc = [
        c.get("component")
        for c in (va.get("repair_components") or [])
        if c.get("component")
    ]
    if rc:
        out["repairComponents"] = rc
    return out


def _comps_to_design(scrutiny: dict, anchor_cents: int, source: str) -> dict:
    """Always returns a comps object so the tab is always present; `empty` is set
    when there were no retail (Facebook/Kijiji) comps to scrutinize."""
    if not scrutiny:
        return {
            "anchor": round((anchor_cents or 0) / 100) or None,
            "conf": "low",
            "source": source,
            "used": [],
            "excluded": [],
            "empty": True,
        }
    used = []
    for c in scrutiny.get("clean", []):
        used.append(
            {
                "y": c.get("year"),
                "mk": c.get("make"),
                "md": c.get("model"),
                "km": c.get("odometer_km") or 0,
                "ask": round((c.get("asking_price") or 0) / 100),
                "dom": c.get("_age_days") or 0,
                "disc": round((c.get("_dom_discount") or 0) * 100),
                "est": round((c.get("_est_sale") or 0) / 100),
                "kmAdj": round((c.get("_km_adj") or c.get("_est_sale") or 0) / 100),
                "cond": c.get("_condition") or "unknown",
                "title": c.get("_title") or "clean",
                "score": round(c.get("_score") or 0, 2),
                "trim": (c.get("_trim") or "").upper() or None,
                "url": c.get("listing_url"),
                "src": _src_label(c.get("source")),
                "realized": bool(c.get("_realized")),
                "id": c.get("external_id"),
                "photo": c.get("main_photo_url"),
            }
        )
    excluded = [
        {
            "y": e.get("year"),
            "mk": e.get("make"),
            "md": e.get("model"),
            "ask": round((e.get("asking_price") or 0) / 100),
            "reason": e.get("_reason") or "excluded",
            "url": e.get("listing_url"),
            "src": _src_label(e.get("source")),
        }
        for e in scrutiny.get("excluded", [])
    ]
    return {
        "anchor": round((anchor_cents or 0) / 100),
        "conf": scrutiny.get("confidence", "low"),
        "source": source,
        "used": used,
        "excluded": excluded,
        "empty": not used,
    }


def _repair_to_design(repair_alternatives: dict | None) -> dict | None:
    if not repair_alternatives:
        return None
    base = repair_alternatives.get("middle") or next(iter(repair_alternatives.values()))
    line_items = [
        {
            "comp": li["component"],
            "action": li.get("action") or "repair",
            "sev": (li.get("severity") or "moderate"),
            "low": li["cost_low"],
            "high": li["cost_high"],
            "contingent": bool(li.get("contingent")),
        }
        for li in base.get("line_items", [])
    ]
    sourcing = {
        k: {"low": e["total_low"], "high": e["total_high"], "mid": e["total_mid"]}
        for k, e in repair_alternatives.items()
    }
    return {
        "lineItems": line_items,
        "sourcing": sourcing,
        "confirmed": {
            "low": base.get("confirmed_low", 0),
            "high": base.get("confirmed_high", 0),
        },
        "contingent": {
            "low": base.get("contingent_low", 0),
            "high": base.get("contingent_high", 0),
        },
        "buffer": base.get("buffer_pct", 0.2),
    }


def _recon_from_advice(advice: dict) -> list:
    return [
        {
            "action": it.get("work", ""),
            "decision": it.get("decision", "DO"),
            "cost": it.get("cost", 0),
            "why": it.get("why", ""),
        }
        for it in advice.get("recon", {}).get("items", [])
    ]


_SRC_LABELS = {
    "facebook_marketplace": "Facebook",
    "kijiji": "Kijiji",
    "personal_sold": "Your sale",
}


def _src_label(source: str | None) -> str:
    return _SRC_LABELS.get(source or "", (source or "retail").replace("_", " ").title())


def _pastsales_to_design(sold_pool: dict | None) -> dict | None:
    """Similar SOLD vehicles from regal_sold (the engine's wholesale comp pool) —
    actual realized auction prices, with a link back to each Regal market report."""
    cl = (sold_pool or {}).get("comp_list") or []
    if not cl:
        return None
    rows = []
    for c in cl[:16]:
        rid = c.get("regal_id")
        rows.append(
            {
                "y": c.get("year"),
                "mk": c.get("make"),
                "md": c.get("model"),
                "trim": c.get("trim") or "",
                "km": c.get("odometer_km") or 0,
                "price": round((c.get("sale_price") or 0) / 100),
                "date": str(c.get("sold_date")) if c.get("sold_date") else "—",
                "decl": c.get("declarations") or "",
                "tier": c.get("_tier") or "unknown",
                "score": round(c.get("_combined_weight") or 0, 2),
                "url": (
                    f"https://regalauctions.com/marketReport.php?a=details&id={rid}"
                    if rid
                    else None
                ),
            }
        )
    clean = (sold_pool.get("tier_stats") or {}).get("clean") or {}
    med = sold_pool.get("base_median")
    return {
        "count": sold_pool.get("comp_count") or len(cl),
        "cleanCount": sold_pool.get("clean_count") or clean.get("count") or 0,
        "median": round(med / 100) if med else None,
        "confidence": sold_pool.get("confidence") or "low",
        "fallback": bool(sold_pool.get("fallback_used")),
        "rows": rows,
    }


def _carfax_to_design(carfax: dict | None) -> dict | None:
    if not carfax:
        return None
    service = carfax.get("service_summary") or carfax.get("service")
    if not service:
        n, d = carfax.get("service_records_count"), carfax.get("service_detail")
        if n is not None or (d and d != "unknown"):
            service = (f"{n} records" if n is not None else "records") + (
                f" · {d}" if d and d != "unknown" else ""
            )
    branding = carfax.get("branding") or carfax.get("title_brand") or "None"
    if isinstance(branding, str) and branding.lower() in ("none", "unknown"):
        branding = "None"
    return {
        "accidents": carfax.get("accidents_reported") or carfax.get("accidents") or 0,
        "claims": carfax.get("total_claims_cad") or carfax.get("claims") or 0,
        "branding": branding,
        "lastKm": carfax.get("last_reported_km")
        or carfax.get("last_km")
        or carfax.get("lastKm")
        or 0,
        "service": service or "—",
        "notes": carfax.get("notes") or "",
        "source": carfax.get("_source")
        or ("carfax-agent" if carfax.get("confidence") else "manual"),
    }


def _meta(ai: dict, elapsed: float, effort: str) -> dict:
    u = ai.get("_usage") or {}
    tin, cache, out = (
        u.get("input", 0) or 0,
        u.get("cache_read", 0) or 0,
        u.get("output", 0) or 0,
    )
    cost = tin / 1e6 * _PRICE_IN + cache / 1e6 * _PRICE_CACHE + out / 1e6 * _PRICE_OUT
    return {
        "model": ai.get("_model", "claude-sonnet-4-6"),
        "effort": effort,
        "elapsed": round(elapsed, 1),
        "tokens": {"in": tin, "cache": cache, "out": out},
        "cost": round(cost, 3),
    }


# ── main entry ────────────────────────────────────────────────────────────────


def evaluate(
    conn,
    contract: str,
    *,
    profile: str = "charles",
    ai_mode: str | None = None,
    progress=None,
    use_deep_cache: bool = True,
    store_deep: bool = True,
    collect_comps=None,
) -> dict | None:
    """Run the engine for one contract and return a design-shaped vehicle dict (or None).
    `progress(stage)` is called at each step (used by the streaming endpoint).
    For ai_mode='deep': serve a fresh cached result if one exists (use_deep_cache), and
    persist the computed result (store_deep) so overnight batch runs make morning opens instant.
    """
    _p = progress or (lambda *a, **k: None)
    raw = fetch_listing_from_db(contract, conn)
    if not raw:
        return None

    vehicle = parse_listing_to_vehicle(raw)
    vehicle.update(prompt_condition(vehicle, skip=True))
    # VIN factory spec gap-fills blanks (driveline/engine/cab/trim/…) before vision/overrides.
    # Live NHTSA fetch only off the lane (ai_mode set); bulk screening serves cache only.
    from engine import settings as _st

    if _st.engine_flag("vin_decode", True):
        apply_vin_decode(conn, vehicle, allow_fetch=ai_mode is not None)
    va = _get_subject_vision(conn, contract) or {}
    if not va and ai_mode == "deep":
        _p("Reading listing photos")
    if not va and _maybe_autorun_vision(
        conn, raw, ai_mode
    ):  # deep: pull + read photos if missing
        va = _get_subject_vision(conn, contract) or {}
    if va:
        _apply_vision_spec(vehicle, va)
        vehicle["condition_notes"] = _append_dash_lights(
            vehicle.get("condition_notes"), va
        )
    if vehicle.get("vin") and vehicle.get("service_records") in (None, "none"):
        vehicle["service_records"] = "unknown"

    # Operator input overrides win over scrape + vision (trim/cab/km/grades/declarations…)
    overrides = get_overrides(conn, contract)
    _apply_overrides(vehicle, overrides)

    # Deep-cache: serve a fresh pre-computed deep result instantly (overnight batch fills it).
    dh = None
    if ai_mode == "deep":
        dh = _inputs_hash(conn, contract, profile, vehicle, overrides)
        if use_deep_cache:
            cached = get_deep_cache(conn, contract, profile, dh)
            if cached:
                _p("Loaded overnight deep result")
                return cached

    v = _appraise_core(
        conn,
        vehicle=vehicle,
        raw=raw,
        va=va,
        overrides=overrides,
        contract=contract,
        ctx=AUCTION_CTX,
        ai_mode=ai_mode,
        profile=profile,
        progress=progress,
        collect_comps=collect_comps,
        autopull_carfax=True,
    )
    if ai_mode is None and v:
        _DET_CACHE[(str(contract), profile)] = v
    if ai_mode == "deep" and v and store_deep and not v.get("aiError"):
        put_deep_cache(conn, contract, profile, dh, v)
    return v


def _appraise_core(
    conn,
    *,
    vehicle,
    raw,
    va,
    overrides,
    contract,
    ctx,
    ai_mode,
    profile,
    progress=None,
    collect_comps=None,
    autopull_carfax=False,
    ad=None,
):
    """The shared deep pipeline over a prepared `vehicle` + purchase `ctx`: comps → valuate →
    anchor → carfax → advise → repair → VMR → AI appraise → design vehicle. Used by both the
    Regal flow (evaluate, contract set, ctx=auction) and off-auction appraisals (appraise_subject,
    contract=None, ad={source,url,asking_price}). Carfax/feedback are contract-only."""
    _p = progress or (lambda *a, **k: None)

    # Deep, on a genuine run: collect retail comps once if we have none + vision-read them, so the
    # Comps tab populates and the AI reasons over a fixed set.
    if ai_mode == "deep":
        _p("Searching live comps")
        _maybe_autocollect_comps(conn, vehicle, ai_mode, collect_comps)
        n_vis = _maybe_vision_comps(conn, vehicle, ai_mode)
        if n_vis:
            _p(f"Reading comp photos ({n_vis})")

    _p("Screening comps & history")
    try:
        valuation = valuate(vehicle, conn=conn, log_to_db=False)
    except (
        Exception
    ) as e:  # noqa: BLE001 — never let a bad comp pool sink the dashboard
        valuation = {"error": str(e)}

    # Past Sales tab — actual regal_sold results for similar units (works off-contract too).
    try:
        sold_pool = get_comp_pool(vehicle, conn=conn)
    except Exception:  # noqa: BLE001
        sold_pool = {}

    anchor, clean, source, scrutiny = _advisor_anchor(conn, vehicle, valuation)
    if not anchor:
        anchor = clean = (raw.get("reserve_price") if raw else None) or (
            (ad or {}).get("asking_price") or 0
        )

    # Carfax is contract-keyed (Regal). Off-auction (VIN-based pull) is deferred.
    carfax = None
    if contract:
        cur = get_cursor(conn)
        cur.execute(
            "SELECT carfax_report FROM regal_listings WHERE contract = %s "
            "ORDER BY last_updated_at DESC LIMIT 1",
            (contract,),
        )
        row = cur.fetchone()
        cur.close()
        carfax = (row.get("carfax_report") if row else None) or None
        if carfax is None and ai_mode == "deep" and autopull_carfax:
            _p("Pulling Carfax")
            carfax = _maybe_autopull_carfax(contract)

    decl = analyze_declarations(
        vehicle.get("declarations") or "", vehicle.get("condition_notes") or ""
    )
    ch = advise(
        vehicle,
        anchor_cents=anchor,
        clean_value_cents=clean,
        decl=decl,
        vision=va,
        carfax=carfax,
        profile_key="charles",
        ctx=ctx,
    )
    me = advise(
        vehicle,
        anchor_cents=anchor,
        clean_value_cents=clean,
        decl=decl,
        vision=va,
        carfax=carfax,
        profile_key="mechanic",
        ctx=ctx,
    )
    prof_advice = ch if profile == "charles" else me

    # profile-aware repair sourcing matrix (only meaningful when there's wreck damage)
    comps_rc = (va or {}).get("repair_components") or []
    rc = ADV_PROFILES["charles"]["repair"]
    repair_est = estimate_repair(
        comps_rc,
        buffer=ADV_PROFILES["charles"]["repair_buffer"],
        small_factor=rc["small_factor"],
        large_factor=rc["large_factor"],
    )
    repair_alternatives = None
    if comps_rc:
        repair_alternatives = {
            "oem_shop": estimate_repair(comps_rc, small_factor=1.0, large_factor=1.0),
            "middle": estimate_repair(comps_rc, small_factor=0.65, large_factor=1.0),
            "used_diy": estimate_repair(comps_rc, small_factor=0.5, large_factor=0.55),
        }

    # VMR Canada book value — published sanity check (only when an AI pass runs).
    vmr = None
    if ai_mode:
        _p("Checking VMR book value")
        try:
            from collector.vmr import vmr_lookup

            vmr = vmr_lookup(
                vehicle.get("year"),
                vehicle.get("make"),
                vehicle.get("model"),
                km=vehicle.get("odometer_km"),
                trim=vehicle.get("trim"),
                cab=vehicle.get("cab"),
                driveline=vehicle.get("driveline"),
                engine=vehicle.get("engine"),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[vmr] {e}")

    calibration = _calibration(conn, vehicle)
    ai, meta, ai_error = None, None, None
    if ai_mode:
        from engine.appraiser import appraise, EFFORT, TRIAGE_EFFORT

        prof = {**ADV_PROFILES[profile], "label": ADV_PROFILES[profile]["label"]}
        _p("AI appraising" + (" (deep)" if ai_mode == "deep" else ""))
        try:
            t0 = time.time()
            ai = appraise(
                vehicle,
                comp_narrative=(scrutiny or {}).get("narrative") or [],
                comp_anchor_cents=anchor,
                comp_confidence=(scrutiny or {}).get("confidence", "low"),
                declarations=decl,
                vision=va,
                repair_est=repair_est,
                deterministic=prof_advice,
                profile=prof,
                mode=ai_mode,
                calibration=calibration,
                vmr=vmr,
                carfax=carfax,
                repair_alternatives=repair_alternatives,
                ctx=ctx,
                tool_ctx=(
                    {
                        "conn": conn,
                        "subject": vehicle,
                        "vision": va,
                        "profile": ADV_PROFILES[profile],
                    }
                    if ai_mode == "deep"
                    else None
                ),
                progress=progress,
            )
            meta = _meta(
                ai, time.time() - t0, TRIAGE_EFFORT if ai_mode == "triage" else EFFORT
            )
        except Exception as e:  # noqa: BLE001 — degrade to the deterministic result
            ai, ai_error = None, str(e)

    feedback = get_feedback(conn, contract) if contract else None
    return _to_design(
        contract,
        vehicle,
        raw,
        sold_pool,
        decl,
        va,
        scrutiny,
        anchor,
        source,
        ch,
        me,
        prof_advice,
        repair_alternatives,
        carfax,
        ai,
        ai_mode,
        meta,
        profile,
        ai_error,
        feedback,
        vmr,
        overrides,
        ad,
    )


# ── off-auction appraisal: any vehicle, no Regal contract ─────────────────────


def appraise_subject(
    conn,
    vehicle: dict,
    *,
    seller_type: str = "private",
    photos: list | None = None,
    asking_price_dollars=None,
    source: str = "manual",
    ad_url: str | None = None,
    profile: str = "charles",
    ai_mode: str = "deep",
    progress=None,
) -> dict:
    """Deep-appraise a vehicle that ISN'T a Regal lot (manual selector, VIN, or scraped ad).
    No auction fee; tax follows the active location + seller type. `vehicle` is a spec dict
    (year/make/model/trim/km/…). Returns the same design shape as evaluate()."""
    from engine import settings as _st

    _p = progress or (lambda *a, **k: None)
    vehicle.update(prompt_condition(vehicle, skip=True))  # neutral condition defaults
    if _st.engine_flag("vin_decode", True):
        apply_vin_decode(conn, vehicle, allow_fetch=True)

    # Purchase context from the active location + seller type (dealer/business taxed, private per rate).
    kind = "dealer" if seller_type in ("dealer", "business") else "private"
    ctx = purchase_context(kind, tax_rate=_st.location_tax(kind))

    # Vision on the ad's photos (in-memory — no DB row), like the subject vision read for a lot.
    va = {}
    photos = [p for p in (photos or []) if p]
    if photos and ai_mode == "deep":
        _p("Reading listing photos")
        try:
            from engine.vision import assess_vehicle
            from engine.vision_factors import vision_to_spec

            summary = " ".join(
                str(vehicle.get(k) or "") for k in ("year", "make", "model", "trim")
            ).strip()
            va = assess_vehicle("adhoc", photos, summary) or {}
            if va and not va.get("error"):
                vehicle.update(vision_to_spec(va, vehicle))
                vehicle["condition_notes"] = _append_dash_lights(
                    vehicle.get("condition_notes"), va
                )
            else:
                va = {}
        except Exception as e:  # noqa: BLE001 — vision is best-effort
            print(f"[appraise_subject vision] {e}")
            va = {}

    raw = {
        "main_photo_url": photos[0] if photos else None,
        "photo_urls": photos,
        "raw_json": {},
        "reserve_price": None,
        "auction_date": None,
        "vin": vehicle.get("vin"),
        "carfax_url": None,
    }
    ad = {"source": source, "url": ad_url, "asking_price": _d2c(asking_price_dollars)}
    return _appraise_core(
        conn,
        vehicle=vehicle,
        raw=raw,
        va=va,
        overrides={},
        contract=None,
        ctx=ctx,
        ai_mode=ai_mode,
        profile=profile,
        progress=progress,
        ad=ad,
    )


# ── persisted deep cache (overnight batch → instant morning opens) ────────────


def _inputs_hash(
    conn, contract: str, profile: str, vehicle: dict, overrides: dict
) -> str:
    """Fingerprint the inputs a deep result depends on so revisits hit the cache.

    Deliberately STABLE across visits: only the profile + operator overrides + the
    spec/declarations/km. We do NOT include carfax/vision presence or the settings
    timestamp here — those would flip between the first run (which auto-pulls carfax
    after this hash is computed) and later visits, causing spurious re-runs. Freshness
    for those is handled explicitly: save_overrides / save_carfax / run_vision /
    flag_comp / a settings change all drop the affected deep_cache rows.
    """
    import hashlib

    sig = {
        "profile": profile,
        "ov": overrides or {},
        "decl": vehicle.get("declarations"),
        "notes": vehicle.get(
            "condition_notes"
        ),  # scraped remarks → re-run if they change
        "km": vehicle.get("odometer_km"),
        "spec": [vehicle.get(k) for k in ("trim", "cab", "bed", "driveline", "engine")],
    }
    return hashlib.sha256(
        json.dumps(sig, sort_keys=True, default=str).encode()
    ).hexdigest()


def get_deep_cache(
    conn, contract: str, profile: str, inputs_hash: str | None
) -> dict | None:
    cur = get_cursor(conn)
    cur.execute(
        "SELECT inputs_hash, payload FROM deep_cache WHERE contract=%s AND profile=%s",
        (str(contract), profile),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    if inputs_hash is not None and row.get("inputs_hash") != inputs_hash:
        return None  # inputs changed since this was computed → stale
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if isinstance(payload, dict):
        payload["_cached"] = True
    return payload


def get_cached_deep(conn, contract: str, profile: str) -> dict | None:
    """The stored deep result for (contract, profile) regardless of inputs-hash freshness —
    used to RE-DISPLAY a persisted deep appraisal on reload/navigation without recomputing
    (the deep run continues server-side and is cached even if the user navigates away).
    """
    return get_deep_cache(conn, contract, profile, None)


def put_deep_cache(
    conn, contract: str, profile: str, inputs_hash: str | None, payload: dict
) -> None:
    cur = get_cursor(conn)
    cur.execute(
        """INSERT INTO deep_cache (contract, profile, inputs_hash, payload, created_at)
                   VALUES (%s,%s,%s,%s::jsonb, NOW())
                   ON CONFLICT (contract, profile) DO UPDATE SET
                     inputs_hash=EXCLUDED.inputs_hash, payload=EXCLUDED.payload, created_at=NOW()""",
        (str(contract), profile, inputs_hash, json.dumps(payload)),
    )
    conn.commit()
    cur.close()


def drop_deep_cache(conn, contract: str) -> None:
    cur = get_cursor(conn)
    cur.execute("DELETE FROM deep_cache WHERE contract=%s", (str(contract),))
    conn.commit()
    cur.close()


def deep_cached_contracts(conn, contracts: list, profile: str) -> set:
    """Which of these contracts have a stored deep result (for the lane 'deep ✓' badge)."""
    if not contracts:
        return set()
    cur = get_cursor(conn)
    cur.execute(
        "SELECT contract FROM deep_cache WHERE profile=%s AND contract = ANY(%s)",
        (profile, [str(c) for c in contracts]),
    )
    out = {r["contract"] for r in cur.fetchall()}
    cur.close()
    return out


def _scrape_retail_comps(vehicle: dict, location: str | None = None) -> int:
    """Trim-targeted Facebook Marketplace scrape for this vehicle → retail_listings.
    Returns the number upserted. Raises if make/model unknown or APIFY_TOKEN missing.
    `location` defaults to the active location's city (Edmonton if unset)."""
    make = (vehicle.get("make") or "").strip()
    model = (vehicle.get("model") or "").strip()
    year = vehicle.get("year")
    if not (make and model):
        raise RuntimeError("vehicle make/model unknown — can't search for comps")
    if not location:
        from engine import settings as _st

        location = (
            _st.active_location().get("city") or "edmonton"
        ).strip() or "edmonton"
    from collector.retail_comps import collect_facebook

    # model can be "MAZDA3" with make "MAZDA" — avoid a redundant doubled query
    query = model if make.upper() in model.upper() else f"{make} {model}"
    trim = (vehicle.get("trim") or "").strip()
    if trim:  # target the right trim (a Lariat needs Lariat comps, not XLT)
        query = f"{query} {trim}"
    return collect_facebook(
        location,
        query,
        max_listings=20,
        min_year=(year - 3 if year else None),
        max_year=(year + 3 if year else None),
    )


def _retail_comp_count(conn, vehicle: dict) -> int:
    """How many usable (non-flagged) retail comps we already have for this vehicle."""
    yr = vehicle.get("year")
    make = (vehicle.get("make") or "").upper()
    model = (vehicle.get("model") or "").upper()
    if not (yr and make and model):
        return 0
    from engine import settings as _st

    province = (_st.active_location().get("province") or "AB").upper()
    cur = get_cursor(conn)
    cur.execute(
        """SELECT count(*) n FROM retail_listings
                   WHERE UPPER(make) = %s AND UPPER(COALESCE(model,'')) LIKE %s
                     AND year BETWEEN %s AND %s AND asking_price >= 300000 AND is_sold = FALSE
                     AND UPPER(COALESCE(location_province,'')) = %s
                     AND external_id NOT IN (SELECT external_id FROM comp_feedback WHERE status='bad')""",
        (make, model.split()[0] + "%", yr - 2, yr + 2, province),
    )
    n = cur.fetchone()["n"]
    cur.close()
    return n


def _maybe_autocollect_comps(
    conn, vehicle: dict, ai_mode: str | None, collect_comps
) -> bool:
    """Deep only: if we don't already have retail comps, scrape them ONCE before the
    anchor is built — so the Comps tab populates from the deep run and the AI reasons
    over a fixed comp set (no mid-run scraping). Gated by the deep_autocollect_comps
    setting; `collect_comps` (True/False) overrides it for the batch."""
    if ai_mode != "deep":
        return False
    from engine import settings as _st

    allow = (
        collect_comps
        if collect_comps is not None
        else _st.engine_flag("deep_autocollect_comps", True)
    )
    if not allow:
        return False
    if _retail_comp_count(conn, vehicle) >= 3:
        return False  # already have comps — don't re-scrape (cost) and don't churn the anchor
    try:
        _scrape_retail_comps(vehicle)
        return True
    except (
        Exception
    ) as e:  # noqa: BLE001 — no token / make unknown / network: continue without comps
        print(f"[deep autocollect comps] {vehicle.get('contract')}: {e}")
        return False


def _maybe_vision_comps(
    conn, vehicle: dict, ai_mode: str | None, limit: int = 6
) -> int:
    """Deep only, gated by deep_vision_comps (default OFF): run the cheap Haiku vision pass
    on this vehicle's matching comps that have photos but no stored assessment yet, so
    comp_scrutiny can drop the ones that are cheap BECAUSE they're wrecked. Bounded + best-
    effort: an API failure on one comp never sinks the eval. Returns how many were assessed.
    """
    if ai_mode != "deep":
        return 0
    from engine import settings as _st

    if not _st.engine_flag("deep_vision_comps", False):
        return 0
    yr = vehicle.get("year")
    make = (vehicle.get("make") or "").upper()
    model = (vehicle.get("model") or "").upper()
    if not (yr and make and model):
        return 0
    cur = get_cursor(conn)
    cur.execute(
        """SELECT external_id FROM retail_listings
           WHERE UPPER(make) = %s AND UPPER(COALESCE(model,'')) LIKE %s
             AND year BETWEEN %s AND %s AND asking_price >= 300000 AND is_sold = FALSE
             AND vision_assessment IS NULL AND photo_urls IS NOT NULL
             AND external_id NOT IN (SELECT external_id FROM comp_feedback WHERE status='bad')
           ORDER BY (odometer_km IS NOT NULL) DESC, collected_at DESC LIMIT %s""",
        (make, model.split()[0] + "%", yr - 2, yr + 2, limit),
    )
    ids = [r["external_id"] for r in cur.fetchall()]
    cur.close()
    if not ids:
        return 0
    from engine.vision import assess_retail_listing

    done = 0
    for eid in ids:
        try:
            assess_retail_listing(eid)  # Haiku triage; stores vision_assessment back
            done += 1
        except Exception as e:  # noqa: BLE001 — best effort per comp
            print(f"[deep vision comps] {eid}: {e}")
    return done


def fetch_comps(
    conn, contract: str, *, profile: str = "charles", location: str = "edmonton"
) -> dict | None:
    """On-demand (triage 'Scan for comps'): scrape FB for this vehicle, then re-evaluate
    so the Comps tab populates. Slow (live Apify scrape)."""
    raw = fetch_listing_from_db(contract, conn)
    if not raw:
        return None
    vehicle = parse_listing_to_vehicle(raw)
    added = _scrape_retail_comps(vehicle, location)

    # drop any cached result so the re-eval picks up the new comps
    for key in [k for k in _DET_CACHE if k[0] == str(contract)]:
        _DET_CACHE.pop(key, None)
    drop_deep_cache(conn, contract)

    v = evaluate(conn, contract, profile=profile, ai_mode=None)
    return {"vehicle": v, "added": added}


# ── Training / feedback loop ──────────────────────────────────────────────────


def _c2d(c):
    return round(c / 100) if c is not None else None


def _d2c(v):
    try:
        return int(round(float(v) * 100)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def get_feedback(conn, contract: str) -> dict | None:
    cur = get_cursor(conn)
    cur.execute("SELECT * FROM listing_feedback WHERE contract = %s", (str(contract),))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {
        "actualSale": _c2d(row.get("actual_sale_price")),
        "correctedValue": _c2d(row.get("corrected_value")),
        "correctedMaxBid": _c2d(row.get("corrected_max_bid")),
        "verdictCorrect": row.get("verdict_correct"),
        "engineMode": row.get("engine_mode"),
        "notes": row.get("notes") or "",
        "updatedAt": str(row.get("updated_at"))[:16] if row.get("updated_at") else None,
    }


def save_feedback(conn, contract: str, data: dict) -> dict | None:
    cur = get_cursor(conn)
    cur.execute(
        """
        INSERT INTO listing_feedback (contract, year, make, model,
            engine_verdict, engine_value, engine_max_bid,
            actual_sale_price, corrected_value, corrected_max_bid, verdict_correct,
            engine_mode, notes, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT (contract) DO UPDATE SET
            year=EXCLUDED.year, make=EXCLUDED.make, model=EXCLUDED.model,
            engine_verdict=EXCLUDED.engine_verdict, engine_value=EXCLUDED.engine_value,
            engine_max_bid=EXCLUDED.engine_max_bid, actual_sale_price=EXCLUDED.actual_sale_price,
            corrected_value=EXCLUDED.corrected_value, corrected_max_bid=EXCLUDED.corrected_max_bid,
            verdict_correct=EXCLUDED.verdict_correct, engine_mode=EXCLUDED.engine_mode,
            notes=EXCLUDED.notes, updated_at=NOW()
    """,
        (
            str(contract),
            data.get("year"),
            data.get("make"),
            data.get("model"),
            data.get("engineVerdict"),
            _d2c(data.get("engineValue")),
            _d2c(data.get("engineMaxBid")),
            _d2c(data.get("actualSale")),
            _d2c(data.get("correctedValue")),
            _d2c(data.get("correctedMaxBid")),
            data.get("verdictCorrect"),
            (data.get("engineMode") or None),
            (data.get("notes") or None),
        ),
    )
    conn.commit()
    cur.close()
    return get_feedback(conn, contract)


def flag_comp(
    conn,
    external_id: str,
    contract: str | None,
    status: str = "bad",
    reason: str = None,
) -> bool:
    cur = get_cursor(conn)
    cur.execute(
        """INSERT INTO comp_feedback (external_id, contract, status, reason)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (external_id) DO UPDATE SET
                     status=EXCLUDED.status, reason=EXCLUDED.reason, contract=EXCLUDED.contract""",
        (external_id, str(contract) if contract else None, status, reason),
    )
    conn.commit()
    cur.close()
    _DET_CACHE.clear()  # a changed comp set can move any anchor — rescreen fresh
    clear_all_deep_cache(conn)
    return True


def clear_all_deep_cache(conn) -> None:
    cur = get_cursor(conn)
    cur.execute("DELETE FROM deep_cache")
    conn.commit()
    cur.close()


# ── personal sales (your own realized retail comps; manual entry) ─────────────


def _personal_sale_to_design(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "year": r.get("year"),
        "make": r.get("make"),
        "model": r.get("model"),
        "trim": r.get("trim") or "",
        "km": r.get("odometer_km") or 0,
        "condition": r.get("condition") or "",
        "salePrice": _c2d(r.get("sale_price")),
        "soldDate": str(r.get("sold_date")) if r.get("sold_date") else None,
        "notes": r.get("notes") or "",
        "createdAt": str(r.get("created_at"))[:16] if r.get("created_at") else None,
    }


def list_personal_sales(conn) -> list:
    cur = get_cursor(conn)
    cur.execute(
        "SELECT * FROM personal_sales ORDER BY sold_date DESC NULLS LAST, id DESC"
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return [_personal_sale_to_design(r) for r in rows]


def add_personal_sale(conn, data: dict) -> dict | None:
    """Insert one hand-entered sold record (sale price in dollars → cents). Invalidates
    caches since a new realized comp can move any anchor."""
    price = _d2c(data.get("salePrice"))
    if not price:
        return None
    cur = get_cursor(conn)
    cur.execute(
        """INSERT INTO personal_sales
               (year, make, model, trim, odometer_km, condition, sale_price, sold_date, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            data.get("year") or None,
            (data.get("make") or "").strip().upper() or None,
            (data.get("model") or "").strip().upper() or None,
            (data.get("trim") or "").strip() or None,
            (int(data["km"]) if str(data.get("km") or "").strip().isdigit() else None),
            (data.get("condition") or "").strip() or None,
            price,
            (data.get("soldDate") or None),
            (data.get("notes") or "").strip() or None,
        ),
    )
    row = dict(cur.fetchone())
    conn.commit()
    cur.close()
    _DET_CACHE.clear()  # a new realized comp can move any anchor — rescreen fresh
    clear_all_deep_cache(conn)
    return _personal_sale_to_design(row)


def delete_personal_sale(conn, sale_id: int) -> bool:
    cur = get_cursor(conn)
    cur.execute("DELETE FROM personal_sales WHERE id = %s", (sale_id,))
    conn.commit()
    cur.close()
    _DET_CACHE.clear()
    clear_all_deep_cache(conn)
    return True


# ── calibration analytics (engine vs reality, from listing_feedback) ──────────

_PRICE_BANDS = [
    (0, 500000, "< $5k"),
    (500000, 1000000, "$5–10k"),
    (1000000, 2000000, "$10–20k"),
    (2000000, 3500000, "$20–35k"),
    (3500000, 10**12, "$35k+"),
]


def _band(cents) -> str:
    for lo, hi, label in _PRICE_BANDS:
        if cents is not None and lo <= cents < hi:
            return label
    return "—"


def _agg(errs: list) -> dict:
    """errs = list of signed pct errors (engine vs truth). Returns n / MAE% / bias%."""
    if not errs:
        return {"n": 0, "mae": None, "bias": None}
    return {
        "n": len(errs),
        "mae": round(sum(abs(e) for e in errs) / len(errs), 1),
        "bias": round(sum(errs) / len(errs), 1),
    }


def _pct_err(engine, truth):
    """Signed % error of an engine number vs a truth value. + = engine HIGH (over)."""
    if engine is None or not truth:
        return None
    return round((engine - truth) / truth * 100, 1)


def _seg_sort(d: dict) -> list:
    """Make/band buckets → list of {key, n, mae, bias}, worst MAE first."""
    return sorted(
        ({"key": k, **_agg(v)} for k, v in d.items()),
        key=lambda x: (x["mae"] is None, -(x["mae"] or 0)),
    )


def _sample(r, *, track, v_err, b_err) -> dict:
    """One calibration-table row (shared shape across both tracks)."""
    return {
        "contract": r["contract"],
        "year": r.get("year"),
        "make": r.get("make"),
        "model": r.get("model"),
        "track": track,  # 'retail' | 'wholesale'
        "engineMode": r.get("engine_mode"),  # deep | triage | rules | auto
        "engineVerdict": r.get("engine_verdict"),
        "engineValue": _c2d(r.get("engine_value")),
        "engineMaxBid": _c2d(r.get("engine_max_bid")),
        "actualSale": _c2d(r.get("actual_sale_price")),
        "correctedValue": _c2d(r.get("corrected_value")),
        "correctedMaxBid": _c2d(r.get("corrected_max_bid")),
        "valueErrPct": v_err,
        "bidErrPct": b_err,
        "verdictCorrect": r.get("verdict_correct"),
        "notes": r.get("notes") or "",
        "updatedAt": str(r.get("updated_at"))[:16] if r.get("updated_at") else None,
    }


def _verdict_acc(rows: list) -> tuple[int | None, int]:
    graded = [r for r in rows if r.get("verdict_correct") is not None]
    if not graded:
        return None, 0
    right = sum(1 for r in graded if r["verdict_correct"])
    return round(right / len(graded) * 100), len(graded)


def _mode_breakdown(rows: list) -> list:
    counts: dict = {}
    for r in rows:
        counts[r.get("engine_mode") or "unknown"] = (
            counts.get(r.get("engine_mode") or "unknown", 0) + 1
        )
    return sorted(
        ({"mode": k, "n": v} for k, v in counts.items()), key=lambda x: -x["n"]
    )


def calibration(conn) -> dict:
    """Engine-vs-reality calibration, split into TWO tracks that must not be averaged together:

    retail  — your Correct-tab corrections (the signal that matters; ideally on DEEP calls).
              value error = engine_value vs corrected_value; bid error = engine_max_bid vs
              corrected_max_bid. Same basis (retail), unconfounded.
    wholesale — the auto-imported backtest: engine_max_bid vs the actual Regal hammer price.
              MARGIN-AFFECTED (max bid sits below the hammer by design) and built off the shoddy
              wholesale data — a TRIAGE/comp-engine baseline, not a measure of deep accuracy.

    Positive % = engine HIGH (over-valued / over-bid); negative = engine LOW.
    """
    cur = get_cursor(conn)
    cur.execute(
        """SELECT contract, year, make, model, engine_verdict, engine_value, engine_max_bid,
                  actual_sale_price, corrected_value, corrected_max_bid, verdict_correct,
                  engine_mode, notes, updated_at
           FROM listing_feedback ORDER BY updated_at DESC"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()

    # Classify each row by which truth it carries. A human retail correction (corrected_*)
    # is the richer signal and wins; otherwise an actual hammer price is the wholesale track.
    retail_rows = [
        r
        for r in rows
        if r.get("corrected_value") is not None
        or r.get("corrected_max_bid") is not None
    ]
    wholesale_rows = [
        r for r in rows if r not in retail_rows and r.get("actual_sale_price")
    ]

    # ── retail track: engine vs corrected (value + bid), both on a retail basis ──
    r_val, r_bid, r_make, r_band, r_samples = [], [], {}, {}, []
    for r in retail_rows:
        v_err = _pct_err(r.get("engine_value"), r.get("corrected_value"))
        b_err = _pct_err(r.get("engine_max_bid"), r.get("corrected_max_bid"))
        if v_err is not None:
            r_val.append(v_err)
        if b_err is not None:
            r_bid.append(b_err)
        seg_err = v_err if v_err is not None else b_err
        seg_truth = r.get("corrected_value") or r.get("corrected_max_bid")
        if seg_err is not None:
            r_make.setdefault((r.get("make") or "—").upper(), []).append(seg_err)
            r_band.setdefault(_band(seg_truth), []).append(seg_err)
        r_samples.append(_sample(r, track="retail", v_err=v_err, b_err=b_err))
    r_acc, r_acc_n = _verdict_acc(retail_rows)

    # ── wholesale track: engine max bid vs actual hammer price (margin-affected) ──
    w_bid, w_make, w_band, w_samples = [], {}, {}, []
    for r in wholesale_rows:
        b_err = _pct_err(r.get("engine_max_bid"), r.get("actual_sale_price"))
        if b_err is not None:
            w_bid.append(b_err)
            w_make.setdefault((r.get("make") or "—").upper(), []).append(b_err)
            w_band.setdefault(_band(r.get("actual_sale_price")), []).append(b_err)
        w_samples.append(_sample(r, track="wholesale", v_err=None, b_err=b_err))
    w_acc, w_acc_n = _verdict_acc(wholesale_rows)

    return {
        "retail": {
            "value": _agg(r_val),
            "bid": _agg(r_bid),
            "verdictAccuracy": r_acc,
            "verdictN": r_acc_n,
            "byMake": _seg_sort(r_make),
            "byBand": _seg_sort(r_band),
            "modes": _mode_breakdown(retail_rows),
            "total": len(retail_rows),
        },
        "wholesale": {
            "bid": _agg(w_bid),
            "verdictAccuracy": w_acc,
            "verdictN": w_acc_n,
            "byMake": _seg_sort(w_make),
            "byBand": _seg_sort(w_band),
            "modes": _mode_breakdown(wholesale_rows),
            "total": len(wholesale_rows),
        },
        "samples": r_samples + w_samples,
        "total": len(rows),
    }


def calibration_csv(conn) -> str:
    import csv
    import io

    data = calibration(conn)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "contract",
            "track",
            "engine_mode",
            "year",
            "make",
            "model",
            "engine_verdict",
            "engine_value",
            "engine_max_bid",
            "actual_sale",
            "corrected_value",
            "corrected_max_bid",
            "value_err_pct",
            "bid_err_pct",
            "verdict_correct",
            "updated_at",
            "notes",
        ]
    )
    for s in data["samples"]:
        w.writerow(
            [
                s["contract"],
                s["track"],
                s["engineMode"],
                s["year"],
                s["make"],
                s["model"],
                s["engineVerdict"],
                s["engineValue"],
                s["engineMaxBid"],
                s["actualSale"],
                s["correctedValue"],
                s["correctedMaxBid"],
                s["valueErrPct"],
                s["bidErrPct"],
                s["verdictCorrect"],
                s["updatedAt"],
                (s["notes"] or "").replace("\n", " "),
            ]
        )
    return buf.getvalue()


# ── input overrides (operator corrections to a listing's inputs) ──────────────

_OVERRIDE_INT_FIELDS = (
    "odometer_km",
    "exterior_grade",
    "interior_grade",
    "mechanical_grade",
)
_OVERRIDE_FIELDS = (
    "trim",
    "cab",
    "bed",
    "driveline",
    "engine",
    "declarations",
    "condition_notes",
    *_OVERRIDE_INT_FIELDS,
)


def get_overrides(conn, contract: str) -> dict:
    cur = get_cursor(conn)
    cur.execute(
        "SELECT overrides FROM listing_overrides WHERE contract = %s", (str(contract),)
    )
    row = cur.fetchone()
    cur.close()
    ov = (row.get("overrides") if row else None) or {}
    if isinstance(ov, str):
        try:
            ov = json.loads(ov)
        except (ValueError, TypeError):
            ov = {}
    return ov


def _apply_overrides(vehicle: dict, ov: dict) -> None:
    """Overlay operator input corrections onto the spec (they win over scrape + vision)."""
    for k, val in (ov or {}).items():
        if k not in _OVERRIDE_FIELDS or val in (None, ""):
            continue
        if k in _OVERRIDE_INT_FIELDS:
            try:
                val = int(round(float(str(val).replace(",", ""))))
            except (TypeError, ValueError):
                continue
        vehicle[k] = val


def save_overrides(
    conn, contract: str, overrides: dict, *, profile: str = "charles"
) -> dict | None:
    """Persist input overrides for a contract, then re-evaluate so the corrected inputs
    flow through comps / VMR / the verdict immediately."""
    clean = {
        k: overrides[k]
        for k in _OVERRIDE_FIELDS
        if k in overrides and overrides[k] not in (None, "")
    }
    cur = get_cursor(conn)
    cur.execute(
        """INSERT INTO listing_overrides (contract, overrides, updated_at)
                   VALUES (%s, %s::jsonb, NOW())
                   ON CONFLICT (contract) DO UPDATE SET overrides = EXCLUDED.overrides, updated_at = NOW()""",
        (str(contract), json.dumps(clean)),
    )
    conn.commit()
    cur.close()
    for key in [k for k in _DET_CACHE if k[0] == str(contract)]:
        _DET_CACHE.pop(key, None)
    drop_deep_cache(conn, contract)
    return evaluate(conn, contract, profile=profile, ai_mode=None)


def _int(v):
    try:
        return (
            int(round(float(str(v).replace(",", "").replace("$", ""))))
            if v not in (None, "")
            else None
        )
    except (TypeError, ValueError):
        return None


def save_carfax(
    conn, contract: str, data: dict, *, profile: str = "charles"
) -> dict | None:
    """Store operator-entered Carfax facts on the listing, then re-evaluate so the
    engine's history deduction + the AI price with them in mind."""
    report = {
        "accidents_reported": _int(data.get("accidents")),
        "total_claims_cad": _int(data.get("totalClaims")),
        "branding": (data.get("branding") or None),
        "last_reported_km": _int(data.get("lastKm")),
        "service_summary": (data.get("service") or None),
        "_source": "manual",
    }
    cur = get_cursor(conn)
    cur.execute(
        "UPDATE regal_listings SET carfax_report = %s::jsonb WHERE contract = %s",
        (json.dumps(report), str(contract)),
    )
    conn.commit()
    cur.close()
    for key in [k for k in _DET_CACHE if k[0] == str(contract)]:
        _DET_CACHE.pop(key, None)
    drop_deep_cache(conn, contract)
    return evaluate(conn, contract, profile=profile, ai_mode=None)


def pull_carfax(conn, contract: str, *, profile: str = "charles") -> dict | None:
    """Auto-pull the Carfax via the local headful browser agent (Playwright + vision),
    store it, then re-evaluate. Only works where a real browser is available."""
    from collector.carfax_agent import fetch_carfax

    report = fetch_carfax(str(contract), table="regal_listings")
    if report and report.get("error"):
        raise RuntimeError(
            "could not read the Carfax report (" + str(report.get("error")) + ")"
        )
    for key in [k for k in _DET_CACHE if k[0] == str(contract)]:
        _DET_CACHE.pop(key, None)
    drop_deep_cache(conn, contract)
    return evaluate(conn, contract, profile=profile, ai_mode=None)


def _ensure_vision(conn, raw: dict) -> bool:
    """Enrich the listing's gallery photos (if missing) and run the vision model;
    store the assessment. Returns True if an assessment now exists."""
    regal_id, vin = raw.get("regal_id"), raw.get("vin")
    if not regal_id:
        return False
    rj = raw.get("raw_json")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except (ValueError, TypeError):
            rj = {}
    details_link = (rj or {}).get("detailsLink")
    from collector.regal_enrich import enrich_one
    from engine.vision import assess_and_store

    if not raw.get("photo_urls"):
        try:
            enrich_one(
                regal_id,
                vin,
                table="regal_listings",
                conn=conn,
                details_link=details_link,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[vision enrich] {regal_id}: {e}")
    try:
        res = assess_and_store(regal_id, table="regal_listings")
        return bool(res and not res.get("error"))
    except Exception as e:  # noqa: BLE001
        print(f"[vision] {regal_id}: {e}")
        return False


def run_vision(conn, contract: str, *, profile: str = "charles") -> dict | None:
    """On-demand: enrich photos + read them with the vision model, then re-evaluate."""
    raw = fetch_listing_from_db(str(contract), conn)
    if not raw:
        return None
    _ensure_vision(conn, raw)
    for key in [k for k in _DET_CACHE if k[0] == str(contract)]:
        _DET_CACHE.pop(key, None)
    drop_deep_cache(conn, contract)
    return evaluate(conn, contract, profile=profile, ai_mode=None)


def _maybe_autorun_vision(conn, raw: dict, ai_mode: str | None) -> bool:
    """During a DEEP run, enrich + read photos when there's no assessment yet, so the
    appraisal sees the vehicle. Toggle in Settings (deep_autorun_vision)."""
    if ai_mode != "deep":
        return False
    from engine import settings as _st

    if not _st.engine_flag("deep_autorun_vision", True):
        return False
    return _ensure_vision(conn, raw)


def prep_one(
    conn,
    contract: str,
    *,
    vision=True,
    carfax=False,
    comps=False,
    profile: str = "charles",
) -> dict:
    """Enrich a single listing for a batch 'prep sale' run. Idempotent: skips work that's
    already done. Returns a per-vehicle status dict."""
    raw = fetch_listing_from_db(str(contract), conn)
    if not raw:
        return {"contract": str(contract), "skipped": "not found"}
    status = {"contract": str(contract)}

    if vision:
        if _get_subject_vision(conn, contract) or {}:
            status["vision"] = "had"
        else:
            status["vision"] = "done" if _ensure_vision(conn, raw) else "failed"

    if carfax:
        cur = get_cursor(conn)
        cur.execute(
            "SELECT carfax_report FROM regal_listings WHERE contract=%s "
            "ORDER BY last_updated_at DESC LIMIT 1",
            (str(contract),),
        )
        row = cur.fetchone()
        cur.close()
        if row and row.get("carfax_report"):
            status["carfax"] = "had"
        else:
            try:
                from collector.carfax_agent import fetch_carfax

                rpt = fetch_carfax(str(contract), table="regal_listings")
                status["carfax"] = (
                    "done" if (rpt and not rpt.get("error")) else "failed"
                )
            except Exception as e:  # noqa: BLE001
                status["carfax"] = "failed"
                print(f"[prep carfax] {contract}: {e}")

    if comps:
        try:
            res = fetch_comps(conn, str(contract), profile=profile)
            status["comps"] = (res or {}).get("added", 0)
        except Exception as e:  # noqa: BLE001
            status["comps"] = "failed"
            print(f"[prep comps] {contract}: {e}")

    for key in [k for k in _DET_CACHE if k[0] == str(contract)]:
        _DET_CACHE.pop(key, None)
    drop_deep_cache(conn, contract)
    return status


def sale_contracts(conn, date_str: str, limit: int) -> list:
    """Contracts in a sale, in lot order, capped at `limit` — the prep target list."""
    from datetime import date as _date

    try:
        d = _date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return []
    rows = [
        r
        for r in _sale_query(conn, "auction_date = %s", (d,))
        if r.get("auction_date") and r["auction_date"].weekday() in _SALE_LABELS
    ]
    rows.sort(key=lambda r: _lot_of(r)[1])
    return [str(r["contract"]) for r in rows[:limit]]


def _maybe_autopull_carfax(contract: str) -> dict | None:
    """During a DEEP run, fetch the Carfax if it's missing so the appraisal has
    complete history. Best-effort: needs a local browser; failures are swallowed.
    Toggle in Settings (deep_autopull_carfax)."""
    from engine import settings as _st

    if not _st.engine_flag("deep_autopull_carfax", True):
        return None
    try:
        from collector.carfax_agent import fetch_carfax

        report = fetch_carfax(str(contract), table="regal_listings")
        return report if (report and not report.get("error")) else None
    except (
        Exception
    ) as e:  # noqa: BLE001 — no browser / playwright / captcha: continue without it
        print(f"[carfax autopull] {contract}: {e}")
        return None


def _calibration(conn, vehicle: dict, limit: int = 4) -> list:
    """Recent operator corrections for similar vehicles — fed to the AI so it stops
    repeating mistakes (e.g. anchoring to a damaged comp)."""
    make = (vehicle.get("make") or "").upper()
    model = (vehicle.get("model") or "").upper()
    if not make:
        return []
    cur = get_cursor(conn)
    cur.execute(
        """SELECT year, make, model, engine_verdict, engine_value, engine_max_bid,
                          actual_sale_price, corrected_value, corrected_max_bid, verdict_correct, notes
                   FROM listing_feedback WHERE UPPER(make) = %s
                   ORDER BY (UPPER(COALESCE(model,'')) = %s) DESC, updated_at DESC LIMIT %s""",
        (make, model, limit),
    )
    rows = cur.fetchall()
    cur.close()
    lines = []
    for r in rows:
        parts = []
        if r.get("engine_verdict") or r.get("engine_max_bid") is not None:
            parts.append(
                f"engine said {r.get('engine_verdict')} max-bid "
                f"${(r.get('engine_max_bid') or 0) / 100:,.0f} (value ${(r.get('engine_value') or 0) / 100:,.0f})"
            )
        if r.get("actual_sale_price"):
            parts.append(f"ACTUALLY sold ${r['actual_sale_price'] / 100:,.0f}")
        if r.get("corrected_value"):
            parts.append(f"true value ${r['corrected_value'] / 100:,.0f}")
        if r.get("corrected_max_bid") is not None:
            parts.append(f"correct max-bid ${r['corrected_max_bid'] / 100:,.0f}")
        if r.get("verdict_correct") is False:
            parts.append("verdict was WRONG")
        line = f"- {r.get('year')} {r.get('make')} {r.get('model')}: " + "; ".join(
            parts
        )
        if r.get("notes"):
            line += f". Lesson: {r['notes']}"
        lines.append(line)
    return lines


def _to_design(
    contract,
    vehicle,
    raw,
    sold_pool,
    decl,
    va,
    scrutiny,
    anchor,
    source,
    ch,
    me,
    prof_advice,
    repair_alternatives,
    carfax,
    ai,
    ai_mode,
    meta,
    profile,
    ai_error,
    feedback=None,
    vmr=None,
    overrides=None,
    ad=None,
) -> dict:
    mode_b = prof_advice.get("mode") == "B"
    value_basis = "after-fix retail" if mode_b else "as-is retail"

    # headline numbers + narrative
    conditional = None
    adjustments = divergence = reasoning = None
    tools_used = []
    if ai:
        verdict = _norm_verdict(ai.get("verdict"))
        value = ai.get("value") or 0
        max_bid = ai.get("max_bid") or 0
        conf = ai.get("confidence") or "low"
        cond = ai.get("conditional_bid") or {}
        if cond.get("amount"):
            conditional = {
                "amount": cond["amount"],
                "condition": cond.get("condition", ""),
            }
        if ai.get("_mode") == "triage":
            summary = ai.get("summary") or prof_advice["thesis"]
            top_flags = ai.get("top_flags") or _topflags(decl)
        else:
            reasoning = ai.get("reasoning")
            summary = _first_sentences(reasoning) or prof_advice["thesis"]
            top_flags = _topflags(decl)
            adjustments = ai.get("key_adjustments") or None
            divergence = ai.get("divergence_from_rules")
            tools_used = ai.get("_tools_used") or []
    else:
        verdict = _norm_verdict(prof_advice["verdict"])
        max_bid = round(prof_advice["max_bid_cents"] / 100)
        value = round(prof_advice["expected_sale_cents"] / 100)
        conf = (scrutiny or {}).get("confidence", "low")
        summary = prof_advice["thesis"]
        top_flags = _topflags(decl)

    margin = _margin(ADV_PROFILES[profile], value)
    # Fee/tax must follow the PURCHASE CONTEXT (advisor already decided it): auction → Regal
    # buyer fee + GST; private/dealer (off-auction, the Appraise tab) → NO auction fee, tax at
    # the jurisdiction rate. (Previously _fee_gst was applied unconditionally, so off-auction
    # appraisals wrongly showed an auction fee.)
    ctx = prof_advice.get("context") or {}
    if ctx.get("auction_fee", True):
        buyer_fee, gst = _fee_gst(max_bid)  # auction: settings-aware Regal fee + GST
    else:
        buyer_fee = 0
        gst = round((max_bid or 0) * ctx.get("tax_rate", 0.0))
    rules = {
        "charles": {
            "verdict": _norm_verdict(ch["verdict"]),
            "maxBid": round(ch["max_bid_cents"] / 100),
            "margin": _margin(ADV_PROFILES["charles"], ch["expected_sale_cents"] / 100),
            "fee": 0,
        },
        "mechanic": {
            "verdict": _norm_verdict(me["verdict"]),
            "maxBid": round(me["max_bid_cents"] / 100),
            "margin": _margin(
                ADV_PROFILES["mechanic"], me["expected_sale_cents"] / 100
            ),
            "fee": 0,
        },
    }
    if divergence is None:
        divergence = (
            (
                f"AI ${max_bid:,} vs rules ${rules['charles']['maxBid']:,} "
                f"(charles) / ${rules['mechanic']['maxBid']:,} (mechanic)"
            )
            if ai
            else f"charles ${rules['charles']['maxBid']:,} · mechanic ${rules['mechanic']['maxBid']:,}"
        )

    # sale plan: prefer the AI's richer plan when present
    if ai and ai.get("sale_plan"):
        sp = ai["sale_plan"]
        sale = {
            "channel": sp.get("channel", ""),
            "list": sp.get("list_price", 0),
            "floor": sp.get("floor_price", 0),
            "days": sp.get("days_to_sell", "—"),
        }
    else:
        sp = prof_advice.get("sale_plan", {})
        sale = {
            "channel": sp.get("channel", ""),
            "list": round(sp.get("list_price_cents", 0) / 100),
            "floor": round(sp.get("floor_price_cents", 0) / 100),
            "days": "—",
        }

    recon = (
        ai.get("recon_plan") if ai and ai.get("recon_plan") else None
    ) or _recon_from_advice(prof_advice)
    verify = (
        (ai.get("verify_before_bid") if ai and ai.get("verify_before_bid") else None)
        or decl.get("verify_before_bid")
        or []
    )

    lot, lot_num = _lot_of(raw)
    ph = _photo_fields(raw)
    comps_design = _comps_to_design(scrutiny, anchor, source)
    if ai:
        needs_deep, deep_reason = bool(ai.get("needs_deep_dive")), None
    else:
        needs_deep, deep_reason = _deep_recommended(vehicle, scrutiny, comps_design)
    ad = ad or {}
    asking = round((ad.get("asking_price") or 0) / 100) or None
    deal_label = None
    if asking and max_bid:  # off-auction: is the ad priced below your max buy?
        deal_label = (
            "at/under your max buy" if asking <= max_bid else "above your max buy"
        )
    v = {
        "contract": str(contract) if contract else None,
        "lot": lot,
        "lotNum": lot_num,
        "source": ad.get(
            "source"
        ),  # None for Regal; 'facebook'/'kijiji'/'autotrader'/'dealer'/'manual'/'vin'
        "adUrl": ad.get("url"),
        "askingPrice": asking,
        "dealLabel": deal_label,
        "purchaseCtx": prof_advice.get("context"),
        "photo": ph["photo"],
        "photos": ph["photos"],
        "year": vehicle.get("year"),
        "make": (vehicle.get("make") or "").upper(),
        "model": (vehicle.get("model") or "").upper(),
        "trim": vehicle.get("trim") or "",
        "cab": vehicle.get("cab"),
        "bed": vehicle.get("bed"),
        "driveline": vehicle.get("driveline") or "—",
        "type": vehicle.get("vehicle_type") or "Vehicle",
        "km": vehicle.get("odometer_km") or 0,
        "vin": vehicle.get("vin") or "",
        "vinFilled": vehicle.get("_vin_filled")
        or [],  # spec fields filled from the VIN decode
        "vinDecoded": vehicle.get("_vin_decoded") or None,
        "color": vehicle.get("color") or "—",
        "engine": vehicle.get("engine") or "—",
        "trans": vehicle.get("transmission") or "—",
        "seller": vehicle.get("seller_type") or "—",
        "reserve": round((raw.get("reserve_price") or 0) / 100) or None,
        "auctionDate": str(raw.get("auction_date")) if raw.get("auction_date") else "—",
        "regalUrl": (REGAL_DETAIL_URL + str(contract)) if contract else None,
        "carfaxUrl": _carfax_url(raw),
        "needsDeep": needs_deep,
        "deepReason": deep_reason,
        "verdict": verdict,
        "value": value,
        "maxBid": max_bid,
        "conf": conf,
        "engineMode": (
            ai.get("_mode") if ai else "rules"
        ),  # which engine produced this call (for the Correct tab → calibration)
        "valueBasis": value_basis,
        "margin": margin,
        "buyerFee": buyer_fee,
        "gst": gst,
        "summary": summary,
        "topFlags": top_flags,
        "conditional": conditional,
        "reasoning": reasoning,
        "adjustments": adjustments,
        "toolsUsed": tools_used,
        "rules": rules,
        "divergence": divergence,
        "decl": _decl_to_design(decl, vehicle.get("declarations")),
        "comps": comps_design,
        "vision": _vision_to_design(va),
        "repair": _repair_to_design(repair_alternatives),
        "recon": recon,
        "sale": sale,
        "verify": verify,
        "carfax": _carfax_to_design(carfax),
        "pastSales": _pastsales_to_design(sold_pool),
        "feedback": feedback,
        "vmr": vmr,
        "inputs": {
            "trim": vehicle.get("trim") or "",
            "cab": vehicle.get("cab") or "",
            "bed": vehicle.get("bed") or "",
            "driveline": vehicle.get("driveline") or "",
            "engine": vehicle.get("engine") or "",
            "km": vehicle.get("odometer_km") or "",
            "exterior_grade": vehicle.get("exterior_grade"),
            "interior_grade": vehicle.get("interior_grade"),
            "mechanical_grade": vehicle.get("mechanical_grade"),
            "declarations": vehicle.get("declarations") or "",
            "condition_notes": vehicle.get("condition_notes") or "",
        },
        "overridden": sorted((overrides or {}).keys()),
        "meta": meta,
    }
    if ai_error:
        v["aiError"] = ai_error
    return v


def _first_sentences(text: str, n: int = 2) -> str | None:
    if not text:
        return None
    parts = text.replace("\n", " ").split(". ")
    out = ". ".join(parts[:n]).strip()
    if out and not out.endswith("."):
        out += "."
    return out or None


# ── The Lane, structured by Regal sale ────────────────────────────────────────

_SALE_COLS = """contract, auction_date, year, make, model, trim, driveline, color,
    engine, transmission, vehicle_type, odometer_km, vin, reserve_price,
    seller_type, declarations, condition_notes, raw_json, main_photo_url, photo_urls"""


def _sale_query(conn, where: str, params: tuple) -> list:
    cur = get_cursor(conn)
    cur.execute(
        f"SELECT DISTINCT ON (contract) {_SALE_COLS} FROM regal_listings "
        f"WHERE contract IS NOT NULL AND {where} "
        f"ORDER BY contract, last_updated_at DESC",
        params,
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def _lite_row(row: dict) -> dict:
    """An un-scored lane row — identity + lot + declarations, no engine run."""
    decl = analyze_declarations(
        row.get("declarations") or "", row.get("condition_notes") or ""
    )
    lot, lot_num = _lot_of(row)
    contract = str(row.get("contract"))
    ph = _photo_fields(row)
    pv = parse_listing_to_vehicle(row)  # recovers trim/cab/bed/engine from raw_json
    return {
        "contract": contract,
        "lot": lot,
        "lotNum": lot_num,
        "photo": ph["photo"],
        "photos": ph["photos"],
        "year": row.get("year"),
        "make": (row.get("make") or "").upper(),
        "model": (row.get("model") or "").upper(),
        "trim": pv.get("trim") or "",
        "cab": pv.get("cab"),
        "bed": pv.get("bed"),
        "driveline": pv.get("driveline") or "—",
        "type": row.get("vehicle_type") or "Vehicle",
        "km": row.get("odometer_km") or 0,
        "vin": row.get("vin") or "",
        "color": row.get("color") or "—",
        "engine": pv.get("engine") or "—",
        "trans": row.get("transmission") or "—",
        "seller": row.get("seller_type") or "—",
        "reserve": round((row.get("reserve_price") or 0) / 100) or None,
        "auctionDate": (
            row["auction_date"].isoformat() if row.get("auction_date") else "—"
        ),
        "regalUrl": REGAL_DETAIL_URL + contract,
        "carfaxUrl": _carfax_url(row),
        "decl": _decl_to_design(decl, row.get("declarations")),
        "verdict": None,
        "value": None,
        "maxBid": None,
        "conf": None,
        "conditional": None,
        "needsDeep": False,
        "scored": False,
    }


def sales(conn) -> list:
    """Index of upcoming Tuesday Timed Auctions + Saturday Super Sales (soonest first)."""
    rows = _sale_query(conn, "auction_date >= %s", (date.today(),))
    counts: dict = {}
    for r in rows:
        ad = r.get("auction_date")
        if ad and ad.weekday() in _SALE_LABELS:
            counts[ad] = counts.get(ad, 0) + 1
    return [
        {
            "date": ad.isoformat(),
            "day": _DAY_ABBR[ad.weekday()],
            "label": _SALE_LABELS[ad.weekday()],
            "count": counts[ad],
        }
        for ad in sorted(counts)
    ]


def sale_vehicles(
    conn, date_str: str, *, screen_limit: int = 60, profile: str = "charles"
) -> dict | None:
    """All vehicles in one sale, ordered by lot. The first `screen_limit` (by lot)
    are scored with the deterministic engine (cached); the rest come back un-scored
    and are evaluated on demand when opened."""
    try:
        d = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
    if d.weekday() not in _SALE_LABELS:
        return None
    rows = [
        r
        for r in _sale_query(conn, "auction_date = %s", (d,))
        if r.get("auction_date") and r["auction_date"].weekday() in _SALE_LABELS
    ]
    rows.sort(key=lambda r: _lot_of(r)[1])

    deep_ready = deep_cached_contracts(conn, [r.get("contract") for r in rows], profile)
    vehicles, screened = [], 0
    for i, r in enumerate(rows):
        c = str(r.get("contract"))
        if i < screen_limit:
            v = _DET_CACHE.get((c, profile))
            if v is None:
                try:
                    v = evaluate(conn, c, profile=profile, ai_mode=None)
                except Exception as e:  # noqa: BLE001
                    print(f"[sale] skip {c}: {e}")
                    v = None
            if v:
                vehicles.append({**v, "scored": True, "deepReady": c in deep_ready})
                screened += 1
                continue
        vehicles.append({**_lite_row(r), "deepReady": c in deep_ready})
    return {
        "date": d.isoformat(),
        "day": _DAY_ABBR[d.weekday()],
        "label": _SALE_LABELS[d.weekday()],
        "count": len(rows),
        "screened": screened,
        "vehicles": vehicles,
    }
