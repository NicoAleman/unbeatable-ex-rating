-- Raise bingo score proof upload limit to 50 MB.

UPDATE storage.buckets
SET file_size_limit = 52428800
WHERE id = 'bingo-score-proofs';
