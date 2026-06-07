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


_REBUILT_KW = (
    "rebuilt",
    "rebuild",
    "salvage",
    "branded",
    "reconstructed",
    "rebuilt title",
)
_ROUGH_KW = (
    "as is",
    "as-is",
    "needs work",
    "mechanic special",
    "project",
    "parts",
    "not running",
    "doesn't run",
    "rust hole",
    "needs tlc",
)
_CLEAN_KW = (
    "no accident",
    "no accidents",
    "clean title",
    "mint",
    "immaculate",
    "excellent condition",
    "showroom",
    "pristine",
)


def _text(comp: dict) -> str:
    """Lowercased title + description + trim of a comp, for keyword matching."""
    return " ".join(
        str(comp.get(k) or "") for k in ("title", "description", "trim")
    ).lower()


def _title_status(comp: dict) -> str:
    """'rebuilt' if any rebuilt/salvage keyword appears, else 'clean'."""
    text = _text(comp)
    if any(kw in text for kw in _REBUILT_KW):
        return "rebuilt"
    return "clean"


def _vision_condition(comp: dict) -> str | None:
    """Condition read from a comp's stored vision assessment (Haiku photo read), if any.
    Returns 'damaged' (exclude from the clean anchor — cheap BECAUSE wrecked, not a clean
    floor), 'rough' (down-weight), or None when there's no usable vision."""
    v = comp.get("vision")
    if not isinstance(v, dict) or v.get("error"):
        return None
    if v.get("flood_or_frame_concern") is True:
        return "damaged"
    try:
        ext = int(v["exterior_grade"]) if v.get("exterior_grade") is not None else None
    except (ValueError, TypeError):
        ext = None
    damage = v.get("damage_details") or []
    severities = {(d.get("severity") or "").lower() for d in damage}
    if (
        (ext is not None and ext <= 2)
        or "severe" in severities
        or (v.get("rust_severity") == "severe")
    ):
        return "damaged"
    if "moderate" in severities or (v.get("rust_severity") == "moderate"):
        return "rough"
    return None


def _condition_hint(comp: dict) -> str:
    """'rough', 'clean', or 'unknown'. A stored vision read (when present) wins over the
    listing-text keywords — photos beat seller adjectives."""
    vis = _vision_condition(comp)
    if vis:  # 'damaged' or 'rough' → penalize like 'rough'
        return "rough"
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
    if any(
        kw in text for kw in ("SUPERCREW", "CREW CAB", "CREWCAB", "CREWMAX", "CREW")
    ):
        return "crew"
    if any(
        kw in text
        for kw in (
            "SUPERCAB",
            "SUPER CAB",
            "QUAD",
            "DOUBLE CAB",
            "KING CAB",
            "ACCESS CAB",
            "EXTENDED",
            "EXT CAB",
        )
    ):
        return "ext"
    if any(
        kw in text
        for kw in ("REGULAR CAB", "REG CAB", "SINGLE CAB", "STANDARD CAB", "STD CAB")
    ):
        return "reg"
    return None


# Trim tokens (longest first so multi-word trims win). A trim mismatch is a real
# price gap — a Lariat is not an XLT — so we weight it heavily, like cab config.
_TRIM_TOKENS = [
    "king ranch",
    "high country",
    "work truck",
    "big horn",
    "grand touring",
    "limited",
    "platinum",
    "laramie",
    "tradesman",
    "denali",
    "raptor",
    "tremor",
    "lariat",
    "rebel",
    "wildtrak",
    "badlands",
    "trailhawk",
    "overland",
    "sahara",
    "rubicon",
    "titanium",
    "premium",
    "touring",
    "sport",
    "ltz",
    "lt",
    "rst",
    "trd",
    "sr5",
    "slt",
    "sle",
    "xlt",
    "xle",
    "xse",
    "stx",
    "xl",
    "sv",
    "sl",
    "se",
    "ex",
    "lx",
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
    subj_cab = subject.get("cab") or _norm_cab(
        subject.get("trim"), subject.get("style")
    )
    if subj_cab:
        comp_cab = _norm_cab(
            comp.get("trim"), comp.get("title"), comp.get("description")
        )
        if comp_cab:
            score += 0.12 if (_norm_cab(subj_cab) or subj_cab) == comp_cab else -0.18

    # Trim match — a Lariat anchored to XLT comps prices it badly low. Reward same
    # trim, penalize a different known trim.
    subj_trim = _trim_token(subject.get("trim"))
    if subj_trim:
        comp_trim = _trim_token(
            comp.get("trim"), comp.get("title"), comp.get("description")
        )
        if comp_trim:
            score += 0.2 if comp_trim == subj_trim else -0.22

    if _condition_hint(comp) == "rough":
        score -= (
            0.10  # less comparable to a clean resale (still informative as a floor)
        )

    # A realized sale (your own past sale) is the strongest comp there is — a real
    # transaction price, not a hopeful ask. Weight it well above scraped listings.
    if comp.get("realized"):
        score += 0.30

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


def _dedupe_reposts(comps: list[dict]) -> tuple[list[dict], int]:
    """Collapse the SAME vehicle reposted as multiple ads (a dealer posting different photo
    angles under separate listings — same year/make/model/trim/km/price). Counting each as a
    distinct comp fakes confidence and skews the anchor (e.g. contract 33704: 4 ads, 1 car).
    Keeps one per identity (preferring a row that has a photo). Returns (deduped, merged_count).
    """
    seen: dict = {}
    out = []
    for c in comps:
        key = (
            c.get("year"),
            (c.get("make") or "").upper(),
            (c.get("model") or "").upper(),
            (c.get("trim") or "").strip().upper(),
            c.get("odometer_km"),
            c.get("asking_price"),
        )
        # Don't merge on an all-empty identity (missing km AND price → can't tell they're the same).
        if not (key[4] and key[5]):
            out.append(c)
            continue
        if key not in seen:
            seen[key] = len(out)
            out.append(c)
        elif not out[seen[key]].get("main_photo_url") and c.get("main_photo_url"):
            out[seen[key]] = c  # keep the copy that has a photo
    return out, len(comps) - len(out)


def scrutinize(subject: dict, comps: list[dict], top_n: int = 6) -> dict:
    clean, excluded, narrative = [], [], []

    comps, _merged = _dedupe_reposts(comps)
    if _merged:
        narrative.append(
            f"merged {_merged} duplicate repost(s) of the same vehicle (counted once)"
        )

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
        vis_cond = _vision_condition(comp)
        row = {
            **comp,
            "_title": title,
            "_age_days": age,
            "_dom_discount": discount,
            "_est_sale": est_sale,
            "_score": _similarity(subject, comp),
            "_condition": _condition_hint(comp),
            "_realized": bool(comp.get("realized")),
            "_trim": _trim_token(
                comp.get("trim"), comp.get("title"), comp.get("description")
            ),
        }
        if title == "rebuilt":
            row["_reason"] = "rebuilt/salvage title — not a clean comp"
            excluded.append(row)
        elif vis_cond == "damaged" and not row["_realized"]:
            # Photos show heavy damage / flood / frame — it's cheap BECAUSE it's wrecked,
            # not a clean market floor. Drop it from the anchor (a realized sale always stays).
            row["_reason"] = "vision: heavy damage/flood/frame — not a clean comp"
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
        row["_km_adj"] = _km_normalize(
            row["_est_sale"], row.get("odometer_km"), subj_km
        )

    # 4. Keep the most comparable comps, then drop the cheapest/priciest as outliers
    #    (rough units / wrong trims) once we have enough to spare. NEVER trim a realized
    #    sale — a real transaction price isn't an outlier, even if it's the cheap/dear end.
    pool.sort(key=lambda r: r["_score"], reverse=True)
    top = pool[:top_n]
    if len(top) >= 5:
        trimmable = [r for r in top if not r.get("_realized")]
        realized = [r for r in top if r.get("_realized")]
        if len(trimmable) >= 3:
            trimmable = sorted(trimmable, key=lambda r: r["_km_adj"])[1:-1]
        top = realized + trimmable

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
    for row in top + excluded:
        km = f"{row.get('odometer_km'):,}km" if row.get("odometer_km") else "km?"
        age = f"{row['_age_days']}d" if row.get("_age_days") is not None else "age?"
        discount = (
            f"−{int(row['_dom_discount']*100)}%" if row.get("_dom_discount") else "—"
        )
        km_adj = row.get("_km_adj", row["_est_sale"])
        tag = row.get("_reason", f"score {row['_score']:.2f}")
        price = (row.get("asking_price") or 0) / 100
        if row.get("_realized"):
            # A realized sale — show the actual sale price, not an "ask → est" chain.
            narrative.append(
                f"{row.get('year')} {row.get('make')} {row.get('model')} {((row.get('_trim') or '').upper())} | {km}"
                f" | YOUR SALE ${price:,.0f} → km-adj ${km_adj/100:,.0f} | {row.get('_condition')} | {tag}"
            )
        else:
            narrative.append(
                f"{row.get('year')} {row.get('make')} {row.get('model')} {((row.get('_trim') or '').upper())} | {km} | ask ${price:,.0f}"
                f" | listed {age} {discount} → est ${row['_est_sale']/100:,.0f} → km-adj ${km_adj/100:,.0f} | {row.get('_condition')} | {tag}"
            )

    return {
        "anchor": anchor,
        "confidence": confidence,
        "clean": top,
        "excluded": excluded,
        "narrative": narrative,
    }
