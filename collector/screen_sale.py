"""
Overnight batch deep-screener.

Pre-computes deep appraisals for a whole upcoming sale and caches them (deep_cache)
so morning card-opens in the dashboard are instant. Runs SEQUENTIALLY (avoids the
429 storm concurrent Sonnet calls caused), is RESUMABLE (skips fresh cache unless
--force), and bounds cost with a TRIAGE PRE-FILTER: triage every car (cheap), then
deep-dive only the buy candidates + thin-evidence ones.

Usage:
    python3 -m collector.screen_sale --date 2026-06-06
    python3 -m collector.screen_sale --date 2026-06-06 --profile charles --limit 200
    python3 -m collector.screen_sale --date 2026-06-06 --all-deep        # deep every car
    python3 -m collector.screen_sale --date 2026-06-06 --comps           # also scrape comps ($)
    python3 -m collector.screen_sale --date 2026-06-06 --dry-run         # plan only, no AI
    python3 -m collector.screen_sale --next                              # the soonest sale

Settings (edited in the dashboard) are applied first, so results match the dashboard.
"""

import os
import sys
import time
import argparse
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.connection import get_conn, get_cursor
from engine import settings as settings_mod
from dashboard import mapper

# Sonnet 4.6 $/1M tokens — for a rough cost tally.
_PIN, _PCACHE, _POUT = 3.0, 0.30, 15.0
DEEP_VERDICTS = {"BID", "BID_TO_FIX"}


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _next_sale_date(conn) -> str | None:
    sales = mapper.sales(conn)
    return sales[0]["date"] if sales else None


def _est_cost(v: dict) -> float:
    m = (v or {}).get("meta") or {}
    t = m.get("tokens") or {}
    return (t.get("in", 0) * _PIN + t.get("cache", 0) * _PCACHE + t.get("out", 0) * _POUT) / 1e6


def screen_sale(date_str, *, profile="charles", limit=300, all_deep=False, comps=False,
                force=False, max_deep=None, dry_run=False):
    conn = get_conn()
    settings_mod.apply_from_db(conn)   # match the dashboard's edited config

    contracts = mapper.sale_contracts(conn, date_str, limit)
    if not contracts:
        _log(f"No Tuesday/Saturday sale on {date_str} (or no vehicles). Nothing to do.")
        conn.close()
        return

    started = datetime.now()
    t0 = time.time()
    _log(f"Screening {len(contracts)} vehicles · sale {date_str} · profile {profile} · "
         f"{'ALL-DEEP' if all_deep else 'triage→deep filter'}{' · +comps' if comps else ''}"
         f"{' · DRY RUN' if dry_run else ''}")

    triaged = deepened = failed = skipped = 0
    cost = 0.0

    for i, c in enumerate(contracts, 1):
        tag = f"({i}/{len(contracts)}) #{c}"

        # Resume: skip if a fresh deep result already exists.
        if not force:
            try:
                v0 = mapper.fetch_listing_from_db(c, conn)
                veh = mapper.parse_listing_to_vehicle(v0) if v0 else {}
                ov = mapper.get_overrides(conn, c)
                mapper._apply_overrides(veh, ov)
                h = mapper._inputs_hash(conn, c, profile, veh, ov)
                if mapper.get_deep_cache(conn, c, profile, h):
                    skipped += 1
                    _log(f"{tag} skip — fresh deep result cached")
                    continue
            except Exception:  # noqa: BLE001
                pass

        if dry_run:
            _log(f"{tag} would screen")
            continue

        try:
            if all_deep:
                v = mapper.evaluate(conn, c, profile=profile, ai_mode="deep",
                                    use_deep_cache=False, store_deep=True)
                deepened += 1
                cost += _est_cost(v)
                _log(f"{tag} DEEP → {v.get('verdict')} ${v.get('maxBid'):,}")
            else:
                # cheap triage to decide deep-worthiness
                t = mapper.evaluate(conn, c, profile=profile, ai_mode="triage",
                                    use_deep_cache=False, store_deep=False)
                triaged += 1
                cost += _est_cost(t)
                worth = (t.get("verdict") in DEEP_VERDICTS) or t.get("needsDeep")
                if worth and (max_deep is None or deepened < max_deep):
                    if comps and (not t.get("comps") or t["comps"].get("empty")):
                        try:
                            mapper.fetch_comps(conn, c, profile=profile)
                        except Exception as e:  # noqa: BLE001
                            _log(f"{tag} comps scrape failed: {e}")
                    v = mapper.evaluate(conn, c, profile=profile, ai_mode="deep",
                                        use_deep_cache=False, store_deep=True)
                    deepened += 1
                    cost += _est_cost(v)
                    _log(f"{tag} {t.get('verdict')} → DEEP → {v.get('verdict')} ${v.get('maxBid'):,}")
                else:
                    _log(f"{tag} {t.get('verdict')} — no deep (not a buy candidate)")
        except Exception as e:  # noqa: BLE001
            failed += 1
            _log(f"{tag} FAILED: {e}")

        time.sleep(float(os.getenv("SCREEN_DELAY_S", "1.0")))   # gentle on rate limits

    elapsed = round(time.time() - t0, 1)
    _log(f"DONE · triaged {triaged} · deep {deepened} · skipped {skipped} · failed {failed} "
         f"· {elapsed}s · ~${cost:.2f}")

    if not dry_run:
        try:
            cur = get_cursor(conn)
            cur.execute("""INSERT INTO screen_runs (sale_date, profile, total, triaged, deepened,
                           failed, elapsed_s, est_cost_usd, started_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (date_str, profile, len(contracts), triaged, deepened, failed,
                         elapsed, round(cost, 2), started))
            conn.commit(); cur.close()
        except Exception as e:  # noqa: BLE001
            _log(f"(run log not written: {e})")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Overnight batch deep-screener for a Regal sale")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", help="Sale date YYYY-MM-DD (Tuesday or Saturday)")
    g.add_argument("--next", action="store_true", help="The soonest upcoming sale")
    ap.add_argument("--profile", default="charles")
    ap.add_argument("--limit", type=int, default=300, help="Max vehicles (by lot order)")
    ap.add_argument("--all-deep", action="store_true", help="Deep every car (skip the triage filter)")
    ap.add_argument("--comps", action="store_true", help="Scrape FB comps for buy candidates ($ Apify)")
    ap.add_argument("--max-deep", type=int, default=None, help="Cap how many deep appraisals to run")
    ap.add_argument("--force", action="store_true", help="Re-run even if a fresh deep result is cached")
    ap.add_argument("--dry-run", action="store_true", help="Show the plan; no AI calls")
    a = ap.parse_args()

    conn0 = get_conn()
    d = _next_sale_date(conn0) if a.next else a.date
    conn0.close()
    if not d:
        print("No upcoming sale found."); sys.exit(1)

    screen_sale(d, profile=a.profile, limit=a.limit, all_deep=a.all_deep, comps=a.comps,
                force=a.force, max_deep=a.max_deep, dry_run=a.dry_run)
