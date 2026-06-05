# Auctionmatic Dashboard

The hi-fi web dashboard for the valuation engine — recreated from the Claude
Design handoff (**"Auctionmatic Detail.html"**: *The Lane* + the *Verdict Card*)
and wired to the live engine.

> Industrial-instrument cockpit · themeable (light/dark) · Hanken Grotesk +
> Spline Sans Mono. Two views: **The Lane** (screening table) and the **Verdict
> Card** (verdict hero → confidence gauge → the max-bid *derivation waterfall* →
> AI-vs-rules line → comps / past-sales / vision / repair / recon / declarations /
> verify / carfax panels).

### Comps vs. Past Sales (the two evidence tabs)

- **Comps** — the *retail* listings the engine anchored to (Facebook / Kijiji,
  from `retail_listings`), each with a click-through **link** to the original ad.
  These set the as-is retail value.
- **Past Sales** — actual *sold* results for similar units from `regal_sold`
  (year ±2, same make/model), with the realized auction price, sale date,
  condition tier, and a **link** to each Regal market-report entry. This is the
  realized-price dataset that grows as you collect more sold history.

## Run

```bash
docker compose up -d                  # Postgres must be up
source venv/bin/activate
pip install -r requirements.txt       # adds flask
python3 -m dashboard.server           # → http://127.0.0.1:8080
```

Open http://127.0.0.1:8080. **The Lane** is structured the way Regal runs it —
one **sale** at a time, soonest first. Only the two recurring sales are shown:
**Tuesday Timed Auctions** and **Saturday Super Sales** (any vehicle not in an
upcoming Tue/Sat sale is excluded). Within a sale, vehicles are listed in **lot
order**. Pick a sale from the selector; click any row to open its **Verdict
Card**, which auto-runs the appraisal for the selected **mode** and **profile**.

### Current vs. sold data

- **The Lane** = current upcoming-sale listings only (`regal_listings`, filtered
  to upcoming Tuesday/Saturday `auction_date`s).
- **Data points (comps)** = `regal_sold` (sold history) — the engine's comp pool.
  These never appear in the Lane.

Each sale screens the first N vehicles (by lot) with the fast deterministic
engine on open (cached); the rest show as `○ unscored` and are evaluated the
moment you open them. **Screen all** scores the remaining vehicles in the sale.

If the API is unreachable (e.g. you open `static/index.html` directly as a file),
the page falls back to the bundled sample cases in `static/data.js` — the exact
design prototype.

## Controls

- **lane / card** — switch between the screening table and the detail card.
- **triage / deep** — `triage` = deterministic engine + the fast Sonnet triage
  pass (~7s, ~$0.005). `deep` = the full agentic appraisal with narrated
  reasoning, key adjustments and escalation tools (~60–90s, ~$0.05). Deep panels
  (comps, vision, repair, recon, carfax) only show in `deep`.
- **charles / mechanic** — the buyer profile (margin floor, repair sourcing).
  Changing mode or profile re-runs the appraisal; **↻ Re-appraise** forces it.
- **dark / light** — theme, persisted to `localStorage`.

## API

| Endpoint | Description |
|---|---|
| `GET /api/health` | `{ok, db, ai}` — DB reachable, API key present |
| `GET /api/sales` | index of upcoming Tuesday/Saturday sales (soonest first) |
| `GET /api/sale?date=YYYY-MM-DD&screen=60\|all&profile=` | one sale's vehicles in lot order; first `screen` are scored |
| `GET /api/evaluate?contract=&mode=triage\|deep&profile=charles\|mechanic` | one full design-shaped vehicle |

## Layout

```
dashboard/
  server.py            # Flask: serves the SPA + /api/lane + /api/evaluate
  mapper.py            # engine output → the design's vehicle shape (the glue)
  static/
    index.html         # the Detail.html shell (loads the design + React/Babel)
    data.js            # bundled sample cases (offline fallback)
    hifi/
      system.css       # design system (verbatim from the handoff)
      viz.jsx          # hero · confidence gauge · waterfall · rules line (verbatim)
      panels.jsx       # tab panels + comps strip (verbatim)
      lane.jsx         # The Lane screening table (verbatim)
      app.jsx          # app shell — wired to the live API (the one adapted file)
```

`mapper.py` reuses the existing orchestration from `evaluate.py` (listing fetch,
anchor/comp-scrutiny, vision overlay) and the engine modules (`valuator`,
`advisor`, `declarations`, `repair_estimate`, `appraiser`), so the dashboard and
the CLI stay in sync.
