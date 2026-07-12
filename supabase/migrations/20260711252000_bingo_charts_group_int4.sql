-- bingo_charts."group" is an int4 group id (nullable).

ALTER TABLE bingo_charts
    ALTER COLUMN "group" TYPE INTEGER
    USING NULLIF(TRIM("group"::TEXT), '')::INTEGER;
