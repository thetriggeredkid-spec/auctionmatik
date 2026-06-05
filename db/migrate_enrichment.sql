-- Migration: Add enrichment columns to existing regal_sold and regal_listings tables
-- Run this once if your DB was created before regal_enrich.py was added:
--   docker compose exec db psql -U auctionmatik -d auctionmatik -f /dev/stdin < db/migrate_enrichment.sql

ALTER TABLE regal_sold
    ADD COLUMN IF NOT EXISTS photo_urls         TEXT[],
    ADD COLUMN IF NOT EXISTS heat_map_damage    JSONB,
    ADD COLUMN IF NOT EXISTS condition_detail   JSONB,
    ADD COLUMN IF NOT EXISTS carfax_url         TEXT,
    ADD COLUMN IF NOT EXISTS vision_assessment  JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at        TIMESTAMPTZ;

ALTER TABLE regal_listings
    ADD COLUMN IF NOT EXISTS photo_urls         TEXT[],
    ADD COLUMN IF NOT EXISTS heat_map_damage    JSONB,
    ADD COLUMN IF NOT EXISTS condition_detail   JSONB,
    ADD COLUMN IF NOT EXISTS carfax_url         TEXT,
    ADD COLUMN IF NOT EXISTS vision_assessment  JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at        TIMESTAMPTZ;

-- Also add retail_listings if not yet created
CREATE TABLE IF NOT EXISTS retail_listings (
    id                  SERIAL PRIMARY KEY,
    external_id         VARCHAR(100) UNIQUE NOT NULL,
    source              VARCHAR(20) NOT NULL,
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
    title               TEXT,
    asking_price        INTEGER NOT NULL,
    location_city       VARCHAR(100),
    location_province   VARCHAR(50),
    seller_type         VARCHAR(20),
    listing_url         TEXT,
    description         TEXT,
    is_sold             BOOLEAN DEFAULT FALSE,
    posted_at           TIMESTAMPTZ,
    raw_json            JSONB,
    collected_at        TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retail_ymm     ON retail_listings (year, make, model);
CREATE INDEX IF NOT EXISTS idx_retail_source  ON retail_listings (source);
CREATE INDEX IF NOT EXISTS idx_retail_price   ON retail_listings (asking_price);
CREATE INDEX IF NOT EXISTS idx_retail_sold    ON retail_listings (is_sold);
CREATE INDEX IF NOT EXISTS idx_retail_vin     ON retail_listings (vin);
