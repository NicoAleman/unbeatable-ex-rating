-- Store note accuracy (and related play data) for submitted scores.
-- Seed imports leave these columns NULL.

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS accuracy DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS miss_count INTEGER,
    ADD COLUMN IF NOT EXISTS max_combo INTEGER,
    ADD COLUMN IF NOT EXISTS cleared BOOLEAN,
    ADD COLUMN IF NOT EXISTS critical_count INTEGER;
