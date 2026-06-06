"""
vPIC dropdown options for the manual (VMR-style) appraisal selector.

NHTSA vPIC (free, no key) feeds the cascading year → make → model dropdowns; VMR
(collector/vmr.py) supplies the per-model trim list. Results are cached in-memory so
the dropdowns don't re-hit the API on every keystroke. VIN shortcut reuses
collector/vin_decode.decode_vin.
"""

import requests

_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
_MAKES_CACHE: list | None = None
_MODELS_CACHE: dict = {}


def _get(url: str) -> list:
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return (r.json() or {}).get("Results") or []
    except (
        Exception
    ):  # noqa: BLE001 — offline / API down: empty list, UI falls back to free-text
        return []


def makes() -> list:
    """Common consumer makes (passenger cars + trucks/MPVs), de-duped + sorted. Cached."""
    global _MAKES_CACHE
    if _MAKES_CACHE is not None:
        return _MAKES_CACHE
    names = set()
    for vtype in ("car", "truck", "mpv"):
        for row in _get(f"{_BASE}/GetMakesForVehicleType/{vtype}?format=json"):
            n = (row.get("MakeName") or "").strip()
            if n:
                names.add(n.upper())
    _MAKES_CACHE = sorted(names)
    return _MAKES_CACHE


def models(make: str, year: int) -> list:
    """Models for a make + year (vPIC GetModelsForMakeYear). Cached per (make, year)."""
    make = (make or "").strip()
    if not (make and year):
        return []
    key = (make.upper(), int(year))
    if key in _MODELS_CACHE:
        return _MODELS_CACHE[key]
    rows = _get(
        f"{_BASE}/GetModelsForMakeYear/make/{make}/modelyear/{int(year)}?format=json"
    )
    out = sorted(
        {
            (r.get("Model_Name") or "").strip().upper()
            for r in rows
            if r.get("Model_Name")
        }
    )
    _MODELS_CACHE[key] = out
    return out


def trims(year: int, make: str, model: str) -> list:
    """Trim names for a year/make/model, from VMR's published trim table (best source we have)."""
    if not (year and make and model):
        return []
    try:
        from collector.vmr import _fetch

        _, rows = _fetch(int(year), make, model)
        return [r["trim"] for r in (rows or [])]
    except Exception:  # noqa: BLE001
        return []


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) >= 4:
        print(json.dumps(trims(int(sys.argv[1]), sys.argv[2], sys.argv[3]), indent=2))
    elif len(sys.argv) == 3:
        print(json.dumps(models(sys.argv[1], int(sys.argv[2])), indent=2))
    else:
        print(json.dumps(makes()[:50], indent=2))
