import os

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from rating.bingo import get_bingo_board_for_mod, process_bingo_mod_submission
from rating.submission_api import authenticate_bearer_token, process_mod_submission

app = FastAPI(title="UNBEATABLE Submission API")


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    player_id: str
    ex_rating: float | None = None
    last_updated: str | None = None
    scores: list[dict]


class BingoSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    player_id: str
    song: str
    difficulty: str
    score: int
    accuracy: float | None = None
    critical: int | None = None
    perfect: int | None = None
    great: int | None = None
    good: int | None = None
    okay: int | None = None
    barely: int | None = None
    miss: int | None = None


def _expected_api_key() -> str | None:
    return os.environ.get("SUBMIT_API_KEY") or os.environ.get("SUBMISSION_API_KEY")


def _error_response(status_code: int, error: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"success": False, "error": error})


def _require_auth(authorization: str | None) -> JSONResponse | None:
    error = authenticate_bearer_token(authorization, _expected_api_key())
    if error:
        return _error_response(401, error)
    return None


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/bingo/board")
def bingo_board():
    """Public read of the active Bingo board charts (for Arcade song filter)."""
    try:
        return get_bingo_board_for_mod()
    except Exception as exc:  # noqa: BLE001 — surface DB/config failures to the client
        return _error_response(500, f"Could not load Bingo board: {exc}")


@app.post("/submit")
def submit(
    body: SubmitRequest,
    authorization: str | None = Header(default=None),
):
    auth_error = _require_auth(authorization)
    if auth_error is not None:
        return auth_error

    result = process_mod_submission(body.model_dump())
    if not result.success:
        status_code = 500 if result.error and result.error.startswith("Could not save submission:") else 400
        return _error_response(status_code, result.error or "Submission rejected.")

    return {
        "success": True,
        "message": result.message or "Rating update saved to the leaderboard.",
        "new_rank": result.new_rank,
    }


@app.post("/submit/bingo")
def submit_bingo(
    body: BingoSubmitRequest,
    authorization: str | None = Header(default=None),
):
    auth_error = _require_auth(authorization)
    if auth_error is not None:
        return auth_error

    success, message = process_bingo_mod_submission(body.model_dump())
    if not success:
        status_code = 500 if message.startswith("Could not save score:") else 400
        return _error_response(status_code, message)

    return {
        "success": True,
        "message": message,
    }
