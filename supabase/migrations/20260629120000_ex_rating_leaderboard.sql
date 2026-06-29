CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE players (
    player_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    player_name TEXT,
    ex_rating DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL
);

CREATE TABLE scores (
    player_id TEXT NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    song TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    score INTEGER NOT NULL,
    PRIMARY KEY (player_id, song, difficulty)
);

CREATE TABLE rating_overrides (
    player_id TEXT PRIMARY KEY REFERENCES players (player_id) ON DELETE CASCADE,
    ex_rating DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_players_rank ON players (rank);
CREATE INDEX idx_players_ex_rating ON players (ex_rating DESC);
CREATE INDEX idx_players_display_name_lower ON players (LOWER(display_name));
CREATE INDEX idx_scores_player ON scores (player_id);

ALTER TABLE players ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE rating_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read players"
    ON players
    FOR SELECT
    USING (true);
