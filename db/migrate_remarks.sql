-- Auctionmatik — store the full condition-report REMARKS from the Regal detail page.
-- The API's `other` field is often empty/sparse; the detail .htm carries the auctioneer
-- announcement + a full condition writeup ("Check Engine light is on", "front bumper is a
-- different color", rust/dents/glass, etc). regal_enrich extracts it into `remarks`.
-- Kept separate from condition_notes so the listings collector's upsert can't clobber it.

ALTER TABLE regal_listings ADD COLUMN IF NOT EXISTS remarks TEXT;
ALTER TABLE regal_sold     ADD COLUMN IF NOT EXISTS remarks TEXT;
