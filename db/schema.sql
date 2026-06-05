-- Auctionmatik Database Schema
-- Phase 1: Regal Auctions foundation

-- Raw sold records from Regal market report API
-- Direct mapping of API fields — no transformation, preserve everything as-is
CREATE TABLE IF NOT EXISTS regal_sold (
    id                  SERIAL PRIMARY KEY,
    regal_id            VARCHAR(20) UNIQUE NOT NULL,   -- Regal's internal ID (e.g. "434156")
    contract            VARCHAR(20),                    -- Contract number (e.g. "34156")

    -- Vehicle identity
    year                SMALLINT,
    make                VARCHAR(50),
    model               VARCHAR(100),
    trim                VARCHAR(100),                   -- parsed from qamodel where possible
    body_style          VARCHAR(50),                    -- parsed from qamodel (e.g. "4D SEDAN")
    vin                 VARCHAR(17),
    color               VARCHAR(50),
    engine              VARCHAR(50),
    transmission        VARCHAR(20),
    driveline           VARCHAR(10),
    fuel_type           VARCHAR(20),
    vehicle_type        VARCHAR(30),                    -- Car / Truck / Sport Utility / Van / etc.
    odometer_km         INTEGER,                        -- normalized to KM integer

    -- Sale data
    sale_price          INTEGER NOT NULL,               -- CAD cents (e.g. 14500 -> 1450000)
    reserve_price       INTEGER,                        -- CAD cents
    sold_date           DATE,
    seller_type         VARCHAR(50),                    -- Finance Repo / Fleet / Dealer / Private / etc.
    declarations        VARCHAR(50),                    -- coded flags from Regal (e.g. "FR")

    -- Listing context
    options_text        TEXT,                           -- raw options string
    condition_notes     TEXT,                           -- "other" field — auctioneer notes
    photo_count         SMALLINT,
    carproof_available  BOOLEAN DEFAULT FALSE,
    main_photo_url      TEXT,

    -- Raw API payload — preserve everything
    raw_json            JSONB,

    -- Enrichment data (from regal_enrich.py — fetched from details page)
    -- Photo URLs at 800x600w from CloudFront
    photo_urls          TEXT[],
    -- Heat map damage layers: [{panel, severity}] e.g. [{panel:"left front door", severity:"yellow"}]
    -- severity: yellow=minor, orange=moderate, red=severe
    heat_map_damage     JSONB,
    -- Structured at-a-glance fields from details page
    -- {windshield, keys, starts, drivable, battery, tire_lf, tire_rf, tire_lr, tire_rr}
    condition_detail    JSONB,
    -- Carfax URL (constructed from id+vin, or scraped from details page)
    carfax_url          TEXT,
    -- Claude vision assessment of photos (Phase 2)
    -- {exterior_grade, interior_grade, damage_type_notes, condition_summary}
    vision_assessment   JSONB,
    enriched_at         TIMESTAMPTZ,

    -- Collection metadata
    collected_at        TIMESTAMPTZ DEFAULT NOW(),
    source              VARCHAR(20) DEFAULT 'regal_market_report'
);

CREATE INDEX IF NOT EXISTS idx_regal_sold_ymm    ON regal_sold (year, make, model);
CREATE INDEX IF NOT EXISTS idx_regal_sold_vin    ON regal_sold (vin);
CREATE INDEX IF NOT EXISTS idx_regal_sold_date   ON regal_sold (sold_date DESC);
CREATE INDEX IF NOT EXISTS idx_regal_sold_type   ON regal_sold (vehicle_type);

-- Current active Regal listings (upcoming auctions)
CREATE TABLE IF NOT EXISTS regal_listings (
    id                  SERIAL PRIMARY KEY,
    regal_id            VARCHAR(20) UNIQUE NOT NULL,
    contract            VARCHAR(20),

    -- Vehicle identity (same fields as regal_sold)
    year                SMALLINT,
    make                VARCHAR(50),
    model               VARCHAR(100),
    trim                VARCHAR(100),
    body_style          VARCHAR(50),
    vin                 VARCHAR(17),
    color               VARCHAR(50),
    engine              VARCHAR(50),
    transmission        VARCHAR(20),
    driveline           VARCHAR(10),
    fuel_type           VARCHAR(20),
    vehicle_type        VARCHAR(30),
    odometer_km         INTEGER,

    -- Listing data
    reserve_price       INTEGER,                        -- CAD cents
    seller_type         VARCHAR(50),
    declarations        VARCHAR(50),
    options_text        TEXT,
    condition_notes     TEXT,
    photo_count         SMALLINT,
    carproof_available  BOOLEAN DEFAULT FALSE,
    main_photo_url      TEXT,
    auction_date        DATE,
    status              VARCHAR(20),                    -- ACTIVE / SOLD / WITHDRAWN

    raw_json            JSONB,
    photo_urls          TEXT[],
    heat_map_damage     JSONB,
    condition_detail    JSONB,
    carfax_url          TEXT,
    vision_assessment   JSONB,
    enriched_at         TIMESTAMPTZ,
    first_seen_at       TIMESTAMPTZ DEFAULT NOW(),
    last_updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regal_listings_ymm   ON regal_listings (year, make, model);
CREATE INDEX IF NOT EXISTS idx_regal_listings_vin   ON regal_listings (vin);

-- Retail market listings — from Facebook Marketplace and Kijiji via Apify
-- These are the PRIMARY price anchor for retail valuation
CREATE TABLE IF NOT EXISTS retail_listings (
    id                  SERIAL PRIMARY KEY,
    external_id         VARCHAR(100) UNIQUE NOT NULL,    -- Apify listing ID (FB item ID or Kijiji listing ID)
    source              VARCHAR(20) NOT NULL,            -- 'facebook_marketplace' | 'kijiji'

    -- Vehicle identity
    year                SMALLINT,
    make                VARCHAR(50),
    model               VARCHAR(100),
    trim                VARCHAR(100),
    body_style          VARCHAR(50),
    vin                 VARCHAR(17),
    color               VARCHAR(50),
    engine              VARCHAR(50),
    transmission        VARCHAR(20),
    driveline           VARCHAR(10),
    fuel_type           VARCHAR(20),
    odometer_km         INTEGER,

    -- Listing data
    title               TEXT,
    asking_price        INTEGER NOT NULL,                -- CAD cents
    location_city       VARCHAR(100),
    location_province   VARCHAR(50),
    seller_type         VARCHAR(20),                     -- 'private' | 'dealer'
    listing_url         TEXT,
    description         TEXT,
    is_sold             BOOLEAN DEFAULT FALSE,
    posted_at           TIMESTAMPTZ,

    -- Listing photos (for vision assessment)
    photo_urls          TEXT[],
    photo_count         SMALLINT,
    main_photo_url      TEXT,

    -- Claude vision assessment of photos (structured clue extraction, retail_listings)
    vision_assessment   JSONB,

    -- Raw API payload
    raw_json            JSONB,

    -- Collection metadata
    collected_at        TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retail_ymm     ON retail_listings (year, make, model);
CREATE INDEX IF NOT EXISTS idx_retail_source  ON retail_listings (source);
CREATE INDEX IF NOT EXISTS idx_retail_price   ON retail_listings (asking_price);
CREATE INDEX IF NOT EXISTS idx_retail_sold    ON retail_listings (is_sold);
CREATE INDEX IF NOT EXISTS idx_retail_vin     ON retail_listings (vin);

-- Valuation outputs — one row per engine run
CREATE TABLE IF NOT EXISTS valuations (
    id                  SERIAL PRIMARY KEY,

    -- What was evaluated
    source_table        VARCHAR(30) NOT NULL,           -- 'regal_listings' or 'regal_sold'
    source_id           INTEGER NOT NULL,               -- FK to the source table row
    contract            VARCHAR(20),

    -- Engine version
    model_version       VARCHAR(20) NOT NULL DEFAULT '0.1',

    -- Comp pool used
    comp_count          INTEGER,
    comp_pool_desc      TEXT,                           -- e.g. "2015 Jeep Wrangler Unlimited 4WD — 8 comps (30d)"

    -- Output prices (CAD cents)
    base_median         INTEGER,                        -- comp pool median before adjustments
    retail_low          INTEGER,
    retail_mid          INTEGER,
    retail_high         INTEGER,
    wholesale_low       INTEGER,
    wholesale_mid       INTEGER,
    wholesale_high      INTEGER,

    -- Max bid outputs (CAD cents)
    max_bid_tier1       INTEGER,                        -- $1,500 margin
    max_bid_tier2       INTEGER,                        -- $2,500 margin
    max_bid_tier3       INTEGER,                        -- $3,500 margin
    max_bid_tier4       INTEGER,                        -- $5,000 margin

    -- Confidence
    confidence          VARCHAR(10),                    -- low / medium / high

    -- Full factor breakdown
    factor_breakdown    JSONB,                          -- [{factor, label, delta_pct, dollar_impact, reasoning}]

    -- Flags
    flags               JSONB,                          -- [{code, severity, message}] — hard-to-sell, rollback risk, etc.

    -- Outcome tracking (filled in later)
    actual_sale_price   INTEGER,
    outcome_notes       TEXT,
    outcome_recorded_at TIMESTAMPTZ,

    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_valuations_source ON valuations (source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_valuations_contract ON valuations (contract);
