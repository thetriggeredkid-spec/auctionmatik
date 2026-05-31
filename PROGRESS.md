# Auctionmatik — Build Progress

## Phase 1: Data Foundation ✅ COMPLETE

### Step 1: Data Sourcing — Regal Auctions ✅
- Primary source: Regal Auctions sold market report + active listings API
- Storage: Postgres 16 (Docker), JSONB raw_json preserved
- Schema: regal_sold, regal_listings, valuations

### Step 2: Methodology Codification ✅
- VALUATION_METHODOLOGY.md complete — 6 factor categories, delta model, max bid formula

### Step 3: Collectors ✅
- `collector/regal_market.py` — paginates sold records, upserts to regal_sold
- `collector/regal_listings.py` — paginates active listings, upserts to regal_listings (built)

### Step 4: Valuation Engine ✅ COMPLETE
All modules built and syntax-verified. Max bid calculation validated against methodology doc example ($11,871 Wrangler case — exact match).

**`engine/comps.py`** — comp pool builder
- Primary match: year ±2, same make/model/driveline
- Fallback: year ±3, model-only
- Recency weighting: 30d = 3x, 90d = 1.5x, older = 1x
- Similarity scoring: trim match, year proximity, mileage proximity
- Returns: base_median (weighted), comp_count, confidence, odometer percentiles

**`engine/factors/mileage.py`** — mileage band vs. comp pool percentiles
- Bands: very_low (+8%), low (+3.5%), average (0%), high (-6%), very_high (-12%)

**`engine/factors/condition.py`** — grades 1–5 + damage items
- Exterior/Interior/Mechanical grade deltas vs. grade 3 baseline
- Damage deducted at 1.35x midpoint repair cost (buyer hassle premium)

**`engine/factors/history.py`** — accident claims, rebuilt title, service records, odometer integrity
- Claim deduction: ~41.7% of claim amount
- Near-total-loss (≥70% of vehicle value at time): compresses ceiling 25%, sets hard_to_sell
- Rebuilt title: -25%

**`engine/factors/options.py`** — options lookup table + mod tolerance by vehicle type
- 25 option types, capped at +12% total
- Mod tolerance: high (Wrangler) → very_low (luxury)

**`engine/factors/market_context.py`** — supply dynamics, seller urgency, days-on-market
- Supply bands, Finance Repo signal, dealer-at-auction signal
- DOM penalty: -0.2%/day after 14 days

**`engine/factors/location.py`** — Alberta-specific premiums
- 4WD/AWD: +3%, Diesel truck: +10%, Rust-free: +2%

**`engine/valuator.py`** — orchestrator
- Multiplies all factor deltas: adjusted = base × ∏(1 + δᵢ)
- Retail range: mid ±8% (±15% if low confidence)
- Wholesale: retail_mid × 0.82 ±5%
- Logs to valuations table

**`engine/max_bid.py`** — Regal fee schedule + GST
- Fee schedule: $285/$385/$535/$685/$835/$985 by price band
- 4 margin tiers, formula: (retail_mid − margin − fee) / 1.05

**`evaluate.py`** — main CLI
- `python3 evaluate.py --contract 37316`
- Fetches from DB or live API, prompts for condition, prints full report

---

## Next Actions
1. Run `docker compose up -d` to start Postgres
2. Run `python3 -m collector.regal_market --type Car --pages 3` to test collector
3. Run full backfill: `python3 -m collector.regal_market`
4. Run `python3 -m collector.regal_listings` to populate active listings
5. Test end-to-end: `python3 evaluate.py --contract <CONTRACT_NUMBER>`

## Phase 2: Refinement (future)
- Outcome tracking: fill actual_sale_price after auction results
- Factor weight calibration from outcome data (1,000+ transactions)
- Seasonal adjustments (12+ months of data)
- Vision model: damage detection from photos
