-- Proof screenshots for manual Bingo score submissions (Supabase Storage).

ALTER TABLE bingo_scores
    ADD COLUMN IF NOT EXISTS proof_path TEXT;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'bingo-score-proofs',
    'bingo-score-proofs',
    false,
    52428800,
    ARRAY['image/png', 'image/jpeg', 'image/webp']::text[]
)
ON CONFLICT (id) DO NOTHING;
