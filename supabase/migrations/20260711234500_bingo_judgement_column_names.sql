-- Shorten bingo judgement column names (drop _count suffix).

ALTER TABLE bingo_scores RENAME COLUMN critical_count TO critical;
ALTER TABLE bingo_scores RENAME COLUMN perfect_count TO perfect;
ALTER TABLE bingo_scores RENAME COLUMN great_count TO great;
ALTER TABLE bingo_scores RENAME COLUMN good_count TO good;
ALTER TABLE bingo_scores RENAME COLUMN okay_count TO okay;
ALTER TABLE bingo_scores RENAME COLUMN barely_count TO barely;
ALTER TABLE bingo_scores RENAME COLUMN miss_count TO miss;
