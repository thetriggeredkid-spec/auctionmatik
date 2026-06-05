"""
Declarations & Remarks Analyzer
Decodes Regal declaration codes and parses the auctioneer remarks / condition
notes into structured signals. This is a DATA layer — it doesn't price anything
itself; the router, repair model, history factor, and the Recommendation Engine
all consume its output.

Output (analyze_declarations):
{
    "codes":            [{code, label, meaning}],
    "route_salvage":    bool,            # frame damage / salvage / non-repairable
    "rebuilt":          bool,            # RS — rebuilt title (title factor applies)
    "out_of_province":  bool,            # OOP* — needs OPI before registration
    "unreserved":       bool,            # UNX — seller motivation signal
    "finance_repo":     bool,            # motivated seller
    "claims_total_low": int | None,      # CH#### lower bound (cumulative claims $)
    "mechanical_risk":  bool,            # MP or remark keywords
    "remark_signals":   [str],           # exhaust_leak, repaint, check_engine, ...
    "verify_before_bid":[str],           # actionable pre-bid checks (for the Advisor)
    "flags":            [{code, severity, message}],
}

Code reference: regal-declaration-codes memory + https://regalauctions.com/auctioninfo/vocabulary
"""

import re

# Declaration codes — matched by prefix so variants like OOPBC resolve to OOP.
# (code_prefix, label, meaning)
DECLARATION_CODES = [
    ("OOP",   "Out of Province",   "Last registered outside Alberta — needs an OPI before it can be registered."),
    ("FD",    "Frame Damage",      "Frame is damaged and requires repair."),
    ("HD",    "Hail Damage",       "Hail dents — severity ranges from barely visible to noticeable; "
                                   "cosmetic (PDR), NOT structural. Real impact depends on a close photo read."),
    ("RS",    "Rebuilt Status",    "Rebuilt from salvage — rebuilt title."),
    ("SALV",  "Salvage Status",    "Flagged a total loss."),
    ("NR",    "Non-Repairable",    "Cannot be registered or driven — parts only."),
    ("MP",    "Mechanical Problem","Known mechanical problem (often unspecified)."),
    ("FR",    "Finance Repo",      "Seized/surrendered to creditor. At Regal these are SAME-DAY / quick "
                                   "release — a motivated-seller (buy-side) signal, NOT a hold-time or "
                                   "days-on-market burden. Do NOT lower the vehicle's value for it."),
    ("TI",    "Dealer Trade-In",   "Dealer trade-in being remarketed — routine seller context, "
                                   "NOT a defect, damage, or risk signal."),
    ("UNX",   "Unreserved",        "No reserve — sells to the highest bid."),
    ("TMU",   "True Mileage Unknown", "Odometer accuracy cannot be verified."),
    ("OOC",   "Out of Country",    "Not previously registered in Canada."),
    ("AA",    "Auctioneer Announcement", "A specific auctioneer announcement applies — the real issue "
                                   "is in the CONDITION-REPORT REMARKS for this lot. Read them; it can be "
                                   "significant (e.g. freezing damage, mechanical, structural)."),
]

# Remark keyword patterns → signal tag. Parsed from condition_notes / description.
REMARK_PATTERNS = [
    (r"exhaust.*(leak|nois)",                 "exhaust_leak"),
    (r"\b(repaint|re-?paint(ed)?)\b",         "repaint"),
    (r"panel.*repaint|repaint.*panel",        "repaint"),
    (r"check\s*engine|\bcel\b|engine light",  "check_engine"),
    (r"airbag light|\bsrs\b light|airbag.{0,15}\bon\b", "airbag_light"),
    (r"different colou?r|mismatched paint|repainted|different shade", "repaint"),
    (r"mechanical (problem|issue)",           "mechanical_unspecified"),
    (r"\bframe\b",                            "frame"),
    (r"\bflood",                              "flood"),
    (r"\brust|paint bubbl",                   "rust"),
    (r"\bhail\b|hail damage|dimpl",           "hail"),
    (r"front end damage|front-end|collision|\btow\b", "collision"),
    (r"does not (start|run)|no start|not drivable", "not_drivable"),
    (r"salvage|write.?off|total loss",        "salvage"),
    (r"\bfreez(e|ing)\b|\bfrozen\b|freeze damage", "freezing_damage"),
]

# Signals that imply a mechanical-risk reserve even without a quote.
_MECHANICAL_SIGNALS = {"exhaust_leak", "check_engine", "mechanical_unspecified", "not_drivable",
                       "freezing_damage", "airbag_light"}


def _is_claims_code(code: str) -> bool:
    """True for a CH#### claims-total code (e.g. 'CH15000')."""
    return code.startswith("CH") and re.search(r"\d", code) is not None


def _claims_amount(code: str) -> int:
    """Extract the dollar lower-bound from a CH#### code ('CH15000' -> 15000)."""
    return int(re.sub(r"\D", "", code))


def _parse_codes(declarations: str) -> list[dict]:
    """Split a declaration string ('MP;OOPBC' / 'CH15000' / 'FD;RS;UNX') into known codes."""
    if not declarations:
        return []
    # Codes are separated by ';', ',' or '/'; normalise to upper-case tokens.
    tokens = [t.strip().upper() for t in re.split(r"[;,/]", declarations) if t.strip()]
    decoded = []
    for token in tokens:
        if _is_claims_code(token):
            amount = _claims_amount(token)
            decoded.append({"code": token, "label": "Claims Total",
                            "meaning": f"Cumulative insurance claims history (band starting ${amount:,})."})
            continue
        # Match by prefix so variants (e.g. OOPBC) resolve to their base code (OOP).
        match = next((c for c in DECLARATION_CODES if token.startswith(c[0])), None)
        if match:
            decoded.append({"code": token, "label": match[1], "meaning": match[2]})
        else:
            decoded.append({"code": token, "label": "Unrecognized code",
                            "meaning": f"'{token}' isn't in the declaration dictionary yet — verify it on the listing."})
    return decoded


def _parse_remarks(notes: str) -> list[str]:
    """Scan free-text condition notes for known keyword patterns, returning unique signal tags."""
    if not notes:
        return []
    text = notes.lower()
    signals = []
    for pattern, tag in REMARK_PATTERNS:
        if re.search(pattern, text) and tag not in signals:
            signals.append(tag)
    return signals


def analyze_declarations(declarations: str = "", condition_notes: str = "") -> dict:
    """Decode declaration codes and condition remarks into structured risk signals.

    See the module docstring for the full shape of the returned dict.
    """
    codes = _parse_codes(declarations)
    signals = _parse_remarks(condition_notes)

    def has(prefix):
        """True if any decoded code starts with `prefix` (prefix-match, like _parse_codes)."""
        return any(c["code"].startswith(prefix) for c in codes)

    # Lower bound of the cumulative claims band. If multiple CH#### codes appear,
    # the last one wins (matches the original scan order).
    claims_amounts = [_claims_amount(c["code"]) for c in codes if _is_claims_code(c["code"])]
    claims_low = claims_amounts[-1] if claims_amounts else None

    route_salvage = has("FD") or has("SALV") or has("NR") or "frame" in signals or "flood" in signals or "salvage" in signals
    rebuilt = has("RS")
    oop = has("OOP")
    mechanical_risk = has("MP") or bool(_MECHANICAL_SIGNALS & set(signals))

    flags = []
    verify = []

    if route_salvage:
        flags.append({"code": "salvage_route", "severity": "high",
                      "message": "Frame/salvage/flood declared or seen — value via repair-project (Mode B), not retail."})
        verify.append("Get a real body-shop repair quote (parts + labour) before bidding.")
    if rebuilt:
        flags.append({"code": "rebuilt_title", "severity": "high",
                      "message": "Rebuilt status — apply title factor (~0.75–0.80) to after-fix value; narrows buyer pool."})
    if oop:
        flags.append({"code": "out_of_province", "severity": "medium",
                      "message": "Out of province — buyer pays OPI before registration; adds cost + friction."})
        verify.append("Budget the OPI (out-of-province inspection) cost + any fixes it forces.")
    if has("MP") or "mechanical_unspecified" in signals:
        flags.append({"code": "mechanical_problem", "severity": "high",
                      "message": "Declared/stated mechanical problem — often unspecified. Carries a repair reserve."})
        verify.append("Diagnose the mechanical issue (scan codes, inspect) — unspecified MP is the biggest risk.")
    if "exhaust_leak" in signals:
        verify.append("Confirm exhaust leak scope (gasket vs. manifold vs. full system).")
    if "check_engine" in signals:
        verify.append("Pull CEL codes — could be trivial or a major driveability fault.")
    if "airbag_light" in signals:
        flags.append({"code": "airbag_light", "severity": "high",
                      "message": "Airbag/SRS light on — possible deployed/disconnected airbag or fault; safety + repair cost. Verify."})
        verify.append("Scan the SRS/airbag system — light-on can mean a prior deployment or a sensor fault.")
    if "repaint" in signals:
        flags.append({"code": "prior_repaint", "severity": "low",
                      "message": "Repaint / mismatched panel — prior bodywork or a replacement panel needing paint-match; check for hidden damage."})
    if has("HD") or "hail" in signals:
        flags.append({"code": "hail_damage", "severity": "low",
                      "message": "Hail damage declared — cosmetic (PDR), not structural. Severity is "
                                 "photo-dependent (near-invisible to a real presentation hit); budget PDR by dent count."})
        verify.append("Inspect photos closely for hail dent count/severity — PDR cost scales with it "
                      "(use the stronger Sonnet vision pass if the dents are hard to read).")
    if claims_low is not None:
        sev = "high" if claims_low >= 10000 else "medium" if claims_low >= 3000 else "low"
        flags.append({"code": "claims_history", "severity": sev,
                      "message": f"Cumulative claims history from ${claims_low:,}. Cumulative ≠ single near-total-loss — "
                                 f"check Carfax for whether it's one big hit or many small ones."})
        verify.append("Review Carfax to see if claims are one structural hit or many minor claims.")
    if has("UNX"):
        flags.append({"code": "unreserved", "severity": "low",
                      "message": "Unreserved — no floor price; seller is motivated."})
    if has("AA"):
        flags.append({"code": "auctioneer_announcement", "severity": "medium",
                      "message": "Auctioneer announcement on this lot — the real issue is in the condition-report "
                                 "REMARKS. Read them; it can be significant. Don't bid until you know what it is."})
        verify.append("Read the auctioneer announcement / condition-report remarks — that's where the actual issue is.")
    if "freezing_damage" in signals:
        flags.append({"code": "freezing_damage", "severity": "high",
                      "message": "Freezing/frost damage stated — can mean burst cooling / cracked block (car) or split "
                                 "plumbing, tanks, lines (RV/trailer). Often expensive and easy to miss; verify scope."})
        verify.append("Inspect freezing-damage scope (cooling system / engine / plumbing / tanks) — potentially major.")

    return {
        "codes": codes,
        "route_salvage": route_salvage,
        "rebuilt": rebuilt,
        "out_of_province": oop,
        "hail": has("HD") or "hail" in signals,
        "unreserved": has("UNX"),
        "finance_repo": has("FR"),
        "claims_total_low": claims_low,
        "mechanical_risk": mechanical_risk,
        "remark_signals": signals,
        "verify_before_bid": verify,
        "flags": flags,
    }
