-- Hybrid leaderboard schema. See supabase/migrations/20260629180000_hybrid_leaderboard.sql

DROP TABLE IF EXISTS scores CASCADE;
DROP TABLE IF EXISTS rating_overrides CASCADE;
DROP TABLE IF EXISTS players CASCADE;
DROP TABLE IF EXISTS metadata CASCADE;
DROP TABLE IF EXISTS updated_ratings CASCADE;

CREATE TABLE updated_ratings (
    player_id TEXT PRIMARY KEY,
    ex_rating DOUBLE PRECISION NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL
);

CREATE TABLE scores (
    player_id TEXT NOT NULL,
    song TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    score INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('seed', 'submission')),
    PRIMARY KEY (player_id, song, difficulty)
);

CREATE INDEX idx_scores_player ON scores (player_id);
CREATE INDEX idx_scores_source ON scores (source);

ALTER TABLE updated_ratings ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read updated_ratings"
    ON updated_ratings
    FOR SELECT
    USING (true);
