-- Auctionmatik — cached NHTSA vPIC VIN decodes.
--
-- The VIN is factory truth for build spec — driveline, engine, body, and (for trucks)
-- cab/bed, the primary value drivers. Methodology §3.1 calls for decoding it. We cache
-- each decode so we hit the free NHTSA API once per VIN, then gap-fill the vehicle spec
-- from it (filling only fields the scrape/vision left blank; operator overrides still win).

CREATE TABLE IF NOT EXISTS vin_decode (
    vin         VARCHAR(17) PRIMARY KEY,
    decoded     JSONB,                  -- normalized spec dict (see collector/vin_decode.py)
    fetched_at  TIMESTAMPTZ DEFAULT NOW()
);
