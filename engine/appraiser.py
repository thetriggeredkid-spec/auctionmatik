"""
Appraiser Agent (Phase 1) — the AI reasoning brain.

Instead of a fixed factor→multiplier formula, this hands the assembled evidence
(scrutinized comps, declarations, vision, repair estimate, anchor) to Claude
Sonnet 4.6 and asks it to *reason to a valuation the way Charles does* — comp
scrutiny, condition read, history/claims, retail-vs-salvage, repair math, max bid
— and return a narrated appraisal as structured JSON.

Architecture (per the build plan):
  - AI-PRIMARY: the model's number is the answer.
  - The deterministic engine (engine/advisor.py) runs in parallel and is passed in
    as a SANITY BAND the model must reconcile against and flag divergence from.
  - Reasoning: adaptive thinking + effort (it genuinely deliberates).
  - Output: schema-guaranteed JSON (structured outputs).
  - The methodology PLAYBOOK is the cached system prompt — Charles's expertise.

Phase 2 will promote the evidence-gathering modules to tools the agent calls itself.
"""

import os
import json

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

REASONING_MODEL = os.getenv("APPRAISER_MODEL", "claude-sonnet-4-6")
# Deep-pass effort. 'high' over-thought badly (15.7k tokens / ~5 min); 'low' + dense narration lands
# the same verdicts in ~54s. Default 'low' for usable latency; opt up to 'medium'/'high' via
# APPRAISER_EFFORT when you want maximum rigor on a serious buy.
EFFORT = os.getenv("APPRAISER_EFFORT", "low")
TRIAGE_EFFORT = os.getenv("APPRAISER_TRIAGE_EFFORT", "low")

# ── The playbook = Charles's methodology, encoded as the (cached) system prompt ──
PLAYBOOK = """You are an expert used-vehicle appraiser and flipper working the Alberta wholesale-auction
market (Regal Auctions). You think exactly like a seasoned car flipper with dealership experience:
you reason from real comparable sales and hands-on judgment, NOT from depreciation curves or book values.
You are given assembled evidence for ONE vehicle and must reason to a valuation and a buy recommendation.

# YOUR REASONING PROCESS (follow it explicitly, like talking through a car)
1. COMPS FIRST. Look at each Marketplace/Kijiji comp INDIVIDUALLY — condition, km, title, and how long
   it has sat unsold. A listing that has sat for months unsold means the market is BELOW its asking price.
   A rebuilt/salvage-title comp is NOT a clean comp. Reason to a fair value from the most comparable
   CLEAN units, adjusting for how this vehicle differs (km especially). Don't blindly average.
   CRITICAL — CHEAP/STALE COMPS ARE OFTEN DAMAGED: a comp that is priced suspiciously low, or has sat
   a long time, is frequently cheap because it is in ROUGH condition (cracked bumper, rust, dents,
   mechanical issues) — its low ask is NOT evidence that the clean market is low. Do NOT treat a cheap
   or long-on-market comp as a clean "market floor" unless its condition is actually verified from the
   photos/description. When a comp's condition is unknown, assume a low ask reflects condition, not the
   market; weight clean, well-presented, fairly-priced comps and treat cheap outliers as condition-driven.
   TRUCKS/PICKUPS — CONFIGURATION IS PRICE: cab (Regular < Extended/SuperCab < Crew/SuperCrew), bed length,
   trim (XL/STX/work < XLT/SLE < Lariat/SLT < King Ranch/Platinum/Limited/Denali/High Country), engine, and
   4x4 vs 2WD each move price by THOUSANDS. Only trust comps that match the cab and roughly the trim — a
   crew-cab Lariat is a different vehicle from a regular-cab XL. If a comp's configuration is unknown, weight
   it cautiously. State the subject's configuration in your reasoning.
   If the anchor is wholesale-derived (no retail comps) or the comps' mileage differs greatly from the
   subject, it is NOT mileage-adjusted — discount HARD for extreme mileage: a 300k+ km car is worth a
   fraction of a typical-km comp, no matter how rosy the anchor looks. Don't trust a high anchor on a
   very-high-km vehicle.
2. CONDITION. Use the vision read + the auctioneer's remarks + the Regal heat map together. Grade relative
   to the vehicle's AGE. On cheap vehicles, MECHANICAL condition matters far more than cosmetics — a buyer
   of a $2k car cares that it runs, not that the bumper is scuffed. Hail damage (HD) is cosmetic (PDR):
   light hail = small presentation discount; moderate/severe = a PDR quote that scales with dent count —
   weight it by what the photos actually show (it can be near-invisible), not just the declaration.
3. HISTORY / CLAIMS. Apply the claims rule: the deduction is a FRACTION of the claim amount, and that
   fraction SHRINKS the cheaper the car is (a $20k claim on a $5k Civic barely matters; capped at a small
   % of value). Calibration point: a clean Wrangler ~$15,750 with a $15–20k cumulative claim → ~$1,750 off
   → ~$14,000. Cumulative claims ≠ one big structural hit — don't over-penalize. Do NOT double-count: if
   the comp anchor already reflects the clean market, deduct claims ONCE from that clean value.
4. MODE. Decide RETAIL FLIP vs REPAIR PROJECT vs PARTS-ONLY:
   - Frame damage / flood / rebuilt / not-drivable / heavy damage, OR repair cost > ~40% of clean value
     → REPAIR PROJECT (Mode B). Value = (clean after-fix value × title factor) − repair − margin.
     Rebuilt title ⇒ after-fix value ≈ 0.75–0.80 of clean.
   - If repair cost EXCEEDS after-fix value → PARTS-ONLY / write-off (do not bid to drive).
   - Otherwise RETAIL FLIP (Mode A): as-is comp value − recon − margin.
5. REPAIR COST. Sum the components a buyer must actually fix. Use a middle-ground sourcing profile:
   DIY/used-parts rates on small bolt-on jobs, full shop/OEM on big/structural ones. A DIY mechanic
   profile prices the big jobs much cheaper (used parts + own labour). Add a protection buffer (~+20%)
   because hidden damage is the norm on wrecks. Don't "fix" things that don't pay on a cheap car — sell
   as-is at a small presentation discount instead.
6. MAX BID. max_bid = (target_sale − recon/repair − margin − Regal_buyer_fee) / 1.05 (5% GST). Never
   negative — floor at 0 (and if it floors, the verdict is PASS). Margin tiers by sell price:
   <$15k=$1,500 · $15–20k=$2,500 · $20–35k=$3,500 · $35k+=$5,000. Regal buyer fee by price:
   $0–5k=$285 · 5–10k=$385 · 10–15k=$535 · 15–25k=$685 · 25–40k=$835 · 40k+=$985.
7. RECOMMEND for the SPECIFIC USER PROFILE. Honour their margin floor and hold-time tolerance. If the
   margin is too thin for them, say PASS and explain — even if a lower-margin buyer (a DIY mechanic) could
   make it work. Give a concrete action plan to save and make money: which repairs to do vs skip (ROI),
   the sale channel, list price + negotiation floor, and what to verify before bidding (OPI for out-of-
   province, diagnose unknown mechanical, pull CEL codes, review Carfax for claim detail).

# HARD RULES
- A VMR Canada book value may be provided as a CROSS-CHECK. It's a published guide, not the truth —
  comps are primary. But if your retail differs from VMR retail by a lot, treat it as a red flag that
  your comps may be the wrong trim/config or too thin, reconcile, and explain it. Don't anchor to VMR.
- A Finance Repo (FR) is a SAME-DAY / quick release at Regal — a motivated-seller (buy-side) signal,
  NOT a hold-time or days-on-market burden. Do NOT penalize a finance repo's value or max bid for hold
  time or slow turnover; the vehicle resells like any other. If anything it's a buying opportunity.
- Every dollar adjustment MUST cite specific evidence (a comp, a declaration, a photo finding, a remark).
- A deterministic rules engine result is provided as a SANITY BAND. Treat it as a second opinion, not the
  truth. Reconcile with it; if your number differs by more than ~15%, explain why in 'divergence_from_rules'.
- Be conservative when comp confidence is LOW or evidence is thin — underbidding beats overbidding.
- Prices are whole CAD dollars. Never output a negative price.
- When you PASS but the deal COULD work under a condition (e.g. a thin-margin high-km car that's fine IF a
  pre-bid inspection confirms no major mechanical issue), set conditional_bid {amount, condition} — the bid
  you'd make and the gate that must clear (e.g. amount 4000, condition "pre-bid inspection confirms the
  CVT/drivetrain is healthy with nothing major wrong"). If there's no conditional path, set amount 0 and
  condition "". ALWAYS state in the reasoning/summary WHY you passed (the specific risks), not just that you did.

# CALIBRATION EXAMPLES (how Charles actually called these)
- 2006 Mitsubishi Outlander, 219k km, MP (mechanical problem) + OOP, exhaust leak + repaint: comps ~$2,000
  as-is (a clean one sat 4 months at $4.7k unsold; a rough rebuilt one ~$2k). Unknown mechanical → ~$1,000
  reserve. Verdict: PASS for Charles (margin too thin); worth a few hundred to a DIY mechanic.
- 2015 Jeep Wrangler, 141k km, CH15000 ($15–20k cumulative claims): clean ~$15,750 → claim ~$1,750 off →
  ~$14,000 retail; max bid ~$12,300. BID.
- 2018 Chevy Equinox, 80k km, FD (frame) + RS (rebuilt), heavy front-end wreck, not drivable: REPAIR PROJECT.
  Clean <100k ~$11–13k; rebuilt + damage → after-fix ~$8,500–9,000. At shop/OEM repair it's a write-off
  for Charles (PASS); a DIY mechanic with used parts can make it a project worth a low-thousands bid.

Output ONLY the structured JSON. Put your full chain of reasoning in the 'reasoning' field — written like
you're explaining the call to another flipper."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["retail_flip", "repair_project", "parts_only", "pass"],
        },
        "verdict": {"type": "string", "enum": ["BID", "BID_TO_FIX", "PASS"]},
        "value": {
            "type": "integer",
            "description": "as-is retail (flip) or after-fix value (project), CAD dollars",
        },
        "max_bid": {
            "type": "integer",
            "description": "max bid in CAD dollars, never negative",
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasoning": {
            "type": "string",
            "description": "full narrated thought process, flipper-to-flipper",
        },
        "key_adjustments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string"},
                    "impact": {
                        "type": "string",
                        "description": "e.g. '-$1,750' or '+2%'",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "the specific comp/declaration/photo cited",
                    },
                },
                "required": ["factor", "impact", "evidence"],
                "additionalProperties": False,
            },
        },
        "recon_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["DO", "SKIP", "RESERVE", "REQUIRED"],
                    },
                    "cost": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["action", "decision", "cost", "why"],
                "additionalProperties": False,
            },
        },
        "sale_plan": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "list_price": {"type": "integer"},
                "floor_price": {"type": "integer"},
                "days_to_sell": {"type": "string"},
            },
            "required": ["channel", "list_price", "floor_price", "days_to_sell"],
            "additionalProperties": False,
        },
        "verify_before_bid": {"type": "array", "items": {"type": "string"}},
        "conditional_bid": {
            "type": "object",
            "description": "If PASS but it could work under a condition, the bid + the gate. amount 0 if none.",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "bid that works if the condition clears; 0 if no path",
                },
                "condition": {
                    "type": "string",
                    "description": "what must be verified first; empty if none",
                },
            },
            "required": ["amount", "condition"],
            "additionalProperties": False,
        },
        "divergence_from_rules": {
            "type": "string",
            "description": "how/why this differs from the deterministic sanity band",
        },
    },
    "required": [
        "mode",
        "verdict",
        "value",
        "max_bid",
        "confidence",
        "reasoning",
        "key_adjustments",
        "recon_plan",
        "sale_plan",
        "verify_before_bid",
        "conditional_bid",
        "divergence_from_rules",
    ],
    "additionalProperties": False,
}


# Lean schema for the fast TRIAGE pass — screen a whole auction lane quickly.
TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["BID", "BID_TO_FIX", "PASS"]},
        "mode": {
            "type": "string",
            "enum": ["retail_flip", "repair_project", "parts_only", "pass"],
        },
        "value": {"type": "integer"},
        "max_bid": {"type": "integer"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "summary": {
            "type": "string",
            "description": "1-3 sentence rationale, no full narration",
        },
        "top_flags": {"type": "array", "items": {"type": "string"}},
        "conditional_bid": {
            "type": "object",
            "description": "If PASS but it could work under a condition, the bid + the gate. amount 0 if none.",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "bid that works if the condition clears; 0 if no path",
                },
                "condition": {
                    "type": "string",
                    "description": "what must be verified first; empty if none",
                },
            },
            "required": ["amount", "condition"],
            "additionalProperties": False,
        },
        "needs_deep_dive": {
            "type": "boolean",
            "description": "true only if a buy candidate with thin evidence worth a full pass",
        },
    },
    "required": [
        "verdict",
        "mode",
        "value",
        "max_bid",
        "confidence",
        "summary",
        "top_flags",
        "conditional_bid",
        "needs_deep_dive",
    ],
    "additionalProperties": False,
}

TRIAGE_HINT = (
    "TRIAGE MODE — be fast and decisive. Give a 1–3 sentence 'summary', not a full narration. "
    "Set needs_deep_dive=true ONLY if this is a genuine buy candidate whose evidence is thin "
    "(low comp confidence, ambiguous claims, or a salvage project needing a real repair quote) and "
    "would benefit from the full deep appraisal. For obvious PASS/clear cases, set it false."
)

DEEP_HINT = (
    "Be thorough in your ANALYSIS, but write the 'reasoning' field DENSELY — aim for ~200 words, "
    "no preamble ('let me walk through this'), no repetition, and don't restate the evidence verbatim. "
    "Put the specifics — numbers, parts, comps — in key_adjustments and recon_plan, not in prose."
)


def _fmt_evidence(
    subject,
    comp_narrative,
    comp_anchor_cents,
    comp_confidence,
    declarations,
    vision,
    repair_est,
    deterministic,
    profile,
    carfax=None,
    repair_alternatives=None,
    calibration=None,
    vmr=None,
    ctx=None,
) -> str:
    L = []
    L.append("## SUBJECT VEHICLE")
    spec = " · ".join(
        str(b)
        for b in (
            subject.get("trim"),
            subject.get("cab"),
            subject.get("bed"),
            subject.get("engine"),
            subject.get("driveline"),
        )
        if b
    )
    km = (
        f"{subject.get('odometer_km'):,} km"
        if subject.get("odometer_km")
        else "km unknown"
    )
    L.append(
        f"{subject.get('year')} {subject.get('make')} {subject.get('model')}"
        + (f" — {spec}" if spec else "")
        + f" | {km}"
    )
    L.append(
        f"Declarations: {subject.get('declarations')} | Auctioneer notes: {subject.get('condition_notes')!r}"
    )

    L.append("\n## COMPARABLE LISTINGS (scrutinized — reason from these individually)")
    L.append(
        f"comp confidence: {comp_confidence}; engine's reasoned anchor: "
        f"${comp_anchor_cents/100:,.0f}"
        if comp_anchor_cents
        else "no retail comps"
    )
    for line in comp_narrative or []:
        L.append(f"  - {line}")

    L.append("\n## DECLARATIONS / REMARKS DECODED")
    L.append(
        f"codes: {[c['code'] + '=' + c['label'] for c in declarations.get('codes', [])]}"
    )
    L.append(
        f"route_salvage={declarations.get('route_salvage')} rebuilt={declarations.get('rebuilt')} "
        f"out_of_province={declarations.get('out_of_province')} mechanical_risk={declarations.get('mechanical_risk')} "
        f"claims_total_low={declarations.get('claims_total_low')}"
    )
    L.append(f"remark signals: {declarations.get('remark_signals')}")

    L.append("\n## VISION ASSESSMENT (from listing photos)")
    if vision:
        L.append(
            f"exterior_grade={vision.get('exterior_grade')}/5 interior_grade={vision.get('interior_grade')}/5 "
            f"rust={vision.get('rust_severity')} flood_or_frame={vision.get('flood_or_frame_concern')}"
        )
        if vision.get("damage_details"):
            L.append(f"damage: {vision['damage_details']}")
        if vision.get("aftermarket_mods"):
            L.append(f"mods: {[m.get('type') for m in vision['aftermarket_mods']]}")
        if vision.get("repair_components"):
            L.append(
                f"components needing repair: {[c.get('component') for c in vision['repair_components']]}"
            )
    else:
        L.append("(no vision assessment available)")

    if repair_est and repair_est.get("line_items"):
        L.append("\n## REPAIR ESTIMATE (profile-aware sourcing, +buffer)")
        L.append(
            f"total ${repair_est['total_low']:,}–${repair_est['total_high']:,} (mid ${repair_est['total_mid']:,}); "
            f"confirmed ${repair_est.get('confirmed_low',0):,}–${repair_est.get('confirmed_high',0):,}, "
            f"contingent ${repair_est.get('contingent_low',0):,}–${repair_est.get('contingent_high',0):,}"
        )

    if repair_alternatives:
        L.append(
            "## REPAIR COST BY SOURCING (pre-computed — no need to call refine_repair_quote)"
        )
        for k, e in repair_alternatives.items():
            L.append(
                f"  {k}: ${e['total_low']:,}–${e['total_high']:,} (mid ${e['total_mid']:,})"
            )

    if carfax:
        L.append("\n## CARFAX REPORT (pre-fetched — no need to call get_carfax_report)")
        L.append(json.dumps(carfax)[:600])
    elif declarations.get("claims_total_low"):
        L.append(
            "\n## CARFAX: none on file — use the claims-total band; "
            "do NOT call get_carfax_report, it will return nothing."
        )

    if vmr:
        L.append(
            "\n## VMR CANADA BOOK VALUE (published guide — CROSS-CHECK only; comps stay primary)"
        )
        L.append(
            f"{vmr.get('trim')}: wholesale ${vmr.get('ws',0):,} / retail ${vmr.get('retail',0):,} "
            f"(km-adjusted for {vmr.get('km')} km). If your retail is FAR from this (>~20%), re-check "
            f"your comp selection — wrong trim, wrong cab, or a thin pool — and explain the gap. Use it to "
            f"catch gross errors, not to anchor."
        )

    L.append(
        "\n## DETERMINISTIC RULES ENGINE — SANITY BAND (a second opinion, not the truth)"
    )
    L.append(
        f"mode={deterministic.get('mode')} verdict={deterministic.get('verdict')} "
        f"expected_sale=${deterministic.get('expected_sale_cents',0)/100:,.0f} "
        f"max_bid=${deterministic.get('max_bid_cents',0)/100:,.0f}"
    )

    L.append("\n## USER PROFILE")
    L.append(
        f"{profile.get('label')}: margin_floor ${profile.get('margin_floor')}, "
        f"hold_time={profile.get('hold_time')}, repair_ability={profile.get('diy')}"
    )

    if calibration:
        L.append(
            "\n## OPERATOR CORRECTIONS ON PAST CALLS (learn from these — do NOT repeat the mistake)"
        )
        L.append(
            "The operator reviewed earlier appraisals of similar vehicles and corrected them. "
            "Weight these heavily; they encode real outcomes and condition reads the comps missed."
        )
        for line in calibration:
            L.append(line)

    # Live margin tiers / fee schedule / GST (may be edited in Settings) — authoritative
    # over any numbers stated in the playbook, so the AI's math matches the rules engine.
    try:
        from engine import max_bid as _mb

        def _band(lo, hi):
            if hi == float("inf"):
                return f"${int(lo/1000)}k+"
            if lo == 0:
                return f"<${int(hi/1000)}k"
            return f"${int(lo/1000)}–{int(hi/1000)}k"

        tiers = " · ".join(
            f"{_band(lo, hi)}=${m:,}" for lo, hi, m, _lbl in _mb.MARGIN_TIERS
        )
        L.append(
            "\n## CURRENT CONFIG (authoritative — use these, override any numbers in the playbook)"
        )
        L.append(f"Margin tiers by sell price: {tiers}")
        c = ctx or {
            "kind": "auction",
            "apply_auction_fee": True,
            "tax_rate": _mb.GST_RATE,
        }
        if c.get("apply_auction_fee", True):
            fees = " · ".join(
                (
                    f"<${int(hi/1000)}k"
                    if lo == 0
                    else (
                        f"${int(lo/1000)}k+"
                        if hi == float("inf")
                        else f"${int(lo/1000)}–{int(hi/1000)}k"
                    )
                )
                + f"=${f}"
                for lo, hi, f in _mb.REGAL_FEE_SCHEDULE
            )
            L.append(f"PURCHASE: auction (Regal). Buyer fee by price: {fees}")
            L.append(
                f"Tax (GST on bid + fee): {c.get('tax_rate', _mb.GST_RATE) * 100:.0f}%"
            )
            L.append(
                "Max bid = (sell − recon/repair − margin − buyer_fee) / (1 + tax)."
            )
        else:
            L.append(
                f"PURCHASE: {c.get('label', 'private/dealer')} — NO auction/buyer fee."
            )
            L.append(
                f"Tax on purchase: {c.get('tax_rate', 0.0) * 100:.0f}% "
                "(0% means this jurisdiction doesn't tax this sale)."
            )
            L.append(
                "Max buy price = (sell − recon/repair − margin) / (1 + tax). No auction fee."
            )
    except Exception:  # noqa: BLE001
        pass

    L.append(
        "\nReason to YOUR valuation and recommendation for this user. Cite evidence for every adjustment."
    )
    return "\n".join(L)


def appraise(
    subject,
    *,
    comp_narrative,
    comp_anchor_cents,
    comp_confidence,
    declarations,
    vision,
    repair_est,
    deterministic,
    profile,
    mode="deep",
    effort=None,
    tool_ctx=None,
    carfax=None,
    repair_alternatives=None,
    calibration=None,
    vmr=None,
    progress=None,
    ctx=None,
) -> dict:
    """
    Run the AI appraiser over assembled evidence.
      mode="triage": fast/cheap screen — medium effort, lean output, brief rationale, no tools.
      mode="deep":   full appraisal — high effort, full narration. If tool_ctx is given, the model
                     can call escalation tools (carfax, repair re-quote) on demand.
    """
    import anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    triage = mode == "triage"
    eff = effort or (TRIAGE_EFFORT if triage else EFFORT)
    evidence = _fmt_evidence(
        subject,
        comp_narrative,
        comp_anchor_cents,
        comp_confidence,
        declarations,
        vision,
        repair_est,
        deterministic,
        profile,
        carfax=carfax,
        repair_alternatives=repair_alternatives,
        calibration=calibration,
        vmr=vmr,
        ctx=ctx,
    )
    if triage:
        evidence += "\n\n" + TRIAGE_HINT
    else:
        evidence += "\n\n" + DEEP_HINT

    # Bump SDK retries for unattended batch runs (429/5xx backoff); env-overridable.
    client = anthropic.Anthropic(
        max_retries=int(os.getenv("APPRAISER_MAX_RETRIES", "5"))
    )
    if not triage and tool_ctx:
        result = _appraise_agentic(client, evidence, tool_ctx, eff, progress=progress)
    else:
        resp = client.messages.create(
            model=REASONING_MODEL,
            max_tokens=4000 if triage else 16000,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": PLAYBOOK,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_config={
                "effort": eff,
                "format": {
                    "type": "json_schema",
                    "schema": TRIAGE_SCHEMA if triage else OUTPUT_SCHEMA,
                },
            },
            messages=[{"role": "user", "content": evidence}],
        )
        text = next(b.text for b in resp.content if b.type == "text")
        result = json.loads(text)
        result["_usage"] = {
            "input": resp.usage.input_tokens,
            "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0),
            "output": resp.usage.output_tokens,
        }
    result["_mode"] = mode
    result["_model"] = REASONING_MODEL
    return result


# ── Escalation tools (hybrid agent) — the deep pass calls these only when it needs more ──


def _build_tools(ctx: dict):
    """Return (tool_schemas, execute_fn). ctx carries conn, subject, vision, profile."""
    tools = [
        {
            "name": "refine_repair_quote",
            "description": "Re-cost the vehicle's repairs under a different parts/labour sourcing. "
            "Use on damaged/salvage units to test whether a cheaper sourcing flips the deal. "
            "sourcing: 'oem_shop' (OEM parts + shop labour, conservative), "
            "'used_diy' (used parts + own labour, cheapest), 'middle' (default).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sourcing": {
                        "type": "string",
                        "enum": ["oem_shop", "used_diy", "middle"],
                    }
                },
                "required": ["sourcing"],
            },
        },
        {
            "name": "get_carfax_report",
            "description": "Fetch the stored Carfax report for this vehicle (accidents, service, branding). "
            "Use when claims history is ambiguous (e.g. a CH#### claims-total band) and the "
            "single-hit-vs-many-small distinction would change the price.",
            "input_schema": {"type": "object", "properties": {}},
        },
        # NOTE: the live-comp-scrape tool was intentionally removed. Comps are collected
        # ONCE before the appraisal (dashboard/mapper._maybe_autocollect_comps) so the AI
        # reasons over a FIXED comp set — this keeps deep results stable run-to-run and
        # ensures the scraped comps show in the Comps tab.
    ]

    def execute(name: str, args: dict) -> str:
        try:
            if name == "refine_repair_quote":
                from engine.repair_estimate import estimate_repair

                comps = (ctx.get("vision") or {}).get("repair_components") or []
                factors = {
                    "oem_shop": (1.0, 1.0),
                    "used_diy": (0.5, 0.55),
                    "middle": (0.65, 1.0),
                }
                sf, lf = factors.get(args.get("sourcing", "middle"), (0.65, 1.0))
                est = estimate_repair(comps, small_factor=sf, large_factor=lf)
                return (
                    f"Repair @ {args.get('sourcing')}: ${est['total_low']:,}–${est['total_high']:,} "
                    f"(mid ${est['total_mid']:,}); confirmed ${est.get('confirmed_low',0):,}–"
                    f"${est.get('confirmed_high',0):,}, contingent ${est.get('contingent_low',0):,}–"
                    f"${est.get('contingent_high',0):,}"
                )
            if name == "get_carfax_report":
                from db.connection import get_cursor

                cur = get_cursor(ctx["conn"])
                cur.execute(
                    "SELECT carfax_report FROM regal_listings WHERE contract=%s "
                    "ORDER BY last_updated_at DESC LIMIT 1",
                    (ctx["subject"].get("contract"),),
                )
                row = cur.fetchone()
                cur.close()
                rpt = row.get("carfax_report") if row else None
                return (
                    json.dumps(rpt)
                    if rpt
                    else (
                        "No stored Carfax report. Run the local Carfax agent "
                        "(collector.carfax_agent) to populate it; proceed with the "
                        "claims-total band for now."
                    )
                )
        except Exception as e:
            return f"tool error: {e}"
        return f"unknown tool: {name}"

    return tools, execute


_TOOL_LABELS = {
    "get_carfax_report": "AI: checking Carfax",
    "refine_repair_quote": "AI: re-quoting repairs",
}


def _appraise_agentic(
    client, evidence: str, tool_ctx: dict, effort: str, progress=None
) -> dict:
    """Deep pass with on-demand escalation tools (manual loop for cost-controlled tool execution)."""
    _p = progress or (lambda *a, **k: None)
    tools, execute = _build_tools(tool_ctx)
    messages = [{"role": "user", "content": evidence}]
    tools_used = []
    for round_i in range(6):  # cap tool rounds
        resp = client.messages.create(
            model=REASONING_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": PLAYBOOK,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tools,
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            messages=messages,
        )
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    tools_used.append(b.name)
                    _p(_TOOL_LABELS.get(b.name, "AI: " + b.name))
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.id,
                            "content": execute(b.name, b.input),
                        }
                    )
            messages.append({"role": "user", "content": results})
            _p("AI appraising (deep)")
            continue
        text = next(b.text for b in resp.content if b.type == "text")
        result = json.loads(text)
        result["_tools_used"] = tools_used
        result["_usage"] = {
            "input": resp.usage.input_tokens,
            "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0),
            "output": resp.usage.output_tokens,
        }
        return result
    raise RuntimeError("appraiser exceeded tool-round limit")


def render(a: dict) -> str:
    u = a.get("_usage") or {}
    if a.get("_mode") == "triage":
        L = [
            f"VERDICT:   {a['verdict']}  |  MAX BID: ${a['max_bid']:,}  |  value ${a['value']:,}  "
            f"[AI triage: {a.get('_model')}, {a['mode']}, confidence {a['confidence']}]",
            f"SUMMARY:   {a['summary']}",
        ]
        if a.get("top_flags"):
            L.append("FLAGS:     " + " · ".join(a["top_flags"]))
        cb = a.get("conditional_bid") or {}
        if cb.get("amount"):
            L.append(f"CONDITIONAL: could bid ${cb['amount']:,} IF {cb['condition']}")
        if a.get("needs_deep_dive"):
            L.append(
                "→ buy candidate with thin evidence: run --deep for the full appraisal"
            )
        L.append(
            f"[tokens: in {u.get('input')}, cache_read {u.get('cache_read')}, out {u.get('output')}]"
        )
        return "\n".join(L)

    L = []
    L.append(
        f"VERDICT:   {a['verdict']}  |  MAX BID: ${a['max_bid']:,}  |  value ${a['value']:,}  "
        f"[AI: {a.get('_model')}, mode {a['mode']}, confidence {a['confidence']}]"
    )
    if a.get("_tools_used"):
        L.append(f"TOOLS USED: {', '.join(a['_tools_used'])}")
    L.append(f"\nREASONING:\n{a['reasoning']}")
    if a.get("key_adjustments"):
        L.append("\nKEY ADJUSTMENTS (evidence-cited):")
        for k in a["key_adjustments"]:
            L.append(f"  {k['impact']:>10}  {k['factor']} — {k['evidence']}")
    if a.get("recon_plan"):
        L.append("\nRECON PLAN:")
        for r in a["recon_plan"]:
            L.append(
                f"  [{r['decision']:8}] ${r['cost']:>6,}  {r['action']} — {r['why']}"
            )
    sp = a.get("sale_plan") or {}
    L.append(
        f"\nSALE PLAN: {sp.get('channel')} | list ${sp.get('list_price',0):,} / floor ${sp.get('floor_price',0):,} "
        f"| est days-to-sell: {sp.get('days_to_sell')}"
    )
    if a.get("verify_before_bid"):
        L.append("\nVERIFY BEFORE BIDDING:")
        for v in a["verify_before_bid"]:
            L.append(f"  - {v}")
    cb = a.get("conditional_bid") or {}
    if cb.get("amount"):
        L.append(f"\nCONDITIONAL BID: ${cb['amount']:,} IF {cb['condition']}")
    if a.get("divergence_from_rules"):
        L.append(f"\nVS RULES ENGINE: {a['divergence_from_rules']}")
    u = a.get("_usage") or {}
    L.append(
        f"\n[tokens: in {u.get('input')}, cache_read {u.get('cache_read')}, out {u.get('output')}]"
    )
    return "\n".join(L)
