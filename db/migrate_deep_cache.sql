-- Auctionmatik — persisted deep-appraisal cache
-- The overnight batch job (collector/screen_sale.py) writes full deep results here so
-- morning card-opens are instant. Keyed by (contract, profile). `inputs_hash` lets a
-- result auto-invalidate when its inputs change (overrides / declarations / km / carfax /
-- vision / settings version). `payload` is the design-shaped vehicle dict.

CREATE TABLE IF NOT EXISTS deep_cache (
    contract     VARCHAR(20) NOT NULL,
    profile      VARCHAR(40) NOT NULL,
    inputs_hash  TEXT,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (contract, profile)
);

CREATE INDEX IF NOT EXISTS idx_deep_cache_created ON deep_cache (created_at DESC);

-- Lightweight run log for overnight jobs (one row per screen_sale run).
CREATE TABLE IF NOT EXISTS screen_runs (
    id            SERIAL PRIMARY KEY,
    sale_date     DATE,
    profile       VARCHAR(40),
    total         INTEGER,
    triaged       INTEGER,
    deepened      INTEGER,
    failed        INTEGER,
    elapsed_s     NUMERIC,
    est_cost_usd  NUMERIC,
    notes         TEXT,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ DEFAULT NOW()
);
