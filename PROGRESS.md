# Auctionmatik — Build Progress

> Quick orientation for a fresh context window. See `CLAUDE.md` for architecture,
> `dashboard/README.md` for the UI, `VALUATION_METHODOLOGY.md` for the spec.

## Where we are
A working **AI-primary valuation engine** with a **web dashboard** over Regal Auctions. You can
screen an upcoming sale, open any vehicle, and get verdict + retail value + max bid with full
reasoning, plus a human-in-the-loop training loop. Decent starting ground; calibrating from here.

---

## Phase 1 — Deterministic foundation ✅
- Postgres (Docker, **port 5433**); `regal_sold`, `regal_listings`, `valuations`.
- Collectors: `regal_market.py` (sold), `regal_listings.py` (active, parses lot + sale_date).
- Factor engine: `engine/comps.py`, `factors/*`, `valuator.py`, `max_bid.py`.

## Phase 2 — AI-primary hybrid + richer evidence ✅
- **`engine/appraiser.py`** — Sonnet 4.6 brain; triage + deep (agentic, tools, playbook). Rules
  engine is the sanity band. Speed funnel tuned (~7s triage, ~50–90s deep).
- **`engine/advisor.py`** — deterministic verdict/max-bid, two buyer profiles (charles, mechanic).
- **`engine/comp_scrutiny.py`** — per-comp reasoning over retail listings (km-norm, DOM discount,
  title exclusion, cab-aware).
- **`engine/declarations.py`** — Regal code decoder (FD/RS/MP/HD/CH####/TI/OOP/UNX/FR…).
- **`engine/valuation_modes.py`** — Mode A (retail flip) vs Mode B (repair project).
- **`engine/repair_estimate.py`** — profile-aware repair sourcing + buffer.
- **`engine/vision.py` / `vision_factors.py`** — Haiku/Sonnet photo assessment → spec.
- **`collector/retail_comps.py`** — FB Marketplace + Kijiji via Apify → `retail_listings`.
- Validated on Jeep 37316 (BID ~$14k/$11k), Pathfinder (PASS+conditional), Equinox (BID-TO-FIX).

## Phase 3 — Dashboard + feedback loop + Carfax ✅
- **`dashboard/`** — Flask + React-over-Babel hi-fi UI (recreated from the Claude Design handoff
  "Auctionmatic Detail.html"). `server.py` + `mapper.py` (glue, reuses `evaluate.py`).
- **The Lane** — structured like Regal: upcoming **Tuesday Timed Auctions** + **Saturday Super
  Sales** only, one sale at a time, **lot order**, deterministic screening (cached).
- **Verdict Card** — photo gallery, verdict hero, max-bid waterfall, AI-vs-rules line, all panels.
- **Comps tab** — retail comps with photo + link; **⚑ flag bad comps** → excluded forever.
- **Past Sales tab** — actual `regal_sold` results for similar units, with Regal links.
- **Carfax** — working link + manual entry + **⟳ Auto-pull** (`collector/carfax_agent.py`,
  local Playwright + vision); **deep auto-pulls** when missing. Verified locally end-to-end.
- **Correct tab** + `listing_feedback`/`comp_feedback` tables — record actual sale + the right call;
  corrections feed the AI as **calibration**; flagged comps drop from anchors. (`db/migrate_feedback.sql`)
- Truck spec (trim/cab/bed/engine) recovered from `raw_json` and used in comps + AI.

---

## How to run
```bash
docker compose up -d
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium                 # for local Carfax auto-pull (uses your Chrome)
python3 -m dashboard.server                 # → http://127.0.0.1:8080
# CLI still works: python3 evaluate.py --contract 37316 --deep
```
Keep data fresh: `python3 -m collector.regal_listings` (lane), `regal_market` (sold comps),
`retail_comps --query "<make model>"` (retail anchors), `regal_enrich` (photos/carfax_url).

Backups: `./scripts/backup_db.sh` (gzipped `pg_dump` → `backups/`, keeps last 14; `KEEP=N` to change).
Restore: `./scripts/restore_db.sh [file]` (defaults to newest). `backups/` is gitignored (holds data).
DB is local Docker Postgres (32 MB, ~12.5k rows) — fine for now; revisit hosted (Supabase/Neon) only
when building the Chrome extension or needing off-Mac / multi-user access.

## Current direction / next actions
0. **Personal sold log → realized comps** ✅ (`db/migrate_personal_sales.sql`) — hand-entered past
   sales (year/make/model/trim/km/condition/sale price/date) via the top-bar **◉ sold log** view
   (`/api/personal_sales` GET/POST/DELETE). They join the deep-mode comp pool as **realized comps**:
   `comp_scrutiny` weights them above scraped asks (+0.30 similarity), skips the days-on-market
   discount (a sale isn't an ask), never trims them as price outliers, and labels them **SOLD · full
   weight** in the Comps tab + "YOUR SALE" in the AI narrative. This is the highest-leverage data we
   can add — real transaction prices that both anchor deep mode and seed retail calibration as they
   accumulate. Adding/deleting one invalidates the det + deep caches. **Backlog toward the goal:**
   the remaining Tier-1 items are *comp-data quality fixes* (km/posted_at/Kijiji — many scrutiny
   levers are inert without them) and *vision on comps*; then VIN decode + recency weighting (Tier 2).
0b. **Comp km parser — robustness + bug fix** ✅ (`collector/retail_comps._parse_km_text`) — fixed a
   real bug where European-style `72.000 km` parsed as **72 km**; now handles `139k`, `72 000`,
   `12.5k`, miles→km, sanity-bounds 100–1,000,000, and falls back to title/description when the
   subtitle block is absent. **Diagnosis that matters more than the fix:** the km gap is NOT a parser
   problem — only **26%** of FB rows are detail-scraped (have a subtitle block), and of those **95%**
   already get km. The other 74% are search-level rows with no subtitle/description/km at all. Kijiji
   isn't broken either (all 3 rows have km) — it's just been run once. So growing comp coverage is an
   **operational** task: re-pull with `includeListingDetails` + run Kijiji broadly for the lane's
   makes/models. The parser fix only helps detail-scraped rows + all future scrapes.
1. **Calibrate from the sale** — the loop is now **two-track + deep-aware** (see "Calibration split
   into two tracks" below). Remaining: (a) **accumulate deep/retail corrections** — open vehicles,
   run **deep**, record the true value in the Correct tab so Track 1 fills up (only 1 outcome so far);
   (b) once there's volume, mine Track 1 for recurring patterns → framework fixes; flag bad comps.
   **Blocked-ish on data:** the retail comp pool is thin (980 listings, only 251 with km, almost no
   Kijiji) — growing it is a *separate effort* but caps how accurate deep can get.
2. **Vision on comps** ✅ — the systematic version of the manual ⚑ flag. Two parts:
   (A) *consume* — `comp_scrutiny` reads each comp's stored `vision_assessment`: a clearly-damaged
   comp (flood/frame, exterior grade ≤2, severe damage, severe rust) is **excluded from the clean
   anchor** like a rebuilt title (it's cheap BECAUSE it's wrecked, not a clean floor); a moderately
   rough one is down-weighted. Vision beats listing-text keywords. A realized sale is never excluded.
   `_advisor_anchor` now selects + decodes `vision_assessment` per comp. (B) *produce* — deep-only
   `_maybe_vision_comps` runs the cheap Haiku pass on a bounded set of matching comps that have photos
   but no assessment, gated by the new **`deep_vision_comps`** setting (default **OFF** — extra Haiku
   calls + latency; toggle in Settings). Verified: injecting a flood/frame read on a comp drops it
   from the anchor with the right reason. Remaining caveat: only ~26% of comps have photo galleries
   (collection depth), so Part B's reach is capped until the comp pool is deepened.
2b. **VIN decode (NHTSA)** ✅ (`db/migrate_vin_decode.sql`, `collector/vin_decode.py`) — methodology
   §3.1. Decodes the VIN via the free NHTSA vPIC API (no key), normalizes to our spec keys
   (driveline/engine/cab/bed/fuel/trim←Trim|Series), and **caches** in `vin_decode` (one fetch per VIN).
   `evaluate.apply_vin_decode` **gap-fills only blank** spec fields — present scrape values and
   operator overrides always win — and is called in both the dashboard (`mapper.evaluate`, after parse,
   before vision) and the CLI. Live NHTSA fetch happens off the lane (`ai_mode` set / card open); bulk
   lane screening serves cache only so it stays fast. Gated by the **`vin_decode`** setting (default ON,
   Settings toggle); the Inputs tab shows which fields the VIN filled (`vinFilled`). Verified live:
   driveline/engine/cab/fuel decode reliably; **trim is often blank from NHTSA** (we fall back to Series
   and otherwise leave the scrape's trim) — so it hardens the reliable fields, not trim. The biggest
   win is on sparse Regal scrapes (missing driveline/engine), which now fill from the factory build.
3. **Carfax on a server** — current local agent works; the planned **Chrome extension** version
   sidesteps reCAPTCHA. (Hybrid worker / managed scraping browser are the server-side options.)
4. Optional: collector to store trim/body columns on scrape; per-vehicle "Load photos" enrichment;
   concurrency-safe lane screening; Settings/profile editor.

### Done (post-QA, June)
- **Deep-run streaming** — SSE `/api/evaluate_stream`; live stage checklist + elapsed timer on the
  card (comp screening → Carfax → photos → VMR → AI appraising + its tool calls).
- **Editable inputs + re-appraise** (A1) — the **Inputs** tab edits trim/cab/bed/driveline/engine/km,
  condition grades, declarations & remarks; persisted per contract (`listing_overrides`,
  `db/migrate_overrides.sql`), applied on every eval (lane + deep), with Reset-to-scraped.
- **Calibration dashboard** (C6) — top-bar **◎ calibration** view: engine vs reality from recorded
  corrections (`listing_feedback`). Retail-value & max-bid MAE + signed bias, verdict accuracy,
  bias **by make** and **by price band**, a per-sample table (click → open card), CSV export
  (`/api/calibration`, `/api/calibration.csv`). Use it to find systematic error for the methodology rewrite.
- **Calibration split into two tracks** (`db/migrate_feedback_mode.sql` — adds `engine_mode` to
  `listing_feedback`). The dashboard previously *mixed* two incompatible truths into one bias number;
  now they're separated and the loop is **deep-aware**:
  - **Track 1 — Deep / retail corrections** (the signal that matters): your **Correct**-tab entries,
    engine value vs your corrected retail value. Each feedback row now records the **mode** that
    produced the call (`deep`/`triage`/`rules`), so we can confirm we're scoring the deep pass. The
    Correct tab nudges you to run **deep** before correcting.
  - **Track 2 — Wholesale backtest** (a triage/comp-engine baseline): the auto-imported
    `collector.import_outcomes` rows (tagged `engine_mode='auto'`), engine max bid vs actual Regal
    hammer price. Clearly labeled **margin-affected** (the bid sits below the hammer by design) and
    built off the shoddy wholesale data — NOT a measure of deep accuracy.
  Each track has its own make/band segments + verdict accuracy + mode breakdown so they never pollute
  each other (`mapper.calibration()`); CSV gains `track` + `engine_mode` columns. **Why the split
  matters:** triage rides the wholesale Regal data and is expected-weak; deep/retail is where accuracy
  lives but is data-starved (1 logged outcome). Calibrating from real sales = log deep corrections.
- **Prep-this-sale** (B4) — lane **⚙ Prep sale** runs a bounded, idempotent background batch
  (photos+vision default; Carfax/comps opt-in) over the first N by lot, with live progress + cancel.
- **Settings / profile editor** — top-bar **⚙ settings** view: editable **buyer profiles**
  (add/rename/remove), **margin tiers**, **Regal fee schedule**, **GST**, and **engine toggles**
  (deep auto-Carfax/vision, vision cap, prep default). Stored as overrides on hardcoded defaults
  (`app_settings`, `db/migrate_settings.sql`, `engine/settings.py`); applied live to advisor +
  max_bid + vision on save/startup; the AI playbook gets the live tiers/fees/GST injected so its
  reasoning matches the rules engine. Reset-to-defaults supported. Profile toggle is now dynamic.

### Done — Overnight batch-deep automation (June)
- **Persisted deep cache** (`deep_cache`, `db/migrate_deep_cache.sql`) keyed by (contract, profile)
  with an **inputs-hash** (overrides/declarations/km/spec/carfax/vision presence/settings version).
  `evaluate(ai_mode="deep")` serves a fresh cached result instantly; stores after computing.
- **Invalidation**: editing inputs / carfax / vision / flagging a comp drops that contract's deep
  cache; a settings change clears all.
- **`collector/screen_sale.py`** — sequential, resumable batch CLI: `--date|--next`, triage→deep
  filter (deep only BID/BID-TO-FIX/needs-deep) or `--all-deep`, `--comps`, `--max-deep`, `--force`,
  `--dry-run`. Applies saved settings; logs to `screen_runs`; bumped SDK retries + inter-call delay.
- **`scripts/overnight_screen.sh`** — backup → `caffeinate` → screen the next sale (cron/launchd).
- **Lane "deep ✓"** badge on pre-screened rows; deep stream short-circuits to the cached result.
- Verified end-to-end: 1-car deep run cached a 13.5KB payload (63.7s/$0.04), re-served in 0.00s,
  invalidated correctly on override.

**NOT scheduled yet (intentionally).** The batch runs only when invoked manually
(`python3 -m collector.screen_sale --next --dry-run`). Hold off on a cron/launchd
schedule until the valuation methodology is refined — then add the cron line in
`scripts/overnight_screen.sh`'s header.

### From QA pass (June, deferred — bigger items)
- **Triage under/over-fit flag** on the lane (low comp SIM / uncertain trim) so users know which
   rows are worth a deep run (the deep-mode trim catch is currently hidden behind a ~75s wait).
- **Deep-run streaming/progress** (already listed) + comp-flag **undo + "anchor recalculated" toast**.
- **Declaration glossary** expansion (codes like `AA` still resolve to "unrecognized" — needs Charles's
   meanings) + a lane-level **verdict-vs-VMR-vs-PastSales divergence** column to spot outliers.
- **Photo coverage** — many listings only have the cover; richer enrichment / fallback image.

### Fixed in QA pass (June)
Moved project out of ~/Downloads (macOS TCC was blocking all file reads → 500s); hardened `/` to
serve from memory; re-price handlers now merge the full vehicle (no stale summary after flag/carfax/
vision/profile change); thesis sentence now includes Regal fee + GST; PASS waterfall shows a clean
"Below viable bid → PASS" instead of a positive "risk haircut"; Verify tab hidden when empty; lot
placeholders (NOTSET/RXXX) hidden; unrecognized declaration codes labelled cleanly; deep-banner
estimate corrected to ~60–90s; comp-flag now shows a re-pricing banner.

## Known reference case
2015 Jeep Wrangler, contract 37316 — Charles: retail ~$14,500, max bid ~$12,300. Validate against it.
