# Mod integration handoff

For the **EXRating game mod** agent, see the mod repo:

`Unbeatable-Mods/mods/EXRating/resources/MOD_API_INTEGRATION.md`

For the **Bingo score upload mod**, see [`BINGO_MOD_API.md`](BINGO_MOD_API.md).

**Live API base URL:** `https://ex-rating-submit-api.onrender.com`

| Endpoint | URL |
|---|---|
| Health | `GET /health` |
| EX Rating submit | `POST /submit` |
| Bingo board | `GET /bingo/board` |
| Bingo submit | `POST /submit/bingo` |

The mod POSTs JSON with `Authorization: Bearer <SUBMIT_API_KEY>`. The API key is configured per-user in BepInEx config — not stored in either repo.
