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
    diff = max(-0.85, min(0.85, (comp_km - subj_km) / subj_km))
    return int(price * (1 + diff * KM_SENSITIVITY))


# Days-on-market discount: a stale unsold listing means asking > market. TUNABLE.
def _dom_discount(age_days: int | None) -> float:
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
    return " ".join(str(comp.get(k) or "") for k in ("title", "description", "trim")).lower()


def _title_status(comp: dict) -> str:
    t = _text(comp)
    if any(k in t for k in _REBUILT_KW):
        return "rebuilt"
    return "clean"


def _condition_hint(comp: dict) -> str:
    t = _text(comp)
    if any(k in t for k in _ROUGH_KW):
        return "rough"
    if any(k in t for k in _CLEAN_KW):
        return "clean"
    return "unknown"


def _age_days(comp: dict) -> int | None:
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
    t = " ".join(str(x or "") for x in texts).upper()
    if any(k in t for k in ("SUPERCREW", "CREW CAB", "CREWCAB", "CREWMAX", "CREW")):
        return "crew"
    if any(k in t for k in ("SUPERCAB", "SUPER CAB", "QUAD", "DOUBLE CAB", "KING CAB",
                            "ACCESS CAB", "EXTENDED", "EXT CAB")):
        return "ext"
    if any(k in t for k in ("REGULAR CAB", "REG CAB", "SINGLE CAB", "STANDARD CAB", "STD CAB")):
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
    t = " ".join(str(x or "") for x in texts).lower()
    for tok in _TRIM_TOKENS:
        if re.search(r"\b" + re.escape(tok) + r"\b", t):
            return tok
    return None


def _similarity(subject: dict, comp: dict) -> float:
    score = 0.5
    s_km, c_km = subject.get("odometer_km"), comp.get("odometer_km")
    if s_km and c_km and s_km > 0:
        ratio = abs(s_km - c_km) / s_km
        score += 0.25 if ratio < 0.10 else 0.12 if ratio < 0.25 else 0.0
    s_yr, c_yr = subject.get("year"), comp.get("year")
    if s_yr and c_yr:
        d = abs(int(s_yr) - int(c_yr))
        score += 0.15 if d == 0 else 0.08 if d == 1 else 0.0
    # Truck cab match (when the subject is a known cab config) — crew vs reg are
    # different vehicles, so reward matches and penalize mismatches when detectable.
    s_cab = subject.get("cab") or _norm_cab(subject.get("trim"), subject.get("style"))
    if s_cab:
        c_cab = _norm_cab(comp.get("trim"), comp.get("title"), comp.get("description"))
        if c_cab:
            score += 0.12 if (_norm_cab(s_cab) or s_cab) == c_cab else -0.18

    # Trim match — a Lariat anchored to XLT comps prices it badly low. Reward same
    # trim, penalize a different known trim.
    s_trim = _trim_token(subject.get("trim"))
    if s_trim:
        c_trim = _trim_token(comp.get("trim"), comp.get("title"), comp.get("description"))
        if c_trim:
            score += 0.2 if c_trim == s_trim else -0.22
    cond = _condition_hint(comp)
    if cond == "rough":
        score -= 0.10        # less comparable to a clean resale (still informative as a floor)
    return max(0.05, min(score, 1.0))


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return None if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2)


def scrutinize(subject: dict, comps: list[dict], top_n: int = 6) -> dict:
    clean, excluded, narrative = [], [], []

    for comp in comps:
        asking = comp.get("asking_price") or 0
        if asking <= 0:
            excluded.append({**comp, "_reason": "no price"})
            continue
        title = _title_status(comp)
        age = _age_days(comp)
        disc = _dom_discount(age)
        est_sale = int(asking * (1 - disc))
        score = _similarity(subject, comp)
        row = {**comp, "_title": title, "_age_days": age, "_dom_discount": disc,
               "_est_sale": est_sale, "_score": score, "_condition": _condition_hint(comp),
               "_trim": _trim_token(comp.get("trim"), comp.get("title"), comp.get("description"))}
        if title == "rebuilt":
            row["_reason"] = "rebuilt/salvage title — not a clean comp"
            excluded.append(row)
        else:
            clean.append(row)

    # Prefer comps that have odometer data — they're the only ones we can truly compare.
    with_km = [c for c in clean if c.get("odometer_km")]
    pool = with_km if len(with_km) >= 3 else clean

    subj_km = subject.get("odometer_km")
    for r in pool:
        r["_km_adj"] = _km_normalize(r["_est_sale"], r.get("odometer_km"), subj_km)

    pool.sort(key=lambda r: r["_score"], reverse=True)
    top = pool[:top_n]

    # Trim price outliers (rough units / wrong trims) once we have enough comps.
    if len(top) >= 5:
        by_price = sorted(top, key=lambda r: r["_km_adj"])
        top = by_price[1:-1]

    # similarity-weighted estimate from the best, km-normalized clean comps
    anchor = None
    if top:
        wsum = sum(r["_score"] for r in top)
        anchor = int(sum(r["_km_adj"] * r["_score"] for r in top) / wsum) if wsum \
            else _median([r["_km_adj"] for r in top])

    n = len(top)
    confidence = "high" if n >= 5 else "medium" if n >= 3 else "low"

    for r in (top + excluded):
        km = f"{r.get('odometer_km'):,}km" if r.get("odometer_km") else "km?"
        age = f"{r['_age_days']}d" if r.get("_age_days") is not None else "age?"
        disc = f"−{int(r['_dom_discount']*100)}%" if r.get("_dom_discount") else "—"
        adj = r.get("_km_adj", r["_est_sale"])
        tag = r.get("_reason", f"score {r['_score']:.2f}")
        narrative.append(
            f"{r.get('year')} {r.get('make')} {r.get('model')} {((r.get('_trim') or '').upper())} | {km} | ask ${ (r.get('asking_price') or 0)/100:,.0f}"
            f" | listed {age} {disc} → est ${r['_est_sale']/100:,.0f} → km-adj ${adj/100:,.0f} | {r.get('_condition')} | {tag}"
        )

    return {"anchor": anchor, "confidence": confidence,
            "clean": top, "excluded": excluded, "narrative": narrative}
