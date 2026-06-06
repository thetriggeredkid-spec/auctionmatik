-- Auctionmatik — your own past sales as retail-truth comps.
--
-- A flipper's realized sale price is the BEST comp data we have: a real transaction,
-- not a hopeful asking price (methodology §1 — known sale prices are used at full weight).
-- These feed the comp-scrutiny pool weighted above scraped asks, and double as retail
-- ground truth as the set grows. Entered by hand in the dashboard "Sold log" view.

CREATE TABLE IF NOT EXISTS personal_sales (
    id            SERIAL PRIMARY KEY,

    -- vehicle identity (year/make/model required to match comps)
    year          SMALLINT,
    make          VARCHAR(50),
    model         VARCHAR(100),
    trim          VARCHAR(100),
    odometer_km   INTEGER,                 -- normalized to KM integer

    condition     VARCHAR(40),             -- free text: clean | rough | grade note, etc.
    sale_price    INTEGER NOT NULL,        -- CAD cents — what YOU sold it for (retail)
    sold_date     DATE,
    notes         TEXT,

    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_sales_ymm ON personal_sales (make, model, year);
