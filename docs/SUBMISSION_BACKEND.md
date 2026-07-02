# EX Rating — Render Submission Backend

Implementation guide for the write API used by the [EXRating game mod](https://github.com/). The mod spec lives in the mod repo at `resources/RENDER_BACKEND.md`; this repo contains the server code.

---

## What was added

| Path | Purpose |
|---|---|
| `api/main.py` | FastAPI app: `GET /health`, `POST /submit` |
| `rating/submission_api.py` | Validation, server-side rating recompute, DB transaction |
| `render.yaml` | One-click Render deploy config |

The API reuses the same rating logic and Postgres writes as the Streamlit site.

---

## Architecture

```
Game mod (EXRating.dll)
    POST JSON  ──►  Render web service (/submit)
                        │
                        ▼
                   Supabase Postgres
                   (updated_ratings, scores, leaderboard_activity)
```

The mod sends `Authorization: Bearer <SUBMIT_API_KEY>`. The server holds `DATABASE_URL` (Supabase Postgres) and never exposes it to clients.

---

## Deploy to Render

### 1. Push this repo to GitHub

Render deploys from Git. Make sure `resources/ex_rating_baseline.csv` and reference files are in the repo (they already are).

### 2. Create a Render web service

**Option A — Blueprint:** In Render, choose **New → Blueprint** and point at this repo. It reads `render.yaml`.

**Option B — Manual:**

| Setting | Value |
|---|---|
| Runtime | Python |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |

### 3. Set environment variables

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase Postgres connection string (same password as Streamlit `supabase.db_url`) |
| `SUBMIT_API_KEY` | Long random secret shared with the mod config |

Generate a key, for example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`DATABASE_URL` is accepted first; `SUPABASE_DB_URL` also works for local dev.

### 4. Deploy and copy the URL

Render gives you something like:

`https://ex-rating-submit-api.onrender.com`

Your mod config endpoint is:

`https://ex-rating-submit-api.onrender.com/submit`

---

## Mod config

In `BepInEx/config/com.unbeatablemods.exrating.plugin.cfg`:

```ini
[Submission]
ApiUrl = https://your-service.onrender.com/submit
ApiKey = <same value as SUBMIT_API_KEY>
UgsWaitSeconds = 2
```

---

## API reference

### `GET /health`

```json
{ "ok": true }
```

### `POST /submit`

**Headers:**

- `Content-Type: application/json`
- `Authorization: Bearer <SUBMIT_API_KEY>`

**Body:**

```json
{
  "player_id": "DFUFGxHDMNp1cR00uFLu2RXXnptp",
  "ex_rating": 12.034,
  "last_updated": "2026-07-01T12:00:00+00:00",
  "scores": [
    {
      "song": "AFTERBURN",
      "difficulty": "Star",
      "score": 1794257,
      "accuracy": 97.2,
      "miss_count": 0,
      "max_combo": 900,
      "cleared": true,
      "critical_count": 850
    }
  ]
}
```

`ex_rating` from the client is **ignored for persistence** — the server recomputes it from `scores`.

**Success (200):**

```json
{
  "success": true,
  "message": "Rating update saved to the leaderboard.",
  "new_rank": 10
}
```

**Failure (400 / 401 / 500):**

```json
{ "success": false, "error": "Human-readable reason" }
```

---

## Server-side validation

1. Bearer token matches `SUBMIT_API_KEY`
2. `player_id` exists on baseline leaderboard CSV
3. `scores` is non-empty; each row has `song`, `difficulty`, `score`
4. Unknown charts are **skipped** (same as the Streamlit site’s `extract_classic_chart_scores`); at least one rateable chart must remain
5. If any score includes `accuracy`, every score must include it
6. EX Rating recomputed server-side from submitted scores
7. New rating must be strictly greater than current effective rating

On success, one Postgres transaction:

1. Upsert `updated_ratings`
2. Replace player rows in `scores` (`in_game` for mod API, `submission` for site)
3. Insert `leaderboard_activity` when EX rating increased, with `submission_source` (`in_game` or `submission`)

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

Test:

```powershell
curl http://localhost:8000/health

curl -X POST http://localhost:8000/submit `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer dev-test-key" `
  -d '{"player_id":"YOUR_ID","scores":[{"song":"AFTERBURN","difficulty":"Star","score":1794257,"accuracy":97.2,"miss_count":0,"max_combo":900,"cleared":true,"critical_count":850}]}'
```

---

## See also

- [`LEADERBOARD_API.md`](LEADERBOARD_API.md) — database schema, EX Rating formulas, SQL reference
- Mod repo `resources/RENDER_BACKEND.md` — mod-facing contract
