-- Track whether an activity feed entry came from the game mod API or the site.

ALTER TABLE leaderboard_activity
    ADD COLUMN submission_source TEXT
    CHECK (submission_source IS NULL OR submission_source IN ('mod', 'site'));
