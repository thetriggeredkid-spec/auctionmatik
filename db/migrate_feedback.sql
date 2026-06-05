-- Auctionmatik — training / feedback loop
-- Human-in-the-loop corrections that the engine learns from:
--   listing_feedback : per-contract actual sale price + corrected valuation + notes
--   comp_feedback    : per-comp (retail listing) good/bad flag — bad comps are
--                      excluded from future anchors so a misread can't repeat.

CREATE TABLE IF NOT EXISTS listing_feedback (
    id                  SERIAL PRIMARY KEY,
    contract            VARCHAR(20) NOT NULL UNIQUE,

    -- vehicle identity snapshot (for calibration retrieval by make/model/year)
    year                SMALLINT,
    make                VARCHAR(50),
    model               VARCHAR(100),

    -- the engine's call at the time feedback was recorded (CAD cents)
    engine_verdict      VARCHAR(20),
    engine_value        INTEGER,
    engine_max_bid      INTEGER,

    -- the human correction (CAD cents)
    actual_sale_price   INTEGER,        -- what it actually sold for at auction
    corrected_value     INTEGER,        -- your true retail value
    corrected_max_bid   INTEGER,        -- what you'd have bid
    verdict_correct     BOOLEAN,        -- was the engine's verdict right?
    notes               TEXT,           -- what the engine missed / why

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listing_feedback_ymm ON listing_feedback (make, model, year);

CREATE TABLE IF NOT EXISTS comp_feedback (
    id                  SERIAL PRIMARY KEY,
    external_id         VARCHAR(100) NOT NULL UNIQUE,   -- retail_listings.external_id
    contract            VARCHAR(20),                    -- subject it was flagged on
    status              VARCHAR(10) NOT NULL DEFAULT 'bad',  -- 'bad' | 'good'
    reason              TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comp_feedback_status ON comp_feedback (status);
