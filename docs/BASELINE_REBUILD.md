# Full EX baseline rebuild & promote

Use this when refreshing the site leaderboard from a fresh UGS Classic pull
(plus higher Supabase chart scores), without relying on stale `updated_ratings`.

## Workflow

```powershell
# 1) Fetch all rateable Classic boards, merge DB scores, rate everyone
python rebuild_ex_baseline_from_ugs.py

# Optional: reuse an existing fetch
python rebuild_ex_baseline_from_ugs.py --skip-fetch --output resources/ex_rating_rebuild_YYYYMMDD

# 2) Promote rebuild to live baseline files + Supabase cleanup/seed
python promote_ex_baseline_rebuild.py --rebuild-dir resources/ex_rating_rebuild_YYYYMMDD

# 3) Commit & push so Streamlit Community Cloud deploys the new CSV/meta
git add resources/ex_rating_baseline.csv resources/ex_rating_baseline_meta.json
git commit -m "Refresh EX rating baseline from UGS full rebuild"
git push
```

Promote flags:

| Flag | Effect |
|------|--------|
| `--skip-db` | Only write CSV/meta/top-scores; leave Supabase alone |
| `--skip-prune` | Keep existing `updated_ratings` (still re-seeds scores unless skipped) |
| `--skip-score-seed` | Do not replace `scores` seed rows |

## What promote does

1. Writes `resources/ex_rating_baseline.csv` with **Last Updated = promote time** for every row
2. Writes `resources/ex_rating_baseline_meta.json` with `last_full_rebuild`
3. Writes `resources/ex_rating_baseline_top_scores.json` (top-1000 chart scores for board merge)
4. Deletes Supabase `updated_ratings` where `last_updated <= last_full_rebuild` (unless `--skip-prune`)
5. Replaces Supabase `scores` rows with `source='seed'` from `top_1000_player_scores.json` using `GREATEST` (unless `--skip-score-seed`)

Player score boards use **max(baseline top scores, Supabase)** per chart so a lower DB row cannot override a higher baseline score.

## How live ratings merge after a rebuild

Displayed rating = baseline, unless a newer override exists:

- If `updated_ratings.last_updated` **>** `last_full_rebuild` → use the override (post-rebuild submission)
- Else if baseline **>=** override → use baseline
- Else → use override (rare; only if somehow still higher)

Submission API `get_effective_rating()` uses the same merge rules.

## Artifacts from rebuild

`resources/ex_rating_rebuild_YYYYMMDD/`

| File | Purpose |
|------|---------|
| `ex_rating_baseline.csv` | Rated players before promote |
| `top_1000_player_scores.json` | Seed payload for top 1000 |
| `ugs_charts/` | Resume-safe per-chart UGS dumps |
| `top_100_comparison_vs_live.csv` | Optional QA vs previous live board |

Rebuild directories are local/working artifacts (gitignored via `resources/ex_rating_rebuild_*/`); only the promoted baseline CSV + meta need to ship with the site.
