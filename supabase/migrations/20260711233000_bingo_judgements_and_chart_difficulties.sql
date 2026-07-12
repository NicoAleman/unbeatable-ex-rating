-- Fix bingo judgement columns and chart song/difficulty to match scores table.

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

-- Remap board levels to song ID + difficulty name (same identity as scores).
UPDATE bingo_charts AS c SET
    song = v.song,
    difficulty = v.difficulty
FROM (VALUES
    (0, 0, 'NOISZ - Done In Love', 'UNBEATABLE'),
    (0, 1, 'PRONTO A MOLTO AC', 'UNBEATABLE'),
    (0, 2, 'Waiting Lumena', 'UNBEATABLE'),
    (0, 3, 'goin crazy', 'Hard'),
    (0, 4, 'NOISZ - True', 'Star'),
    (1, 0, 'PROPERRHYTHM', 'Beginner'),
    (1, 1, 'Proper Rhythm Live', 'UNBEATABLE'),
    (1, 2, 'Forever Now - DOG_NOISE Remix', 'UNBEATABLE'),
    (1, 3, 'Motherbound', 'Star'),
    (1, 4, 'Future People', 'UNBEATABLE'),
    (2, 0, 'PROPERRHYTHM MUST DIE', 'Normal'),
    (2, 1, 'proper rhythm zflip', 'UNBEATABLE'),
    (2, 2, 'yeahx6radio', 'UNBEATABLE'),
    (2, 3, 'Disco Disaster', 'UNBEATABLE'),
    (2, 4, 'RETUNED AC', 'Star'),
    (3, 0, 'Misery Index', 'Star'),
    (3, 1, 'MEMORIZED', 'UNBEATABLE'),
    (3, 2, 'beat v rest pt 2 ac', 'UNBEATABLE'),
    (3, 3, 'DRASTIC HAMMER AC', 'UNBEATABLE'),
    (3, 4, 'Familiar Acoustic', 'Easy'),
    (4, 0, 'True - Full', 'Hard'),
    (4, 1, 'SQUARE UP', 'UNBEATABLE'),
    (4, 2, 'Familiar Live', 'Beginner'),
    (4, 3, 'K Moe', 'UNBEATABLE'),
    (4, 4, 'Done In Love Full', 'Star')
) AS v("row", "column", song, difficulty)
WHERE c."row" = v."row" AND c."column" = v."column";
