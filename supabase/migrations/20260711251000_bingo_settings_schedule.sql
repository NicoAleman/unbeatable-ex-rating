-- Seed bingo schedule: Jul 13 2026 00:00 Pacific (PDT) = 07:00 UTC, 7 days.

UPDATE bingo_settings
SET
    start_time = '2026-07-13 07:00:00+00',
    day_count = 7
WHERE id = 1;
