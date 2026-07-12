-- Bingo game settings (singleton row): board size, start time, duration.

CREATE TABLE bingo_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    board_width INTEGER NOT NULL DEFAULT 5 CHECK (board_width >= 1),
    start_time TIMESTAMPTZ,
    day_count INTEGER CHECK (day_count IS NULL OR day_count >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO bingo_settings (id, board_width, start_time, day_count)
VALUES (1, 5, '2026-07-13 07:00:00+00', 7);

ALTER TABLE bingo_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read bingo_settings"
    ON bingo_settings
    FOR SELECT
    USING (true);

-- Board size is driven by bingo_settings.board_width; keep only >= 0 bounds.
ALTER TABLE bingo_charts DROP CONSTRAINT IF EXISTS bingo_charts_row_check;
ALTER TABLE bingo_charts DROP CONSTRAINT IF EXISTS bingo_charts_column_check;
ALTER TABLE bingo_charts
    ADD CONSTRAINT bingo_charts_row_check CHECK ("row" >= 0);
ALTER TABLE bingo_charts
    ADD CONSTRAINT bingo_charts_column_check CHECK ("column" >= 0);
