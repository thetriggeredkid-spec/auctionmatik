-- Auctionmatik — human input overrides
-- Operator corrections to a listing's INPUTS (trim, cab/bed, km, condition grades,
-- declarations, remarks). Applied on top of the scraped/vision spec on every eval,
-- so a fix (e.g. a missed trim) sticks and the lane + deep runs use it. Keyed by
-- contract; survives re-scrapes (separate from regal_listings).

CREATE TABLE IF NOT EXISTS listing_overrides (
    contract    VARCHAR(20) PRIMARY KEY,
    overrides   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
