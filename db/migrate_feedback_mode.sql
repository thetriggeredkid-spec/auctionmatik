-- Auctionmatik — tag each feedback row with the engine MODE that produced the call.
--
-- Calibration has two incompatible "truths":
--   * retail/deep corrections (Correct tab) — engine_value vs your corrected retail value.
--     This is the signal that matters; we want to know we're scoring the DEEP pass.
--   * wholesale backtest (collector.import_outcomes) — engine_max_bid vs the actual Regal
--     hammer price. Margin-affected and built off the shoddy wholesale data; a TRIAGE baseline.
--
-- engine_mode lets the calibration view split these so they stop polluting one bias number.
--   'deep'   — the AI deep appraisal produced the corrected call
--   'triage' — the fast AI screen produced it
--   'rules'  — the deterministic advisor (no AI) produced it
--   'auto'   — auto-imported wholesale backtest (collector.import_outcomes)

ALTER TABLE listing_feedback ADD COLUMN IF NOT EXISTS engine_mode VARCHAR(10);

-- Backfill: existing auto-imported rows are tagged in notes; everything else is unknown.
UPDATE listing_feedback SET engine_mode = 'auto'
 WHERE engine_mode IS NULL AND notes LIKE '[auto]%';
