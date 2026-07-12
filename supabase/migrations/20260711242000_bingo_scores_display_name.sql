-- Add display_name to bingo_scores (after player_id) for easier internal viewing.
-- Recreate to keep column order; table starts empty.

DROP TABLE IF EXISTS bingo_scores CASCADE;

CREATE TABLE bingo_scores (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    team TEXT NOT NULL CHECK (team IN ('Eve', 'Grace', 'Rest')),
    song TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    score INTEGER NOT NULL,
    accuracy DOUBLE PRECISION,
    critical INTEGER,
    perfect INTEGER,
    great INTEGER,
    good INTEGER,
    okay INTEGER,
    barely INTEGER,
    miss INTEGER,
    source TEXT NOT NULL CHECK (source IN ('in_game', 'submission')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bingo_scores_player ON bingo_scores (player_id);
CREATE INDEX idx_bingo_scores_team ON bingo_scores (team);
CREATE INDEX idx_bingo_scores_chart ON bingo_scores (song, difficulty);
CREATE INDEX idx_bingo_scores_created_at ON bingo_scores (created_at DESC);

ALTER TABLE bingo_scores ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read bingo_scores"
    ON bingo_scores
    FOR SELECT
    USING (true);
