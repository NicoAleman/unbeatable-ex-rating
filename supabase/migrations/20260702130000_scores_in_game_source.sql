-- Allow in-game mod imports as a distinct score source from site submissions.

ALTER TABLE scores DROP CONSTRAINT IF EXISTS scores_source_check;

ALTER TABLE scores
    ADD CONSTRAINT scores_source_check
    CHECK (source IN ('seed', 'submission', 'in_game'));
