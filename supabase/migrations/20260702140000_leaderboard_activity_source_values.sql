-- Align leaderboard_activity.submission_source with scores.source player channels.

ALTER TABLE leaderboard_activity
    DROP CONSTRAINT IF EXISTS leaderboard_activity_submission_source_check;

UPDATE leaderboard_activity
SET submission_source = 'in_game'
WHERE submission_source = 'mod';

UPDATE leaderboard_activity
SET submission_source = 'submission'
WHERE submission_source = 'site';

ALTER TABLE leaderboard_activity
    ADD CONSTRAINT leaderboard_activity_submission_source_check
    CHECK (
        submission_source IS NULL
        OR submission_source IN ('submission', 'in_game')
    );
