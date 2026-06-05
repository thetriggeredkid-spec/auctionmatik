-- Auctionmatik — editable settings (single-row JSONB store of OVERRIDES only).
-- Code keeps the hardcoded values as defaults; engine/settings.py merges these on top
-- and applies them to the live config (buyer profiles, margin tiers, fee schedule, GST,
-- engine toggles). See engine/settings.py.

CREATE TABLE IF NOT EXISTS app_settings (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT  single_row CHECK (id = 1)
);

INSERT INTO app_settings (id, settings) VALUES (1, '{}'::jsonb)
    ON CONFLICT (id) DO NOTHING;
