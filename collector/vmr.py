"""
VMR Canada lookup — a published book-value SANITY CHECK for the engine.

VMR Canada (vmrcanada.com) serves used-vehicle wholesale/retail values as static,
public HTML (no login, no captcha) at a deterministic URL:
    https://www.vmrcanada.com/used-car/values/{year}-{make}-{model}.html
Each page lists every trim/body with base WS + Retail, plus a JS mileage calculator.
We fetch + parse the trim table and replicate VMR's own mileage-adjustment formula
(lifted from their calcvalue() script) — so no browser is needed.

This is a CROSS-CHECK only; the engine stays comp-driven. vmr_lookup(...) returns
the km-adjusted WS/Retail for the trim that best matches the subject, or None.
"""

import re
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_BASE = "https://www.vmrcanada.com/used-car/values/{year}-{make}-{model}.html"
_PAGE_CACHE: dict = {}   # url -> [trim rows] | None  (page tables rarely change)

# Current model year baseline for the mileage formula (VMR uses the running year).
import datetime as _dt
_CURRENT_YEAR = _dt.date.today().year


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _norm_cab(*texts) -> str | None:
    t = " ".join(str(x or "") for x in texts).lower()
    if any(k in t for k in ("supercrew", "crew cab", "crewcab", "crewmax", "crew")):
        return "crew"
    if any(k in t for k in ("supercab", "super cab", "quad", "double cab", "king cab", "access cab", "extended", "ext cab")):
        return "ext"
    if any(k in t for k in ("regular cab", "reg cab", "single cab", "std cab", "standard cab")):
        return "reg"
    return None


def _parse_trims(html: str) -> list:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        head = [c.get_text(strip=True).lower() for c in rows[0].find_all(["td", "th"])]
        if head[:3] == ["trim", "ws", "retail"]:
            out = []
            for row in rows[1:]:
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 3 and cells[1].isdigit() and cells[2].isdigit():
                    out.append({"trim": cells[0], "ws": int(cells[1]), "retail": int(cells[2])})
            return out
    return []


def _candidate_urls(year, make, model) -> list:
    mk = _slug(make)
    parts = (model or "").split()
    slugs = [_slug(model)]
    if len(parts) > 1:                         # "GRAND CARAVAN" → try "caravan" too
        slugs.append(_slug(parts[-1]))
        slugs.append(_slug(parts[0]))
    seen, urls = set(), []
    for s in slugs:
        u = _BASE.format(year=year, make=mk, model=s)
        if s and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def _fetch(year, make, model):
    for url in _candidate_urls(year, make, model):
        if url in _PAGE_CACHE:
            if _PAGE_CACHE[url]:
                return url, _PAGE_CACHE[url]
            continue
        try:
            r = requests.get(url, headers=_HEADERS, timeout=15)
            trims = _parse_trims(r.text) if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            trims = []
        _PAGE_CACHE[url] = trims or None
        if trims:
            return url, trims
    return _candidate_urls(year, make, model)[0], None


def _best_match(trims, trim, cab, driveline, engine):
    tl = (trim or "").lower().strip()
    cabkey = _norm_cab(cab, trim)
    dl = (driveline or "").upper()
    eng = (engine or "").lower()
    em = re.search(r"(\d\.\d)\s*l", eng)
    best, best_score = None, 0
    for r in trims:
        txt = r["trim"].lower()
        s = 0
        if tl and re.search(r"\b" + re.escape(tl) + r"\b", txt):
            s += 4
        rc = _norm_cab(r["trim"])
        if cabkey and rc:
            s += 3 if rc == cabkey else -2
        if dl in ("4WD", "AWD") and ("4wd" in txt or "awd" in txt):
            s += 1
        if dl in ("FWD", "RWD", "2WD") and "4wd" not in txt and "awd" not in txt:
            s += 1
        if em and em.group(1) in txt:
            s += 1
        if s > best_score:
            best, best_score = r, s
    return best if best_score > 0 else None


def _mileage_adj(wholesale: int, model_year: int, km: int) -> float:
    """Replicates VMR's calcvalue() mileage adjustment (applied to WS and Retail alike)."""
    yrsold = _CURRENT_YEAR - model_year
    if yrsold < 7:
        normkm = yrsold * 21500
    else:
        normkm = 129000 + ((yrsold - 6) * (18000 * (1 - ((yrsold - 7) / 100))))
    yradj = (1 - (yrsold / 30)) * 0.5
    maxmin = 0.7 * wholesale
    adj = (normkm - km) * (0.12 * ((wholesale / 28000) + 0.27)) * yradj
    rng = normkm - km
    if maxmin and abs(adj) > maxmin:
        adj = (abs(adj) / adj) * maxmin
    if -5000 < rng < 5000:
        adj = 0
    return adj


def vmr_lookup(year, make, model, *, km=None, trim=None, cab=None,
               driveline=None, engine=None) -> dict | None:
    """Return km-adjusted VMR WS/Retail for the best-matching trim (or trim-median
    fallback), plus provenance. None if VMR has no page for this vehicle."""
    if not (year and make and model):
        return None
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None
    url, trims = _fetch(year, make, model)
    if not trims:
        return None

    row = _best_match(trims, trim, cab, driveline, engine)
    if row:
        base_ws, base_ret, tname, matched = row["ws"], row["retail"], row["trim"], True
    else:                                       # no trim match → median of all trims
        ws_sorted = sorted(t["ws"] for t in trims)
        ret_sorted = sorted(t["retail"] for t in trims)
        mid = len(trims) // 2
        base_ws, base_ret, tname, matched = ws_sorted[mid], ret_sorted[mid], f"{len(trims)} trims (median)", False

    adj = _mileage_adj(base_ws, year, int(km)) if km else 0.0
    return {
        "ws": int(round((base_ws + adj) / 25) * 25),
        "retail": int(round((base_ret + adj) / 25) * 25),
        "baseWs": base_ws, "baseRetail": base_ret,
        "mileageAdj": int(round(adj)),
        "trim": tname, "matched": matched, "nTrims": len(trims), "url": url,
        "km": int(km) if km else None,
    }


if __name__ == "__main__":
    import json
    import argparse
    ap = argparse.ArgumentParser(description="VMR Canada book-value lookup")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--make", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--km", type=int)
    ap.add_argument("--trim")
    ap.add_argument("--cab")
    ap.add_argument("--driveline")
    ap.add_argument("--engine")
    a = ap.parse_args()
    print(json.dumps(vmr_lookup(a.year, a.make, a.model, km=a.km, trim=a.trim,
                                cab=a.cab, driveline=a.driveline, engine=a.engine), indent=2))
