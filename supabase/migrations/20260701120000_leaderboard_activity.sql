-- Recent rating submissions for the public activity feed.

CREATE TABLE leaderboard_activity (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    prev_rating DOUBLE PRECISION NOT NULL,
    new_rating DOUBLE PRECISION NOT NULL,
    prev_rank INTEGER NOT NULL,
    new_rank INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_leaderboard_activity_created_at
    ON leaderboard_activity (created_at DESC);

CREATE INDEX idx_leaderboard_activity_player
    ON leaderboard_activity (player_id);

ALTER TABLE leaderboard_activity ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read leaderboard_activity"
    ON leaderboard_activity
    FOR SELECT
    USING (true);
