# UNBEATABLE EX Rating Leaderboard — API & Rating Reference

This document describes the Supabase database used by the [UNBEATABLE EX Rating](https://github.com/) leaderboard site, how submissions are written today, and how EX Rating is calculated. It is intended for building a game mod or other client that submits scores and ratings.

---

## Architecture overview

The leaderboard uses a **hybrid model**:

| Layer | Storage | Purpose |
|---|---|---|
| **Baseline** | `resources/ex_rating_baseline.csv` (in repo) | One row per player: `player_id`, display name, baseline EX rating, last updated |
| **Live overrides** | Supabase `updated_ratings` | Patches baseline ratings when a player submits a new rating |
| **Chart scores** | Supabase `scores` | Per-chart Classic scores used to render rating boards for searchable players |
| **Activity feed** | Supabase `leaderboard_activity` | Recent rating increases shown on the site |

**Displayed leaderboard rank** = sort all baseline players by effective rating (override if present), then assign competition ranks (ties share a rank).

There is **no public HTTP REST API** for writes today. The Streamlit site and admin scripts connect to Supabase Postgres directly using a server-side connection string. A game mod should **not** embed database credentials; it calls the Render submission API described in [`SUBMISSION_BACKEND.md`](SUBMISSION_BACKEND.md).

### Row Level Security (RLS)

| Table | Public read | Public write |
|---|---|---|
| `updated_ratings` | Yes | No |
| `scores` | No | No |
| `leaderboard_activity` | Yes | No |

Reads of `scores` and all writes require a privileged Postgres/service connection.

---

## Database schema

### `updated_ratings`

Live rating overrides keyed by the game's platform player ID.

| Column | Type | Notes |
|---|---|---|
| `player_id` | `TEXT` PK | Platform ID, e.g. `DFUFGxHDMNp1cR00uFLu2RXXnptp` |
| `ex_rating` | `DOUBLE PRECISION` | Full player EX rating **including +2.0 completion bonus** |
| `last_updated` | `TIMESTAMPTZ` | ISO 8601 timestamp of submission |

### `scores`

One row per player per chart (song + difficulty). Primary key: `(player_id, song, difficulty)`.

| Column | Type | Notes |
|---|---|---|
| `player_id` | `TEXT` | Platform player ID |
| `song` | `TEXT` | Internal song identifier (matches `ArcadeMaxScores.csv`) |
| `difficulty` | `TEXT` | e.g. `Star`, `Hard`, `UNBEATABLE` |
| `score` | `INTEGER` | Classic mode score |
| `source` | `TEXT` | `'seed'` (bulk import), `'submission'` (site upload), or `'in_game'` (mod API) |
| `accuracy` | `DOUBLE PRECISION` | Optional. Note accuracy as **0–100 percent** (not 0–1) |
| `miss_count` | `INTEGER` | Optional |
| `max_combo` | `INTEGER` | Optional |
| `cleared` | `BOOLEAN` | Optional |
| `critical_count` | `INTEGER` | Optional |

**Accuracy metadata rule:** If you include `accuracy` on any score for a player, include it on **all** scores for that player. Mixed null/non-null accuracy causes the site to show a Standard Rating board with mostly empty accuracy columns. For score-only submissions (EX Rating from score alone), **omit all accuracy columns** (leave them `NULL`).

### `leaderboard_activity`

Append-only feed of rating increases.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL` PK | Auto |
| `player_id` | `TEXT` | |
| `prev_rating` | `DOUBLE PRECISION` | Rating before submission |
| `new_rating` | `DOUBLE PRECISION` | Rating after submission |
| `prev_rank` | `INTEGER` | Competition rank before |
| `new_rank` | `INTEGER` | Competition rank after |
| `created_at` | `TIMESTAMPTZ` | Defaults to `NOW()` |
| `submission_source` | `TEXT` | `'in_game'` or `'submission'`; `NULL` for backfilled rows. **Admin/audit only** — matches `scores.source` for player updates |

---

## Reading data (public)

These queries work with Supabase's anon key / public RLS policies.

### Effective leaderboard

```sql
-- Pseudocode: merge baseline CSV with updated_ratings, sort by ex_rating DESC
SELECT player_id, ex_rating, last_updated
FROM updated_ratings
ORDER BY ex_rating DESC;
```

The site loads baseline from CSV and overlays `updated_ratings` in application code (`rating/public_leaderboard.py`).

### Activity feed

```sql
SELECT player_id, prev_rating, new_rating, prev_rank, new_rank, created_at, submission_source
FROM leaderboard_activity
ORDER BY created_at DESC
LIMIT 20;
```

Display names are resolved from the baseline CSV by `player_id`.

---

## Submitting a rating update

Reference implementation: `rating/full_ex_submissions.py` → `submit_full_ex_rating_update()`.

### Validation rules

1. **Player must exist** on the baseline leaderboard (matched by `player_id`).
2. **New EX rating must be strictly greater** than the player's current effective rating (baseline or latest override).
3. **At least one rated Classic chart** must be present in the submitted score list.
4. Only **Classic** charts count. Custom charts (`CUSTOM_*`) are excluded.
5. Only charts with a known **critical max score** in `resources/ArcadeMaxScores.csv` are rated.

### Submission payload (logical)

Your backend should accept something equivalent to:

```json
{
  "player_id": "DFUFGxHDMNp1cR00uFLu2RXXnptp",
  "ex_rating": 12.034,
  "last_updated": "2026-07-01T12:00:00+00:00",
  "scores": [
    {
      "song": "AFTERBURN",
      "difficulty": "Star",
      "score": 1794257
    },
    {
      "song": "apb",
      "difficulty": "Star",
      "score": 1779685,
      "accuracy": 100.0,
      "miss_count": 0,
      "max_combo": 842,
      "cleared": true,
      "critical_count": 842
    }
  ],
  "prev_rating": 11.985,
  "prev_rank": 12
}
```

- `ex_rating` must be computed client-side or server-side using the formulas below (including +2.0 completion bonus).
- `scores` should contain the player's **best score per chart** after the update (same shape the site extracts from `arcade-highscores.json`).
- `prev_rating` / `prev_rank` are used only to write the activity feed entry.

### Write sequence (Postgres)

Execute in a transaction:

**1. Upsert live rating**

```sql
INSERT INTO updated_ratings (player_id, ex_rating, last_updated)
VALUES ($1, $2, $3)
ON CONFLICT (player_id) DO UPDATE SET
    ex_rating = EXCLUDED.ex_rating,
    last_updated = EXCLUDED.last_updated;
```

**2. Replace player scores**

Delete existing rows for that channel, then upsert the full score list with the matching `source`:

- Site upload → `source = 'submission'`
- Mod API → `source = 'in_game'`

```sql
DELETE FROM scores WHERE player_id = $1 AND source = $2;  -- 'submission' or 'in_game'

INSERT INTO scores (
    player_id, song, difficulty, score, source,
    accuracy, miss_count, max_combo, cleared, critical_count
) VALUES ($1, $2, $3, $4, $2, $5, $6, $7, $8, $9)
ON CONFLICT (player_id, song, difficulty) DO UPDATE SET
    score = EXCLUDED.score,
    source = EXCLUDED.source,
    accuracy = EXCLUDED.accuracy,
    miss_count = EXCLUDED.miss_count,
    max_combo = EXCLUDED.max_combo,
    cleared = EXCLUDED.cleared,
    critical_count = EXCLUDED.critical_count;
```

Rows with `source = 'seed'` from the initial bulk import are left untouched unless the same `(player_id, song, difficulty)` is upserted via `ON CONFLICT`.

**3. Record activity feed** (when rating increased)

```sql
INSERT INTO leaderboard_activity (
    player_id, prev_rating, new_rating, prev_rank, new_rank, created_at, submission_source
) VALUES ($1, $2, $3, $4, $5, $6, $7);
```

Only write a feed entry when EX rating increased. Set `submission_source` to `'in_game'` (mod API) or `'submission'` (site upload), matching `scores.source`.

---

## Extracting scores from game data

### From `arcade-highscores.json`

The site reads the player's local save at:

`%LOCALAPPDATA%/../LocalLow/D-CELL GAMES/UNBEATABLE/PROFILES/<profile>/arcade-highscores.json`

Expected structure:

```json
{
  "highScores": [
    {
      "song": "AFTERBURN/Star\\Classic",
      "score": 1794257,
      "level": 71,
      "accuracy": 1.0,
      "cleared": true,
      "maxCombo": 900,
      "notes": [
        { "timing": "Miss", "count": 0 },
        { "timing": "Critical", "count": 850 }
      ]
    }
  ]
}
```

Extraction rules (`rating/full_ex_submissions.py` → `extract_classic_chart_scores()`):

| Rule | Detail |
|---|---|
| Classic only | `song` ends with `\Classic` |
| No custom charts | Song ID must not start with `CUSTOM_` |
| Chart key | Strip `\Classic` → `AFTERBURN/Star` |
| Rated charts | Must exist in `ArcadeMaxScores.csv` |
| Best per chart | Keep highest `score` per `(song, difficulty)` |
| Accuracy | If present in JSON, store as `accuracy * 100` (percent) |

Song identifiers in the JSON use the **internal name** from the CSV first column (e.g. `apb`, `ZERO MOMENT AC`, `PROPERRHYTHM BOOTLEG`), not necessarily the display name.

### Chart key format

Charts are identified as `{song}/{difficulty}`:

```
apb/Star
ZERO MOMENT AC/Star
PROPERRHYTHM BOOTLEG/Star
AFTERBURN/Star
```

Lookup is case-insensitive when matching against `ArcadeMaxScores.csv`.

---

## Reference data files

Ship these with your mod or fetch them from the leaderboard repo.

### `resources/ArcadeMaxScores.csv`

CSV rows: `{chart_key},{display_name},{level},{max_score},{critical_max_score}`

Example:

```
AFTERBURN/Star,Afterburn,71,1477652,1845916
```

- **critical_max_score** (last column) = denominator for EX Accuracy
- Used to decide which charts are rateable

### `resources/chart_rating_levels.json`

Maps chart keys to **rating levels** used in the EX Rating formula. Built from highscore save files; keys match `ArcadeMaxScores.csv`.

Example:

```json
{
  "AFTERBURN/Star": 20,
  "apb/Star": 23
}
```

If a chart has no level entry, it is not rated.

### `resources/rating/level_overrides.py` (manual fixes)

A small set of level corrections overrides JSON levels, e.g. `AFTERBURN/Star → 20`.

---

## EX Rating calculation

Constants (`rating/constants.py`):

| Constant | Value |
|---|---|
| `TOP_N` | 25 |
| `COMPLETION_BONUS` | 2.0 |
| `RATING_DIVISOR` | 5625 |
| `EX_S_PLUS_THRESHOLD` | 98.0 |

Reference code: `rating/calculator.py`, `rating/formulas.py`, `rating/board.py`.

### Step 1 — Per-chart EX Accuracy

EX Accuracy is **score-based**, not note-accuracy-based:

```
EX Accuracy = (score ÷ critical_max_score) × 100
```

`critical_max_score` comes from `ArcadeMaxScores.csv`.

### Step 2 — EX Grade

Uses EX Accuracy (not note accuracy). A **+1% bonus** is added to the grade threshold when there are no misses.

| Grade | Condition |
|---|---|
| F | Not cleared |
| S++ | No misses, grade accuracy ≥ 95%, **and** `critical_count == max_combo` |
| S+ | No misses **and** EX Accuracy ≥ 98% |
| S | Grade accuracy ≥ 95% |
| A | ≥ 85% |
| B | ≥ 75% |
| C | ≥ 65% |
| D | ≥ 55% |
| HOW? | Below 55% |

Where `grade_accuracy = ex_accuracy + (1.0 if no misses else 0.0)`.

When accuracy metadata is omitted from stored scores, misses default to 0 and `cleared` defaults to true, so grades are driven primarily by EX Accuracy. EX S++ requires submitting `critical_count` and `max_combo`.

### Step 3 — Grade bonus

Same rules for standard and EX paths:

```
if accuracy > 90%:           bonus = 25
elif no misses and acc > 89%: bonus = 25
elif grade A:                 bonus = 20
elif grade B:                 bonus = 15
elif grade C:                 bonus = 12
elif grade D or HOW?:         bonus = 10
else:                         bonus = 0
```

For EX Rating, `accuracy` in the above means **EX Accuracy**.

### Step 4 — Per-chart EX Rating

```
accPower = (EX Accuracy - 50)^1.12    // 0 if EX Accuracy ≤ 50

EX Rating (chart) = (chart_level × (accPower + grade_bonus)) ÷ 5625
```

`chart_level` from `chart_rating_levels.json`, with manual overrides applied.

### Step 5 — Player EX Rating

```
board_sum = sum of top 25 chart EX Ratings (highest 25 values)

Player EX Rating = board_sum + 2.0   // completion bonus
```

This final value is what gets stored in `updated_ratings.ex_rating` and shown on the leaderboard (displayed to 3 decimal places).

### Worked example

Chart: `AFTERBURN/Star`, level 20, critical max 1,845,916, score 1,794,257, no misses.

```
EX Accuracy = 1,794,257 / 1,845,916 × 100 = 97.20%
accPower = (97.20 - 50)^1.12 = 78.47
grade_bonus = 25   (accuracy > 90%)
EX Rating = (20 × (78.47 + 25)) / 5625 = 0.368
```

Repeat for every rated chart, take the top 25 EX Rating values, sum them, add 2.0.

### Standard Rating (optional)

The site can also show a **Standard Rating** board when note-accuracy metadata is present on scores. Standard Rating uses `accuracy` from the save file (0–100%) instead of score-based EX Accuracy. Player total also uses top 25 + 2.0 completion bonus.

For mod submissions focused on the EX leaderboard, omit accuracy fields entirely.

---

## Competition ranking

After updating `updated_ratings`:

1. Load all baseline entries from CSV.
2. Replace rating with override when `player_id` exists in `updated_ratings`.
3. Sort by `ex_rating` descending, then display name (case-insensitive).
4. Assign competition ranks (ties share rank; next rank skips: 1, 1, 3, …).

Reference: `rating/public_leaderboard.py` → `player_rank_on_leaderboard()`.

---

## Recommended mod integration

### Client (game mod)

1. Read `arcade-highscores.json` (or equivalent in-memory highscore list).
2. Filter to Classic, non-custom charts with known max scores.
3. Compute EX Rating locally using the formulas above (ship `ArcadeMaxScores.csv` + `chart_rating_levels.json`).
4. Compare against the player's current effective rating (fetch `updated_ratings` for their `player_id`, fall back to baseline).
5. If higher, POST to your submission backend with `player_id`, computed `ex_rating`, and the score list.

### Backend (you provide)

1. Authenticate the request (verify the caller owns `player_id`).
2. Recompute and validate EX Rating server-side (do not trust client-only math).
3. Enforce `new_rating > current_rating`.
4. Run the Postgres write sequence above.
5. Return success/error JSON.

### Suggested HTTP response shape

```json
{ "success": true, "message": "Rating update saved to the leaderboard.", "new_rank": 10 }
```

```json
{ "success": false, "error": "Your submitted rating (12.000) must be higher than your current leaderboard rating (12.034)." }
```

---

## Python reference functions

| Function | Module | Purpose |
|---|---|---|
| `extract_classic_chart_scores()` | `rating/full_ex_submissions.py` | Parse save file → score rows |
| `build_ratings()` | `rating/calculator.py` | Save file → list of `ChartRating` |
| `build_ratings_from_stored_scores()` | `rating/imported_players.py` | DB score rows → `ChartRating` list |
| `player_ex_rating_with_completion()` | `rating/board.py` | Chart ratings → player EX rating |
| `validate_full_ex_rating_submission()` | `rating/full_ex_submissions.py` | Check rating increase |
| `submit_player_update_to_supabase()` | `rating/supabase_leaderboard.py` | Write scores + override |
| `record_leaderboard_activity()` | `rating/leaderboard_activity.py` | Append feed entry |
| `player_rank_on_leaderboard()` | `rating/public_leaderboard.py` | Compute rank after update |

---

## Migration files

Schema source of truth: `supabase/migrations/`

- `20260629180000_hybrid_leaderboard.sql` — `updated_ratings`, `scores`
- `20260630120000_scores_accuracy.sql` — accuracy metadata columns
- `20260701120000_leaderboard_activity.sql` — activity feed
- `20260702120000_leaderboard_activity_submission_source.sql` — activity feed source column
- `20260702130000_scores_in_game_source.sql` — mod score source (`in_game`)
- `20260702140000_leaderboard_activity_source_values.sql` — align activity source with scores (`in_game` / `submission`)
