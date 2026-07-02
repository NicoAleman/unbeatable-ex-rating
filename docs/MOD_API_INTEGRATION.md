# Mod integration handoff

For the **EXRating game mod** agent, see the mod repo:

`Unbeatable-Mods/mods/EXRating/resources/MOD_API_INTEGRATION.md`

**Live API base URL:** `https://ex-rating-submit-api.onrender.com`

| Endpoint | URL |
|---|---|
| Health | `GET /health` |
| Submit | `POST /submit` |

The mod POSTs JSON with `Authorization: Bearer <SUBMIT_API_KEY>`. The API key is configured per-user in BepInEx config — not stored in either repo.
