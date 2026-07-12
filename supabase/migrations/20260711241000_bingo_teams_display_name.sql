-- Add display_name to bingo_teams for easier internal viewing.

CREATE TABLE bingo_teams_new (
    player_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    team TEXT NOT NULL CHECK (team IN ('Eve', 'Grace', 'Rest')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO bingo_teams_new (player_id, display_name, team, created_at)
SELECT
    t.player_id,
    v.display_name,
    t.team,
    t.created_at
FROM bingo_teams AS t
JOIN (VALUES
    ('mUdeR3emV3D0imF6t93ODeON50uw', 'Zennan'),
    ('37sx5ImA7o4hJl7qnTY22kWzcAyH', 'm'),
    ('FBCDmx4SwL6AkDHnL1Z0cD4RaYkw', 'steelce'),
    ('hpy46N8yG1Lu3Osad4HGURJRtWSr', 'BurgerMinus'),
    ('mxtjpmg0nGF1c4GlcErRA81mGG28', ':treblesat:'),
    ('6JtdQWRLzAlaCSKgTS6MUkpgQ17U', 'Flowery'),
    ('e4KF6nuqBNKjeyae2sSYzno28pEI', 'Vaporeon'),
    ('8qRQkcjFnMKZzsqvyEhJWdCl1CRv', 'Weeb Shortz'),
    ('5kApL7CuTC389Eui4naO36Y68ckU', 'F43555'),
    ('qr1KR66rUSqwzpLUpSH7tHQpOaQ8', 'alex schmalex'),
    ('KWs7rbQjAXUQP1jVpuzrvlVpTgqP', 'Arbitrary'),
    ('Ogb6FSSh7U3miuk1HRNpphqgkbhF', 'NULL'),
    ('wimEZieSVCUwzZ0qlNzerh5xQ3oD', 'melike_cookiecake'),
    ('EQ1uckpddDun4NnOEd1kamlXD9Yr', 'Pringles'),
    ('EDFlelylGwq1MPY61mjuBcFLfD01', 'Metalhead\m/'),
    ('5Rcrnc3PZrd1GgNkfY6BM1ccYhpb', 'asymmetric'),
    ('jWaNUUUI0sNWxAFDp06BngYcokBh', 'Mash0u0'),
    ('DEm4WwDN8fgeGLlsQVFBM04Ujtg2', 'terry'),
    ('d4lobXBPA3jGVHYzBfb2aF3RgijL', 'branstonbakesbeans'),
    ('XyukTc7yBC98Pax9uE4rrUCepEPD', 'Zachava'),
    ('iQWhn0lri3sH3bMEXaE68y87WJ0N', 'bobob13131'),
    ('stcvViUHGUtbawyk9Qyv3rB0DCvK', 'TeamGames'),
    ('d4CbRHm2Ln5HOt3drDz31J8MEk9e', 'hotsauceinramen'),
    ('OJH0y4N5hhU9wVYIfApSFzixCMIZ', 'Trumpet_Boi_208'),
    ('Eg1PZSGg5GQuc8oID0LBBs7Ix0KN', 'FacadeNico'),
    ('230iE0zZmcWfSLabVyCYPQIJcFKv', 'jjules.'),
    ('pHLwBehLgbrjZSsyx4ELXsLxHPdU', 'Lichtbaulb'),
    ('1H2wmJ2NsXfxzyGs6AJKveJwM98W', 'Simply Resharkable'),
    ('X1tbIRJSqZT1K8apERbvT4fI8QEo', 'Stefyfresh'),
    ('UHpjuLr28FwQs1ZteLF2A8UtkSwz', 'ellie')
) AS v(player_id, display_name)
    ON t.player_id = v.player_id;

DROP TABLE bingo_teams;
ALTER TABLE bingo_teams_new RENAME TO bingo_teams;

CREATE INDEX idx_bingo_teams_team ON bingo_teams (team);

ALTER TABLE bingo_teams ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read bingo_teams"
    ON bingo_teams
    FOR SELECT
    USING (true);
