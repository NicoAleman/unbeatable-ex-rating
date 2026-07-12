-- Bingo game tables: teams, charts, scores, admin auth/activity.

CREATE TABLE bingo_teams (
    player_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    team TEXT NOT NULL CHECK (team IN ('Eve', 'Grace', 'Rest')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE bingo_charts (
    "row" INTEGER NOT NULL CHECK ("row" >= 0),
    "column" INTEGER NOT NULL CHECK ("column" >= 0),
    "group" INTEGER,
    song TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("row", "column")
);

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

CREATE TABLE bingo_admin_pass (
    "user" TEXT PRIMARY KEY,
    pass TEXT NOT NULL
);

CREATE TABLE bingo_admin_activity (
    id BIGSERIAL PRIMARY KEY,
    "user" TEXT NOT NULL,
    teams BOOLEAN NOT NULL DEFAULT FALSE,
    charts BOOLEAN NOT NULL DEFAULT FALSE,
    dates BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bingo_teams_team ON bingo_teams (team);
CREATE INDEX idx_bingo_scores_player ON bingo_scores (player_id);
CREATE INDEX idx_bingo_scores_team ON bingo_scores (team);
CREATE INDEX idx_bingo_scores_chart ON bingo_scores (song, difficulty);
CREATE INDEX idx_bingo_scores_created_at ON bingo_scores (created_at DESC);
CREATE INDEX idx_bingo_admin_activity_created_at ON bingo_admin_activity (created_at DESC);
CREATE INDEX idx_bingo_admin_activity_user ON bingo_admin_activity ("user");

ALTER TABLE bingo_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE bingo_charts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bingo_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE bingo_admin_pass ENABLE ROW LEVEL SECURITY;
ALTER TABLE bingo_admin_activity ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read bingo_teams"
    ON bingo_teams
    FOR SELECT
    USING (true);

CREATE POLICY "Public read bingo_charts"
    ON bingo_charts
    FOR SELECT
    USING (true);

CREATE POLICY "Public read bingo_scores"
    ON bingo_scores
    FOR SELECT
    USING (true);

-- Seed teams from the Bingo team roster (player_id matches leaderboard/scores IDs).
INSERT INTO bingo_teams (player_id, display_name, team) VALUES
    ('mUdeR3emV3D0imF6t93ODeON50uw', 'Zennan', 'Eve'),
    ('37sx5ImA7o4hJl7qnTY22kWzcAyH', 'm', 'Eve'),
    ('FBCDmx4SwL6AkDHnL1Z0cD4RaYkw', 'steelce', 'Eve'),
    ('hpy46N8yG1Lu3Osad4HGURJRtWSr', 'BurgerMinus', 'Eve'),
    ('mxtjpmg0nGF1c4GlcErRA81mGG28', ':treblesat:', 'Eve'),
    ('6JtdQWRLzAlaCSKgTS6MUkpgQ17U', 'Flowery', 'Eve'),
    ('e4KF6nuqBNKjeyae2sSYzno28pEI', 'Vaporeon', 'Eve'),
    ('8qRQkcjFnMKZzsqvyEhJWdCl1CRv', 'Weeb Shortz', 'Eve'),
    ('5kApL7CuTC389Eui4naO36Y68ckU', 'F43555', 'Eve'),
    ('qr1KR66rUSqwzpLUpSH7tHQpOaQ8', 'alex schmalex', 'Eve'),
    ('KWs7rbQjAXUQP1jVpuzrvlVpTgqP', 'Arbitrary', 'Grace'),
    ('Ogb6FSSh7U3miuk1HRNpphqgkbhF', 'NULL', 'Grace'),
    ('wimEZieSVCUwzZ0qlNzerh5xQ3oD', 'melike_cookiecake', 'Grace'),
    ('EQ1uckpddDun4NnOEd1kamlXD9Yr', 'Pringles', 'Grace'),
    ('EDFlelylGwq1MPY61mjuBcFLfD01', 'Metalhead\m/', 'Grace'),
    ('5Rcrnc3PZrd1GgNkfY6BM1ccYhpb', 'asymmetric', 'Grace'),
    ('jWaNUUUI0sNWxAFDp06BngYcokBh', 'Mash0u0', 'Grace'),
    ('DEm4WwDN8fgeGLlsQVFBM04Ujtg2', 'terry', 'Grace'),
    ('d4lobXBPA3jGVHYzBfb2aF3RgijL', 'branstonbakesbeans', 'Grace'),
    ('XyukTc7yBC98Pax9uE4rrUCepEPD', 'Zachava', 'Grace'),
    ('iQWhn0lri3sH3bMEXaE68y87WJ0N', 'bobob13131', 'Rest'),
    ('stcvViUHGUtbawyk9Qyv3rB0DCvK', 'TeamGames', 'Rest'),
    ('d4CbRHm2Ln5HOt3drDz31J8MEk9e', 'hotsauceinramen', 'Rest'),
    ('OJH0y4N5hhU9wVYIfApSFzixCMIZ', 'Trumpet_Boi_208', 'Rest'),
    ('Eg1PZSGg5GQuc8oID0LBBs7Ix0KN', 'FacadeNico', 'Rest'),
    ('230iE0zZmcWfSLabVyCYPQIJcFKv', 'jjules.', 'Rest'),
    ('pHLwBehLgbrjZSsyx4ELXsLxHPdU', 'Lichtbaulb', 'Rest'),
    ('1H2wmJ2NsXfxzyGs6AJKveJwM98W', 'Simply Resharkable', 'Rest'),
    ('X1tbIRJSqZT1K8apERbvT4fI8QEo', 'Stefyfresh', 'Rest'),
    ('UHpjuLr28FwQs1ZteLF2A8UtkSwz', 'ellie', 'Rest');

-- Seed charts from the Bingo board (group left null for now).
-- song/difficulty match the scores table chart keys (level shown on board in comments).
INSERT INTO bingo_charts ("row", "column", "group", song, difficulty) VALUES
    (0, 0, NULL, 'NOISZ - Done In Love', 'UNBEATABLE'),              -- lv 18
    (0, 1, NULL, 'PRONTO A MOLTO AC', 'UNBEATABLE'),                   -- lv 21
    (0, 2, NULL, 'Waiting Lumena', 'UNBEATABLE'),                      -- lv 19
    (0, 3, NULL, 'goin crazy', 'Hard'),                                -- lv 13
    (0, 4, NULL, 'NOISZ - True', 'Star'),                              -- lv 23
    (1, 0, NULL, 'PROPERRHYTHM', 'Beginner'),                          -- lv 01
    (1, 1, NULL, 'Proper Rhythm Live', 'UNBEATABLE'),                  -- lv 16
    (1, 2, NULL, 'Forever Now - DOG_NOISE Remix', 'UNBEATABLE'),       -- lv 17
    (1, 3, NULL, 'Motherbound', 'Star'),                               -- lv 22
    (1, 4, NULL, 'Future People', 'UNBEATABLE'),                       -- lv 14
    (2, 0, NULL, 'PROPERRHYTHM MUST DIE', 'Normal'),                   -- lv 09
    (2, 1, NULL, 'proper rhythm zflip', 'UNBEATABLE'),                 -- lv 22
    (2, 2, NULL, 'yeahx6radio', 'UNBEATABLE'),                         -- lv 20
    (2, 3, NULL, 'Disco Disaster', 'UNBEATABLE'),                      -- lv 17
    (2, 4, NULL, 'RETUNED AC', 'Star'),                                -- lv 24
    (3, 0, NULL, 'Misery Index', 'Star'),                              -- lv 21
    (3, 1, NULL, 'MEMORIZED', 'UNBEATABLE'),                           -- lv 15
    (3, 2, NULL, 'beat v rest pt 2 ac', 'UNBEATABLE'),                 -- lv 24
    (3, 3, NULL, 'DRASTIC HAMMER AC', 'UNBEATABLE'),                   -- lv 13
    (3, 4, NULL, 'Familiar Acoustic', 'Easy'),                         -- lv 06
    (4, 0, NULL, 'True - Full', 'Hard'),                               -- lv 13
    (4, 1, NULL, 'SQUARE UP', 'UNBEATABLE'),                           -- lv 18
    (4, 2, NULL, 'Familiar Live', 'Beginner'),                         -- lv 01
    (4, 3, NULL, 'K Moe', 'UNBEATABLE'),                               -- lv 16
    (4, 4, NULL, 'Done In Love Full', 'Star');                         -- lv 20

INSERT INTO bingo_admin_pass ("user", pass) VALUES
    ('Nico', '3483'),
    ('Arbitrary', 'ubgoat');
