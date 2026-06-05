"""
Editable settings — defaults + DB overrides, applied to the live engine config.

The hardcoded values in engine/advisor.py and engine/max_bid.py are the DEFAULTS.
The dashboard's Settings editor stores only the deltas in app_settings (JSONB).
`apply(merged)` patches the running modules in place so every evaluation uses the
edited buyer profiles / margin tiers / fee schedule / GST / engine toggles.

The CLI (evaluate.py) keeps the hardcoded defaults unless it calls apply_from_db().
"""

import copy
import json

_INF = 100_000_000   # JSON-friendly stand-in for the top fee/margin band's "infinity"

# In-memory live snapshot (engine toggles read this at call time).
CURRENT: dict = {}
# Pristine defaults captured on first read (BEFORE apply() ever mutates the live config).
_SNAPSHOT: dict | None = None


def _defaults() -> dict:
    """The hardcoded engine values, captured once before any settings are applied."""
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        return copy.deepcopy(_SNAPSHOT)
    _SNAPSHOT = _read_engine_defaults()
    return copy.deepcopy(_SNAPSHOT)


def _read_engine_defaults() -> dict:
    from engine.advisor import PROFILES
    from engine.max_bid import MARGIN_TIERS, REGAL_FEE_SCHEDULE, GST_RATE

    profiles = {}
    for key, p in PROFILES.items():
        profiles[key] = {
            "label": p.get("label", key),
            "margin_floor": p.get("margin_floor", 1500),
            "margin_scale": p.get("margin_scale", 1.0),
            "repair_buffer": p.get("repair_buffer", 0.20),
            "hold_time": p.get("hold_time", "low"),
            "diy": p.get("diy", "some"),
            "mech_reserve_factor": p.get("mech_reserve_factor", 1.0),
            "repair_small_factor": (p.get("repair") or {}).get("small_factor", 0.65),
            "repair_large_factor": (p.get("repair") or {}).get("large_factor", 1.0),
        }
    return {
        "profiles": profiles,
        "profile_order": list(PROFILES.keys()),
        "margin_tiers": [[lo, (_INF if hi == float("inf") else hi), m, lbl] for lo, hi, m, lbl in MARGIN_TIERS],
        "fee_schedule": [[lo, (_INF if hi == float("inf") else hi), f] for lo, hi, f in REGAL_FEE_SCHEDULE],
        "gst_rate": GST_RATE,
        "engine": {
            "deep_autopull_carfax": True,
            "deep_autorun_vision": True,
            "deep_autocollect_comps": True,
            "vision_photo_cap": 30,
            "prep_default_limit": 25,
        },
    }


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(conn) -> dict:
    """Defaults merged with the stored overrides → the full effective settings."""
    from db.connection import get_cursor
    cur = get_cursor(conn)
    cur.execute("SELECT settings FROM app_settings WHERE id = 1")
    row = cur.fetchone()
    cur.close()
    overrides = (row.get("settings") if row else None) or {}
    if isinstance(overrides, str):
        try:
            overrides = json.loads(overrides)
        except (ValueError, TypeError):
            overrides = {}
    merged = _deep_merge(_defaults(), overrides)
    # These keys must fully replace (not deep-merge into) the defaults when the editor
    # sends them, so list deletes/renames/reorders stick instead of being merged back.
    for key in ("profiles", "profile_order", "margin_tiers", "fee_schedule"):
        if key in overrides:
            merged[key] = overrides[key]
    return merged


def _to_profile(p: dict, key: str) -> dict:
    return {
        "label": p.get("label", key), "margin_floor": int(p.get("margin_floor", 1500)),
        "margin_scale": float(p.get("margin_scale", 1.0)), "repair_buffer": float(p.get("repair_buffer", 0.20)),
        "hold_time": p.get("hold_time", "low"), "diy": p.get("diy", "some"),
        "mech_reserve_factor": float(p.get("mech_reserve_factor", 1.0)),
        "repair": {"small_factor": float(p.get("repair_small_factor", 0.65)),
                   "large_factor": float(p.get("repair_large_factor", 1.0))},
    }


def apply(merged: dict) -> None:
    """Patch the live engine modules in place so the running app uses these settings."""
    import engine.advisor as adv
    import engine.max_bid as mb
    import engine.vision as vis

    # Buyer profiles — mutate the dict in place so existing references stay valid.
    new_profiles = {k: _to_profile(p, k) for k, p in (merged.get("profiles") or {}).items()}
    if new_profiles:
        adv.PROFILES.clear()
        adv.PROFILES.update(new_profiles)

    # Margin tiers + fee schedule (read at call time by get_margin/get_buyer_fee).
    # Restore the JSON-friendly sentinel back to a real float("inf") top band.
    def _to_inf(hi):
        return float("inf") if hi is None or hi >= _INF else hi
    if merged.get("margin_tiers"):
        mb.MARGIN_TIERS = [(lo, _to_inf(hi), m, lbl) for lo, hi, m, lbl in merged["margin_tiers"]]
    if merged.get("fee_schedule"):
        mb.REGAL_FEE_SCHEDULE = [(lo, _to_inf(hi), f) for lo, hi, f in merged["fee_schedule"]]

    # GST — patch every module that imported it by value.
    gst = float(merged.get("gst_rate", mb.GST_RATE))
    mb.GST_RATE = gst
    adv.GST_RATE = gst

    # Vision photo cap.
    cap = (merged.get("engine") or {}).get("vision_photo_cap")
    if cap:
        vis.MAX_PHOTOS_FOR_VISION = int(cap)

    CURRENT.clear()
    CURRENT.update(merged)


def engine_flag(name: str, default):
    return (CURRENT.get("engine") or {}).get(name, default)


def apply_from_db(conn) -> dict:
    merged = load(conn)
    apply(merged)
    return merged


def save(conn, patch: dict) -> dict:
    from db.connection import get_cursor
    cur = get_cursor(conn)
    cur.execute("UPDATE app_settings SET settings = %s::jsonb, updated_at = NOW() WHERE id = 1",
                (json.dumps(patch or {}),))
    conn.commit()
    cur.close()
    return apply_from_db(conn)


def reset(conn) -> dict:
    return save(conn, {})
