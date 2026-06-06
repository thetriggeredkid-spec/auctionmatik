# Auctionmatik — Claude Code Context

## What this project is
A behavioral pricing engine for used vehicles. The thesis: existing tools (KBB, MMR, Black Book)
price the *asset* with depreciation curves. Real transaction prices are set by behavioral and
contextual factors those tools ignore. This engine prices the *transaction*.

**Current focus:** the **web dashboard** over the Regal Auctions evaluator — screen an upcoming
auction lane, open any vehicle, and get a verdict (BID / BID-TO-FIX / PASS), retail value, and max
bid, with the full reasoning. The dashboard is now the primary interface; the CLI still works.

## Read these first
- `PROGRESS.md` — current build status, direction, and next actions
- `VALUATION_METHODOLOGY.md` — the full pricing methodology spec (source of truth). Don't invent
  heuristics — follow it. NOTE: superseded in places by the June 2026 overhaul (AI-primary + two
  valuation modes + comp-scrutiny); the code is ahead of parts of this doc.
- `dashboard/README.md` — the dashboard architecture + how to run it

## Project owner
Charles. Domain expert (years of car flipping + dealership experience). He defines the methodology;
the code implements his expertise. When the methodology is vague, **flag it — don't guess.** When a
miss is systemic (logic/factor/prompt), he reports it in chat for a framework fix; one-off corrections
go in the dashboard's **Correct** tab (which feeds the AI as calibration).

## Architecture (AI-primary hybrid)
The engine is **AI-primary**: `engine/appraiser.py` (Claude **Sonnet 4.6**) reasons to the valuation
the way Charles does, from assembled evidence. The deterministic rules engine (`engine/advisor.py`)
runs alongside as a **sanity band** the AI reconciles against. Two AI modes:
- **triage** — fast/cheap screen (lean JSON, brief rationale).
- **deep** — full agentic appraisal: adaptive thinking, narrated reasoning, on-demand escalation
  tools (refine repair quote / get carfax / fetch more comps), and operator-correction calibration.

In the dashboard, **triage = the deterministic result** (instant, matches the lane); **deep = the AI
pass**. Evidence is assembled by the deterministic pipeline below.

## Tech stack
- Python 3, PostgreSQL 16 (Docker), `venv` (`source venv/bin/activate`)
- `psycopg2-binary`, `requests`, `python-dotenv`, `beautifulsoup4`, `lxml`
- `anthropic` (Sonnet 4.6 reasoning, Haiku 4.5 vision), `apify-client` (FB/Kijiji scraping),
  `flask` (dashboard), `playwright` (local Carfax agent)
- `.env` holds `ANTHROPIC_API_KEY`, `APIFY_TOKEN`, `POSTGRES_*` (gitignored)

## Database
- `docker compose up -d` → Postgres on **localhost:5433** (container maps 5433→5432; `.env` sets
  `POSTGRES_PORT=5433`). DB/User `auctionmatik`, password in `.env`.
- Base schema in `db/schema.sql` (auto-runs on first up). Migrations applied manually:
  `db/migrate_enrichment.sql`, `db/migrate_feedback.sql`.
- Tables:
  - `regal_sold` — sold auction history → **wholesale comp pool (data points)**
  - `regal_listings` — active listings → **the lane** (current upcoming sales)
  - `retail_listings` — Facebook/Kijiji listings → **retail price anchor**
  - VMR Canada (live fetch, not stored) → **published book-value sanity check** (`collector/vmr.py`)
  - `valuations` — logged engine runs
  - `listing_feedback`, `comp_feedback` — the training/feedback loop (corrections + bad comps)
  - `listing_overrides` — operator input corrections (trim/cab/km/grades/declarations)
  - `app_settings` — editable config overrides (profiles, margins, fees, GST, toggles); see `engine/settings.py`

## Project structure
```
collector/
  regal_market.py     # sold history → regal_sold
  regal_listings.py   # active listings → regal_listings (parses lot, sale_date)
  regal_enrich.py     # per-listing gallery photos + carfax_url + condition detail
  retail_comps.py     # FB Marketplace + Kijiji via Apify → retail_listings
  carfax_agent.py     # headless Playwright + vision (tiled) → carfax_report
  vmr.py              # VMR Canada book value (static HTML fetch + km formula) — sanity check

db/
  connection.py       # get_conn / get_cursor (RealDictCursor)
  schema.sql · migrate_enrichment.sql · migrate_feedback.sql

engine/
  appraiser.py        # AI BRAIN (Sonnet 4.6) — triage/deep, tools, playbook, calibration
  advisor.py          # deterministic rules engine → verdict/max-bid (the sanity band)
  comps.py            # wholesale comp pool from regal_sold (cab-aware similarity)
  comp_scrutiny.py    # per-comp reasoning over retail listings (km-norm, DOM, title, cab)
  declarations.py     # decode Regal codes (FD/RS/MP/HD/CH####/TI/...) + remark signals
  valuation_modes.py  # Mode A (retail flip) vs Mode B (repair project) router
  repair_estimate.py  # components → repair quote (profile-aware sourcing + buffer)
  vision.py · vision_factors.py   # Haiku/Sonnet photo assessment → spec
  valuator.py · max_bid.py · factors/   # original deterministic factor engine (Phase 1)

dashboard/
  server.py           # Flask: serves the SPA + JSON API
  mapper.py           # engine output → the design's vehicle shape (the glue)
  static/             # hi-fi React-over-Babel UI (recreated from Claude Design handoff)
    index.html · data.js (sample) · hifi/{system.css,viz,panels,lane,app}.jsx

evaluate.py           # CLI: python3 evaluate.py --contract 37316 [--ai --deep --auto]
```

## The dashboard
Run: `source venv/bin/activate && python3 -m dashboard.server` → http://127.0.0.1:8080
- **The Lane** — structured like Regal: one **sale** at a time (only upcoming **Tuesday Timed
  Auctions** + **Saturday Super Sales**), vehicles in **lot order**, screened deterministically.
- **Verdict Card** — identity + photo gallery → verdict hero → max-bid derivation waterfall →
  AI-vs-rules line → tabs: Reasoning · Comps · Past Sales · Vision · Repair · Recon · Declarations ·
  Verify · Carfax · Correct.
- **Comps** = retail listings (with photo + link); **⚑ flag** a bad comp to exclude it forever.
- **Past Sales** = actual `regal_sold` results for similar units (with Regal links).
- **Carfax** = working link + manual entry + **⟳ Auto-pull** (local agent); deep runs auto-pull when
  missing (`DASHBOARD_CARFAX_AUTOPULL=0` to disable).
- **Correct** = record actual sale + the right call → stored in `listing_feedback` → injected into
  the AI as calibration on future similar vehicles.

## Key methodology rules (summary — read the full doc)
- Value from **comp scrutiny**, not blind median: reason per-comp (condition, km, title, days-unsold);
  a cheap/stale comp is often cheap because it's **damaged** — don't treat it as a clean floor.
- **Mode A** (retail flip): as-is comp value − recon − margin. **Mode B** (repair project): after-fix
  value (rebuilt ≈ ×0.78) − repair − margin; if repair > after-fix → parts-only/PASS.
- Claims: deduction is a **fraction** of the claim that shrinks the cheaper the car (Carfax overrides
  the `CH####` band). Trucks: **cab/bed/trim/engine/4x4 are primary value drivers** — match comps on them.
- Prices stored in CAD cents internally, shown as dollars.
- Max bid = (target_sale − recon/repair − margin − Regal_fee) / 1.05 (5% GST), floored at 0.

## Margin tiers · Regal buyer fees
- Margin (by sell price): <$15k → $1,500 · $15–20k → $2,500 · $20–35k → $3,500 · $35k+ → $5,000
  (profile-aware floor; Charles $1,500, scales with capital)
- Buyer fee: $0–5k $285 · 5–10k $385 · 10–15k $535 · 15–25k $685 · 25–40k $835 · 40k+ $985

## Buyer profiles
- **charles** (flipper): margin floor $1,500, low hold-time, +20% repair buffer, middle sourcing
- **mechanic** (DIY): margin floor $800, holds back less, used-parts/DIY repair sourcing

## Reference cases (validate against these)
- 2015 Jeep Wrangler, contract 37316 — Charles: retail ~$14,500, max bid ~$12,300. Engine: BID ~$14k/$11k.
- Pathfinder (CVT, high km) → PASS + conditional bid. Equinox (frame/salvage) → BID-TO-FIX (Mode B).

## Code principles
- AI output is schema-guaranteed JSON; deterministic factors return `{delta_pct, dollar_impact,
  reasoning}` — no black boxes.
- Don't change methodology weights/prompts without flagging first.
- Keep modules independently testable; the dashboard `mapper.py` reuses `evaluate.py` helpers so CLI
  and dashboard stay in sync.
- Models: default to the latest Claude (`claude-sonnet-4-6` reasoning, `claude-haiku-4-5` vision);
  don't downgrade without being asked.
- **Keep the docs current.** After every major change (new feature, framework/methodology change,
  schema/migration, new module or CLI, changed run steps), update `PROGRESS.md` in the same change —
  and any other `.md` that's now stale (`CLAUDE.md`, `dashboard/README.md`, `VALUATION_METHODOLOGY.md`,
  `TESTING.md`). This is how we avoid losing progress across sessions: a fresh context window should be
  able to orient from the docs alone. Record what changed, where it lives, and what's next; move the
  item from "next actions" to "done." Skip only for trivial edits (typos, comments, one-off fixes).
