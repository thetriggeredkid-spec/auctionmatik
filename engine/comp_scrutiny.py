"""
Comp Scrutiny Engine
Replaces blind weighted-median comping with per-comp reasoning, the way Charles
actually appraises: look at each Marketplace/Kijiji listing individually —
condition, km, title status, and how long it's sat unsold — then reason to a
fair as-is anchor.

Key behaviours (from Charles's feedback):
  - A listing that's sat a long time unsold ⇒ asking is above market ⇒ discount it.
  - Rebuilt/salvage-title comps are NOT clean comps ⇒ segmented out of the anchor.
  - Condition lives in *which comps you trust*, not a separate blanket deduction.

scrutinize(subject, comps) ->
{
  "anchor": int|None,            # reasoned as-is retail anchor (CAD cents)
  "confidence": "high|medium|low",
  "clean": [comp + reasoning],   # comps used, each with est_sale + score + note
  "excluded": [comp + reason],   # rebuilt/salvage or unusable
  "narrative": [str],            # one human line per comp
}
"""

import re
from datetime import datetime, timezone

# Value sensitivity to mileage, used to normalize each comp's price to the SUBJECT's km.
# Raised from 0.30 + widened clamp: the gentle curve under-penalized extreme-mileage subjects
# (a 344k-km car was barely discounted vs ~180k comps). TUNABLE.
KM_SENSITIVITY = 0.40


def _km_normalize(price: int, comp_km, subj_km) -> int:
    """Adjust a comp's price to the subject's mileage (more comp km ⇒ adjust price up)."""
    if not (price and comp_km and subj_km and subj_km > 0):
        return price
    # Fraction the comp is above/below the subject's mileage, clamped to ±85%.
    km_diff_frac = max(-0.85, min(0.85, (comp_km - subj_km) / subj_km))
    return int(price * (1 + km_diff_frac * KM_SENSITIVITY))


def _dom_discount(age_days: int | None) -> float:
    """Days-on-market discount: a stale unsold listing means asking > market. TUNABLE."""
    if not age_days or age_days <= 21:
        return 0.0
    if age_days <= 45:
        return 0.03
    if age_days <= 90:
        return 0.07
    if age_days <= 150:
        return 0.12
    return 0.18


_REBUILT_KW = ("rebuilt", "rebuild", "salvage", "branded", "reconstructed", "rebuilt title")
_ROUGH_KW = ("as is", "as-is", "needs work", "mechanic special", "project", "parts",
             "not running", "doesn't run", "rust hole", "needs tlc")
_CLEAN_KW = ("no accident", "no accidents", "clean title", "mint", "immaculate",
             "excellent condition", "showroom", "pristine")


def _text(comp: dict) -> str:
    """Lowercased title + description + trim of a comp, for keyword matching."""
    return " ".join(str(comp.get(k) or "") for k in ("title", "description", "trim")).lower()


def _title_status(comp: dict) -> str:
    """'rebuilt' if any rebuilt/salvage keyword appears, else 'clean'."""
    text = _text(comp)
    if any(kw in text for kw in _REBUILT_KW):
        return "rebuilt"
    return "clean"


def _condition_hint(comp: dict) -> str:
    """'rough', 'clean', or 'unknown' based on condition keywords in the listing text."""
    text = _text(comp)
    if any(kw in text for kw in _ROUGH_KW):
        return "rough"
    if any(kw in text for kw in _CLEAN_KW):
        return "clean"
    return "unknown"


def _age_days(comp: dict) -> int | None:
    """Days since the comp was posted, or None if there's no parseable post date."""
    posted = comp.get("posted_at")
    if not posted:
        return None
    if isinstance(posted, str):
        try:
            posted = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        except ValueError:
            return None
    now = datetime.now(timezone.utc)
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return max(0, (now - posted).days)


def _norm_cab(*texts) -> str | None:
    """Canonical truck cab ('crew' | 'ext' | 'reg') from any trim/title/description text."""
    text = " ".join(str(x or "") for x in texts).upper()
    if any(kw in text for kw in ("SUPERCREW", "CREW CAB", "CREWCAB", "CREWMAX", "CREW")):
        return "crew"
    if any(kw in text for kw in ("SUPERCAB", "SUPER CAB", "QUAD", "DOUBLE CAB", "KING CAB",
                                 "ACCESS CAB", "EXTENDED", "EXT CAB")):
        return "ext"
    if any(kw in text for kw in ("REGULAR CAB", "REG CAB", "SINGLE CAB", "STANDARD CAB", "STD CAB")):
        return "reg"
    return None


# Trim tokens (longest first so multi-word trims win). A trim mismatch is a real
# price gap — a Lariat is not an XLT — so we weight it heavily, like cab config.
_TRIM_TOKENS = [
    "king ranch", "high country", "work truck", "big horn", "grand touring", "limited",
    "platinum", "laramie", "tradesman", "denali", "raptor", "tremor", "lariat", "rebel",
    "wildtrak", "badlands", "trailhawk", "overland", "sahara", "rubicon", "titanium",
    "premium", "touring", "sport", "ltz", "lt", "rst", "trd", "sr5", "slt", "sle",
    "xlt", "xle", "xse", "stx", "xl", "sv", "sl", "se", "ex", "lx",
]


def _trim_token(*texts) -> str | None:
    """First matching trim token (whole-word) found across the given texts, else None."""
    text = " ".join(str(x or "") for x in texts).lower()
    for token in _TRIM_TOKENS:
        if re.search(r"\b" + re.escape(token) + r"\b", text):
            return token
    return None


def _similarity(subject: dict, comp: dict) -> float:
    """Comparability score in [0.05, 1.0]: km, year, cab, trim, and condition matches."""
    score = 0.5

    subj_km, comp_km = subject.get("odometer_km"), comp.get("odometer_km")
    if subj_km and comp_km and subj_km > 0:
        km_ratio = abs(subj_km - comp_km) / subj_km
        score += 0.25 if km_ratio < 0.10 else 0.12 if km_ratio < 0.25 else 0.0

    subj_year, comp_year = subject.get("year"), comp.get("year")
    if subj_year and comp_year:
        year_gap = abs(int(subj_year) - int(comp_year))
        score += 0.15 if year_gap == 0 else 0.08 if year_gap == 1 else 0.0

    # Truck cab match (when the subject is a known cab config) — crew vs reg are
    # different vehicles, so reward matches and penalize mismatches when detectable.
    subj_cab = subject.get("cab") or _norm_cab(subject.get("trim"), subject.get("style"))
    if subj_cab:
        comp_cab = _norm_cab(comp.get("trim"), comp.get("title"), comp.get("description"))
        if comp_cab:
            score += 0.12 if (_norm_cab(subj_cab) or subj_cab) == comp_cab else -0.18

    # Trim match — a Lariat anchored to XLT comps prices it badly low. Reward same
    # trim, penalize a different known trim.
    subj_trim = _trim_token(subject.get("trim"))
    if subj_trim:
        comp_trim = _trim_token(comp.get("trim"), comp.get("title"), comp.get("description"))
        if comp_trim:
            score += 0.2 if comp_trim == subj_trim else -0.22

    if _condition_hint(comp) == "rough":
        score -= 0.10        # less comparable to a clean resale (still informative as a floor)

    return max(0.05, min(score, 1.0))


def _median(vals):
    """Integer median of vals (averaging the two middle values for even counts), or None."""
    ordered = sorted(vals)
    n = len(ordered)
    if n == 0:
        return None
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) // 2


def scrutinize(subject: dict, comps: list[dict], top_n: int = 6) -> dict:
    clean, excluded, narrative = [], [], []

    # 1. Reason about each comp: estimate its likely sale price (asking minus a
    #    days-on-market discount) and score its comparability. Rebuilt/salvage
    #    titles and priceless listings are excluded from the clean pool.
    for comp in comps:
        asking = comp.get("asking_price") or 0
        if asking <= 0:
            excluded.append({**comp, "_reason": "no price"})
            continue
        title = _title_status(comp)
        age = _age_days(comp)
        discount = _dom_discount(age)
        est_sale = int(asking * (1 - discount))
        row = {**comp, "_title": title, "_age_days": age, "_dom_discount": discount,
               "_est_sale": est_sale, "_score": _similarity(subject, comp),
               "_condition": _condition_hint(comp),
               "_trim": _trim_token(comp.get("trim"), comp.get("title"), comp.get("description"))}
        if title == "rebuilt":
            row["_reason"] = "rebuilt/salvage title — not a clean comp"
            excluded.append(row)
        else:
            clean.append(row)

    # 2. Prefer comps that have odometer data — they're the only ones we can truly
    #    compare. Fall back to all clean comps if we don't have enough with km.
    with_km = [c for c in clean if c.get("odometer_km")]
    pool = with_km if len(with_km) >= 3 else clean

    # 3. Normalize each comp's estimated sale price to the subject's mileage.
    subj_km = subject.get("odometer_km")
    for row in pool:
        row["_km_adj"] = _km_normalize(row["_est_sale"], row.get("odometer_km"), subj_km)

    # 4. Keep the most comparable comps, then drop the cheapest/priciest as outliers
    #    (rough units / wrong trims) once we have enough to spare.
    pool.sort(key=lambda r: r["_score"], reverse=True)
    top = pool[:top_n]
    if len(top) >= 5:
        by_price = sorted(top, key=lambda r: r["_km_adj"])
        top = by_price[1:-1]

    # 5. Anchor = similarity-weighted average of the km-normalized clean comps
    #    (falling back to the median if every weight is zero).
    anchor = None
    if top:
        weight_sum = sum(r["_score"] for r in top)
        if weight_sum:
            anchor = int(sum(r["_km_adj"] * r["_score"] for r in top) / weight_sum)
        else:
            anchor = _median([r["_km_adj"] for r in top])

    n_top = len(top)
    confidence = "high" if n_top >= 5 else "medium" if n_top >= 3 else "low"

    # 6. One human-readable line per comp used or excluded.
    for row in (top + excluded):
        km = f"{row.get('odometer_km'):,}km" if row.get("odometer_km") else "km?"
        age = f"{row['_age_days']}d" if row.get("_age_days") is not None else "age?"
        discount = f"−{int(row['_dom_discount']*100)}%" if row.get("_dom_discount") else "—"
        km_adj = row.get("_km_adj", row["_est_sale"])
        tag = row.get("_reason", f"score {row['_score']:.2f}")
        narrative.append(
            f"{row.get('year')} {row.get('make')} {row.get('model')} {((row.get('_trim') or '').upper())} | {km} | ask ${ (row.get('asking_price') or 0)/100:,.0f}"
            f" | listed {age} {discount} → est ${row['_est_sale']/100:,.0f} → km-adj ${km_adj/100:,.0f} | {row.get('_condition')} | {tag}"
        )

    return {"anchor": anchor, "confidence": confidence,
            "clean": top, "excluded": excluded, "narrative": narrative}
