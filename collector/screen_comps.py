"""
Comp-coverage batch — proactively deepen the retail comp pool BEFORE you screen.

Deep mode prices off FB/Kijiji comps, but the pool is thin/shallow and gets collected
reactively (one car at a time, mid-eval). This batch walks an upcoming sale's vehicles
(or an ad-hoc make/model), and for each distinct year/make/model that doesn't already
have enough local comps, runs a DETAILED Facebook Marketplace pull (km + post date +
photo galleries) for the active location's city. The result: the lane screens against a
deep, km-rich, local pool instead of scraping per car.

Bounded + idempotent + cost-aware: dedupes models, skips specs already deep enough
(--min-have), caps total scrapes (--max-queries), and has a --dry-run planner. MANUAL
ONLY — nothing here is scheduled; run it when you want to warm the pool. ($ Apify.)

Usage:
    python3 -m collector.screen_comps --next --dry-run            # plan for the soonest sale
    python3 -m collector.screen_comps --date 2026-06-06           # warm comps for that sale
    python3 -m collector.screen_comps --next --min-have 10 --max-queries 25
    python3 -m collector.screen_comps --make FORD --model F-150 --year 2019   # one model
    python3 -m collector.screen_comps --next --city calgary       # override the location city
"""

import os
import sys
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.connection import get_conn
from engine import settings as settings_mod
from dashboard import mapper
from collector.retail_comps import collect_facebook


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _sale_specs(conn, date_str: str, limit: int) -> list:
    """Distinct (year, make, model) specs for a sale's vehicles, in lot order, deduped."""
    seen, specs = set(), []
    for c in mapper.sale_contracts(conn, date_str, limit):
        raw = mapper.fetch_listing_from_db(c, conn)
        if not raw:
            continue
        v = mapper.parse_listing_to_vehicle(raw)
        yr, mk, md = (
            v.get("year"),
            (v.get("make") or "").upper(),
            (v.get("model") or "").upper(),
        )
        if not (yr and mk and md):
            continue
        key = (yr, mk, md)
        if key not in seen:
            seen.add(key)
            specs.append({"year": yr, "make": mk, "model": md})
    return specs


def screen_comps(
    date_str=None,
    specs=None,
    *,
    city=None,
    limit=300,
    min_have=8,
    per=20,
    max_queries=None,
    dry_run=False,
):
    conn = get_conn()
    settings_mod.apply_from_db(conn)  # match the dashboard's location/config
    city = city or (settings_mod.active_location().get("city") or "edmonton")
    province = (settings_mod.active_location().get("province") or "AB").upper()

    if specs is None:
        specs = _sale_specs(conn, date_str, limit)
    if not specs:
        _log("No vehicles/specs to warm. Nothing to do.")
        conn.close()
        return

    _log(
        f"Comp coverage · {len(specs)} distinct models · city {city} ({province}) · "
        f"min-have {min_have} · {per}/query{' · DRY RUN' if dry_run else ''}"
    )

    scraped = added = skipped = failed = 0
    for i, s in enumerate(specs, 1):
        if max_queries is not None and scraped >= max_queries:
            _log(f"Reached --max-queries {max_queries}; stopping.")
            break
        tag = f"({i}/{len(specs)}) {s['year']} {s['make']} {s['model']}"
        have = mapper._retail_comp_count(conn, s)
        if have >= min_have:
            skipped += 1
            _log(f"{tag} — have {have} comps ≥ {min_have}, skip")
            continue
        if dry_run:
            _log(f"{tag} — have {have} comps, WOULD scrape FB")
            continue
        query = s["model"] if s["make"] in s["model"] else f"{s['make']} {s['model']}"
        try:
            n = collect_facebook(
                city,
                query,
                max_listings=per,
                min_year=s["year"] - 3,
                max_year=s["year"] + 3,
            )
            scraped += 1
            added += n
            _log(
                f"{tag} — had {have}, scraped {n} (now ~{mapper._retail_comp_count(conn, s)})"
            )
        except Exception as e:  # noqa: BLE001 — no token / network / actor: keep going
            failed += 1
            _log(f"{tag} FAILED: {e}")
        time.sleep(float(os.getenv("COMPS_DELAY_S", "1.0")))

    _log(
        f"DONE · models {len(specs)} · scraped {scraped} · listings added {added} · "
        f"skipped {skipped} · failed {failed}{' · DRY RUN' if dry_run else ''}"
    )
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Warm the retail comp pool for an upcoming sale (manual)."
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", help="Sale date YYYY-MM-DD (Tuesday or Saturday)")
    g.add_argument("--next", action="store_true", help="The soonest upcoming sale")
    g.add_argument("--make", help="Ad-hoc: one model (needs --model --year)")
    ap.add_argument("--model", help="Ad-hoc model (with --make --year)")
    ap.add_argument("--year", type=int, help="Ad-hoc year (with --make --model)")
    ap.add_argument(
        "--city",
        default=None,
        help="Override the FB search city (default: active location)",
    )
    ap.add_argument(
        "--limit", type=int, default=300, help="Max sale vehicles to consider"
    )
    ap.add_argument(
        "--min-have",
        type=int,
        default=8,
        help="Skip models already at/above this many comps",
    )
    ap.add_argument(
        "--per", type=int, default=20, help="Listings to pull per model query"
    )
    ap.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="Cap total FB scrapes (cost guard)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the plan + current coverage; no scraping",
    )
    a = ap.parse_args()

    specs = None
    date_str = None
    if a.make:
        if not (a.model and a.year):
            print("--make needs --model and --year")
            sys.exit(1)
        specs = [{"year": a.year, "make": a.make.upper(), "model": a.model.upper()}]
    else:
        conn0 = get_conn()
        date_str = (
            mapper.sales(conn0)[0]["date"] if a.next and mapper.sales(conn0) else a.date
        )
        conn0.close()
        if not date_str:
            print("No upcoming sale found.")
            sys.exit(1)

    screen_comps(
        date_str,
        specs,
        city=a.city,
        limit=a.limit,
        min_have=a.min_have,
        per=a.per,
        max_queries=a.max_queries,
        dry_run=a.dry_run,
    )
