# Bingo — Game Mod Submission API

Handoff for building a **Bingo score upload mod**, modeled after the [EXRating mod](https://github.com/Unbeatable-Mods/mods/tree/main/EXRating). The mod POSTs one chart score at a time to the Render submission API; the server validates and writes to Supabase Postgres.

For shared auth, deploy, and error format, see [`SUBMISSION_BACKEND.md`](SUBMISSION_BACKEND.md).

---

## Status

| Piece | Status |
|---|---|
| `POST /submit` (EX Rating) | Live |
| `POST /submit/bingo` (Bingo) | Implemented in `api/main.py` — deploy to Render |
| Validation logic | `rating/bingo.py` → `submit_bingo_score()`, `process_bingo_mod_submission()` |
| Live-window check | Enforced for mod submissions (`require_live=True`) |

**Live API base URL (same service as EX):** `https://ex-rating-submit-api.onrender.com`

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | `GET` | Health check |
| `/bingo/board` | `GET` | Active board charts (public, no auth) |
| `/submit/bingo` | `POST` | Submit one Bingo chart score |

---

## Architecture

```
Game mod (Bingo.dll)
    POST JSON  ──►  Render web service (/submit/bingo)
                        │
                        ▼
                   Supabase Postgres
                   (bingo_scores, bingo_teams, bingo_charts, bingo_settings)
```

The mod sends `Authorization: Bearer <SUBMIT_API_KEY>`. The server holds `DATABASE_URL` and never exposes it to clients. Use the same `SUBMIT_API_KEY` as the EX Rating mod unless you configure a separate key later.

---

## Mod config (suggested)

In BepInEx config (mirror EX Rating):

```ini
[Submission]
ApiUrl = https://ex-rating-submit-api.onrender.com/submit/bingo
ApiKey = <same value as SUBMIT_API_KEY on Render>
```

The API key is per-user in mod config — not stored in this repo.

---

## API reference

### `GET /bingo/board`

**Auth:** none (public read).

Returns charts inside the active `board_width × board_width` grid from `bingo_charts` / `bingo_settings`.

```json
{
  "board_width": 5,
  "charts": [
    {
      "song": "NOISZ - Done In Love",
      "difficulty": "UNBEATABLE",
      "row": 0,
      "column": 0,
      "group": null
    }
  ]
}
```

Used by the Bingo mod Arcade **Category → Bingo** song filter.

### `POST /submit/bingo`

**Headers:**

- `Content-Type: application/json`
- `Authorization: Bearer <SUBMIT_API_KEY>`

**Body:**

```json
{
  "player_id": "mUdeR3emV3D0imF6t93ODeON50uw",
  "song": "NOISZ - Done In Love",
  "difficulty": "UNBEATABLE",
  "score": 1150000,
  "accuracy": 97.2,
  "critical": 850,
  "perfect": 12,
  "great": 3,
  "good": 0,
  "okay": 0,
  "barely": 0,
  "miss": 0
}
```

| Field | Required | Notes |
|---|---|---|
| `player_id` | Yes | UGS / internal player ID from `bingo_teams` |
| `song` | Yes | Chart song key (must match board) |
| `difficulty` | Yes | Chart difficulty key (must match board) |
| `score` | Yes | Positive integer |
| `accuracy` | No | 0–100 note accuracy |
| `critical`, `perfect`, `great`, `good`, `okay`, `barely`, `miss` | No | Judgement counts |

Unlike EX Rating (`POST /submit`), Bingo accepts **one chart per request**, not a full score list. There is no EX Rating recompute — the board uses raw scores only.

**Success (200):**

```json
{
  "success": true,
  "message": "Saved 1,150,000 for Zennan on NOISZ - Done In Love."
}
```

**Failure (400 / 401 / 500):**

```json
{
  "success": false,
  "error": "Human-readable reason"
}
```

---

## Server-side validation

The server must enforce all of the following before inserting a row into `bingo_scores`:

### 1. Authentication

Bearer token must match `SUBMIT_API_KEY`. Same rules as EX — see `authenticate_bearer_token()` in `rating/submission_api.py`.

### 2. Competition is live

Reject if the Bingo event is not currently running:

- **Before** `bingo_settings.start_time` → reject
- **After** the final competition day ends → reject

Live window:

```
start_time <= now < start_time + (day_count × 24 hours)
```

Reference: `bingo_in_progress_day()` in `rating/bingo.py`. Returns the 1-based day number while live, or `None` when submissions should be rejected.

> **Note:** The site’s manual submit path (`submit_bingo_score()`) does not yet enforce this live-window check. Add it when wiring the API route.

### 3. Player on Bingo roster

`player_id` must exist in `bingo_teams`. This is **not** the same roster as the EX Rating baseline CSV — only players assigned to Eve, Grace, or Rest for Bingo.

### 4. Chart on current board

`song` and `difficulty` must match a row in `bingo_charts` that falls inside the configured `board_width × board_width` grid. Charts outside the active board size are ignored even if present in the database.

Reference: `bingo_charts_on_board()` in `rating/bingo.py`.

### 5. Score validity

- Must be a positive integer
- Must not exceed the chart’s critical max score from `ArcadeMaxScores.csv` (`bingo_chart_max_score()`)

### 6. Personal best since competition start

The new score must be **strictly higher** than the player’s existing best on that chart since `bingo_settings.start_time`:

```sql
SELECT MAX(score)
FROM bingo_scores
WHERE player_id = $1
  AND song = $2
  AND difficulty = $3
  AND created_at >= $start_time
```

If a prior best exists and `new_score <= best`, reject.

---

## Database write

On success, insert one row into `bingo_scores`:

| Column | Value |
|---|---|
| `player_id` | From request |
| `display_name` | Looked up from `bingo_teams` |
| `team` | Looked up from `bingo_teams` |
| `song`, `difficulty`, `score` | From request |
| `accuracy`, judgement columns | From request (optional) |
| `source` | `'in_game'` for mod API; `'submission'` for site manual upload |
| `created_at` | Server default `NOW()` |

Schema: `supabase/migrations/20260711242000_bingo_scores_display_name.sql`

The board and scoreboard recompute leaders from best scores per chart per team — no separate rating table is updated.

---

## Chart identification

`song` and `difficulty` must use the same keys the game and database use. Format: `{song}/{difficulty}` (see `resolve_max_score_chart_key()` in `rating/imported_players.py`). Matching is case-insensitive for max-score lookup; board chart matching uses exact `song` + `difficulty` equality against `bingo_charts`.

**Examples from the seeded board:**

| Song | Difficulty |
|---|---|
| `NOISZ - Done In Love` | `UNBEATABLE` |
| `goin crazy` | `Hard` |
| `PROPERRHYTHM` | `Beginner` |
| `Motherbound` | `Star` |
| `Familiar Acoustic` | `Easy` |

Full seed list: `supabase/migrations/20260711230000_bingo_tables.sql`

The mod should read chart identity from the same in-game highscore / results data the EX mod uses (`song` + `difficulty` strings), not display names shown on the Bingo board UI.

---

## Player identification

Use the player’s UGS / internal ID (`player_id`), not display name.

Roster is in `bingo_teams`:

```sql
SELECT player_id, display_name, team FROM bingo_teams;
```

Teams: `Eve`, `Grace`, `Rest`.

`bingo_teams`, `bingo_charts`, and `bingo_scores` are publicly readable via Supabase RLS. The mod may fetch roster/board data for client-side UX, but **writes must go through the Render API** — never embed database credentials in the mod.

---

## Differences from EX Rating submission

| | EX Rating (`/submit`) | Bingo (`/submit/bingo`) |
|---|---|---|
| Payload | Full score list + ignored client `ex_rating` | Single chart score |
| Roster check | Baseline leaderboard CSV | `bingo_teams` |
| Improvement rule | EX / Standard rating must increase | Score must beat PB since `start_time` |
| Timing rule | None | Must be during live competition window |
| Rating recompute | Server-side EX Rating math | None — raw score only |
| `source` value | `in_game` | `in_game` |
| Activity feed | `leaderboard_activity` | Bingo claim feed (derived from score inserts) |

---

## Recommended mod flow

1. Player finishes a chart on the Bingo board during the live event.
2. Mod reads `player_id`, `song`, `difficulty`, `score`, and optional judgement fields from game state.
3. Mod optionally checks locally that the chart is on the board and the score beats the player’s known PB.
4. Mod POSTs to `/submit/bingo` with Bearer auth.
5. On success, show confirmation. On failure, show the server `error` string.

Only submit when the score is a new personal best for that chart — the server enforces this, but skipping obvious rejects in the mod reduces noise.

---

## Python reference (this repo)

| Function | Module | Purpose |
|---|---|---|
| `submit_bingo_score()` | `rating/bingo.py` | Validate + insert (site manual submit today) |
| `bingo_in_progress_day()` | `rating/bingo.py` | Whether competition is live |
| `bingo_chart_max_score()` | `rating/bingo.py` | Chart critical max |
| `bingo_charts_on_board()` | `rating/bingo.py` | Filter charts to active board |
| `load_bingo_teams_by_ex_rating()` | `rating/bingo.py` | Roster by team |
| `authenticate_bearer_token()` | `rating/submission_api.py` | Bearer auth |
| `resolve_max_score_chart_key()` | `rating/imported_players.py` | Song/difficulty key normalization |

---

## Server implementation checklist

Before the mod ships:

- [x] Add `POST /submit/bingo` to `api/main.py`
- [x] Add `process_bingo_mod_submission()` with live-window check, `source = 'in_game'`, judgement columns
- [ ] Redeploy Render service (`render.yaml`)
- [ ] Add mod repo doc mirroring this file under `Unbeatable-Mods/mods/Bingo/resources/`

---

## Local development

```powershell
cd unbeatable-ex-rating
$env:PYTHONPATH = "."
$env:DATABASE_URL = "postgresql://..."   # from .streamlit/secrets.toml
$env:SUBMIT_API_KEY = "dev-test-key"
pip install -r requirements.txt
uvicorn api.main:app --reload
```

Test (once route exists):

```powershell
curl -X POST http://localhost:8000/submit/bingo `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer dev-test-key" `
  -d '{"player_id":"mUdeR3emV3D0imF6t93ODeON50uw","song":"NOISZ - Done In Love","difficulty":"UNBEATABLE","score":1150000}'
```

---

## See also

- [`SUBMISSION_BACKEND.md`](SUBMISSION_BACKEND.md) — Render deploy, shared auth, EX endpoint
- [`MOD_API_INTEGRATION.md`](MOD_API_INTEGRATION.md) — live base URL
- [`LEADERBOARD_API.md`](LEADERBOARD_API.md) — EX Rating schema and formulas (not used for Bingo)
- EX mod reference: `Unbeatable-Mods/mods/EXRating/resources/MOD_API_INTEGRATION.md`
