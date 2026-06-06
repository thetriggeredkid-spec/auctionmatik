"""
VIN decode — NHTSA vPIC, cached.

The VIN is factory truth for build spec: driveline, engine, body, and (on trucks)
cab/bed — the primary value drivers the comp match hinges on. We decode it once via
the free NHTSA vPIC API (no key), cache the normalized result in `vin_decode`, and
gap-fill the vehicle spec from it (see evaluate.apply_vin_decode).

NHTSA caveats: Make/Model/Year/Body/Engine/DriveType are reliable; Trim is often blank
or generic (we fall back to Series). So treat this as a HARDENING source — gap-fill only,
never override a present scrape value or an operator override.

Usage:
    python3 -m collector.vin_decode 1C4HJXEG5JW287140
"""

import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$", re.I)  # VINs exclude I/O/Q


def _norm_driveline(raw: str) -> str | None:
    r = (raw or "").upper()
    if not r:
        return None
    if "4WD" in r or "4X4" in r or "FOUR" in r or "4-WHEEL" in r:
        return "4WD"
    if "AWD" in r or "ALL-WHEEL" in r or "ALL WHEEL" in r:
        return "AWD"
    if "FWD" in r or "FRONT-WHEEL" in r or "FRONT WHEEL" in r:
        return "FWD"
    if "RWD" in r or "REAR-WHEEL" in r or "REAR WHEEL" in r:
        return "RWD"
    return None


def _norm_cab(raw: str) -> str | None:
    r = (raw or "").upper()
    if "CREW" in r:
        return "crew"
    if (
        "EXTEND" in r
        or "DOUBLE" in r
        or "SUPER" in r
        or "QUAD" in r
        or "KING" in r
        or "ACCESS" in r
    ):
        return "ext"
    if "REGULAR" in r or "STANDARD" in r or "SINGLE" in r:
        return "reg"
    return None


def _engine_str(res: dict) -> str | None:
    """Build a compact engine string, e.g. '3.5L V6' / '5.0L 8cyl', from vPIC fields."""
    disp = res.get("DisplacementL")
    cyl = res.get("EngineCylinders")
    config = (res.get("EngineConfiguration") or "").upper()
    parts = []
    if disp:
        try:
            parts.append(f"{float(disp):.1f}L")
        except (ValueError, TypeError):
            pass
    if cyl and str(cyl).strip().isdigit():
        if "V" in config:
            parts.append(f"V{int(cyl)}")
        elif "INLINE" in config or "STRAIGHT" in config:
            parts.append(f"I{int(cyl)}")
        else:
            parts.append(f"{int(cyl)}cyl")
    return " ".join(parts) or None


def _normalize(res: dict) -> dict:
    """vPIC flat result → our spec keys. Empty/zero fields drop to None."""

    def val(*keys):
        for k in keys:
            v = res.get(k)
            if v not in (None, "", "Not Applicable", "0"):
                return str(v).strip()
        return None

    year = res.get("ModelYear")
    return {
        "year": int(year) if str(year).isdigit() else None,
        "make": (val("Make") or "").upper() or None,
        "model": (val("Model") or "").upper() or None,
        "trim": val("Trim", "Series", "Series2"),
        "driveline": _norm_driveline(res.get("DriveType")),
        "engine": _engine_str(res),
        "cab": _norm_cab(res.get("BodyCabType")),
        "bed": val("BedType"),
        "fuel_type": val("FuelTypePrimary"),
        "transmission": val("TransmissionStyle"),
        "body_class": val("BodyClass"),
    }


def _fetch_nhtsa(vin: str) -> dict | None:
    import requests

    try:
        r = requests.get(NHTSA_URL.format(vin=vin), timeout=12)
        r.raise_for_status()
        results = (r.json() or {}).get("Results") or []
    except (
        Exception
    ):  # noqa: BLE001 — offline / API down / bad json: degrade gracefully
        return None
    if not results:
        return None
    res = results[0]
    # ErrorCode "0" = decoded cleanly; anything else may still carry partial fields, so keep it.
    return _normalize(res)


def decode_vin(vin: str | None, conn=None, allow_fetch: bool = True) -> dict | None:
    """Return the normalized spec for a VIN (cached). `allow_fetch=False` serves cache only
    (used for fast lane screening — no live API call). Returns None when unavailable."""
    if not vin:
        return None
    vin = vin.strip().upper()
    if not _VIN_RE.match(vin):
        return None

    close = conn is None
    if conn is None:
        from db.connection import get_conn

        conn = get_conn()
    try:
        from db.connection import get_cursor

        cur = get_cursor(conn)
        cur.execute("SELECT decoded FROM vin_decode WHERE vin = %s", (vin,))
        row = cur.fetchone()
        cur.close()
        if row:
            decoded = row.get("decoded")
            return json.loads(decoded) if isinstance(decoded, str) else decoded

        if not allow_fetch:
            return None
        decoded = _fetch_nhtsa(vin)
        if decoded is None:
            return None
        cur = get_cursor(conn)
        cur.execute(
            """INSERT INTO vin_decode (vin, decoded, fetched_at) VALUES (%s, %s::jsonb, NOW())
               ON CONFLICT (vin) DO UPDATE SET decoded = EXCLUDED.decoded, fetched_at = NOW()""",
            (vin, json.dumps(decoded)),
        )
        conn.commit()
        cur.close()
        return decoded
    finally:
        if close:
            conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 -m collector.vin_decode <VIN>")
        sys.exit(1)
    out = decode_vin(sys.argv[1])
    print(
        json.dumps(out, indent=2)
        if out
        else "(no decode — bad VIN, offline, or no data)"
    )
