"""Validate and persist EX Rating submissions from the game mod API."""

from dataclasses import dataclass
from datetime import datetime, timezone

from rating.baseline_leaderboard import UpdatedRating, load_baseline_leaderboard_csv
from rating.board import player_ex_rating_with_completion, player_standard_rating_with_completion
from rating.chart_levels import load_chart_rating_levels, resolve_chart_rating_level
from rating.constants import DEFAULT_MAX_SCORES_PATH, SCORE_SOURCE_IN_GAME, SCORE_SOURCE_SUBMISSION
from rating.data import load_critical_max_scores
from rating.formatting import format_rating_display
from rating.imported_players import (
    build_ratings_from_stored_scores,
    resolve_max_score_chart_key,
    stored_scores_have_accuracy,
)
from rating.public_leaderboard import merge_baseline_with_updated_ratings, rank_leaderboard_entries
from rating.supabase_config import get_supabase_db_url
from rating.supabase_leaderboard import (
    _batched,
    _connect_postgres,
    load_player_scores_from_supabase,
    load_updated_ratings_from_supabase,
)

import psycopg2.extras

REQUIRED_SCORE_FIELDS = ("song", "difficulty", "score")


@dataclass(frozen=True)
class SubmissionResult:
    success: bool
    message: str | None = None
    error: str | None = None
    new_rank: int | None = None
    ex_rating: float | None = None


@dataclass(frozen=True)
class SubmissionImprovement:
    computed_ex_rating: float
    computed_standard_rating: float
    prev_standard_rating: float
    ex_rating_improved: bool
    standard_rating_improved: bool
    has_accuracy_metadata: bool

    @property
    def accepted(self) -> bool:
        return self.ex_rating_improved or self.standard_rating_improved


def authenticate_bearer_token(authorization: str | None, expected_key: str | None) -> str | None:
    if not expected_key:
        return "Submission API is not configured."
    if not authorization or not authorization.startswith("Bearer "):
        return "Missing or invalid Authorization header."
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected_key:
        return "Invalid API key."
    return None


def get_effective_rating(player_id: str) -> tuple[float | None, str | None]:
    baseline = {entry.player_id: entry for entry in load_baseline_leaderboard_csv()}
    entry = baseline.get(player_id)
    if entry is None:
        return None, "Player is not on the baseline leaderboard."

    overrides = load_updated_ratings_from_supabase()
    override = overrides.get(player_id)
    if override is not None:
        return override.ex_rating, None
    return entry.ex_rating, None


def get_previous_standard_rating(player_id: str) -> float:
    score_rows = load_player_scores_from_supabase(player_id)
    if not score_rows or not stored_scores_have_accuracy(score_rows):
        return 0.0

    ratings = build_ratings_from_stored_scores(score_rows)
    if not ratings:
        return 0.0
    return player_standard_rating_with_completion(ratings)


def _score_has_accuracy(score: dict[str, object]) -> bool:
    return score.get("accuracy") is not None


def normalize_submission_scores(raw_scores: object) -> tuple[list[dict[str, object]], str | None]:
    if not isinstance(raw_scores, list) or not raw_scores:
        return [], "scores must be a non-empty list."

    max_scores = load_critical_max_scores(DEFAULT_MAX_SCORES_PATH)
    levels = load_chart_rating_levels()
    normalized: list[dict[str, object]] = []
    accuracy_flags: list[bool] = []

    for index, raw_score in enumerate(raw_scores):
        if not isinstance(raw_score, dict):
            return [], f"scores[{index}] must be an object."

        for field in REQUIRED_SCORE_FIELDS:
            if field not in raw_score or raw_score[field] in (None, ""):
                return [], f"scores[{index}] is missing `{field}`."

        song = str(raw_score["song"]).strip()
        difficulty = str(raw_score["difficulty"]).strip()
        if not song or not difficulty:
            return [], f"scores[{index}] has an empty song or difficulty."

        chart_key = resolve_max_score_chart_key(song, difficulty, max_scores)
        if chart_key is None:
            continue

        level = resolve_chart_rating_level(chart_key, levels)
        if level is None:
            continue

        row: dict[str, object] = {
            "song": song,
            "difficulty": difficulty,
            "score": int(raw_score["score"]),
        }
        if "accuracy" in raw_score and raw_score["accuracy"] is not None:
            row["accuracy"] = float(raw_score["accuracy"])
        if "miss_count" in raw_score and raw_score["miss_count"] is not None:
            row["miss_count"] = int(raw_score["miss_count"])
        if "max_combo" in raw_score and raw_score["max_combo"] is not None:
            row["max_combo"] = int(raw_score["max_combo"])
        if "cleared" in raw_score and raw_score["cleared"] is not None:
            row["cleared"] = bool(raw_score["cleared"])
        if "critical_count" in raw_score and raw_score["critical_count"] is not None:
            row["critical_count"] = int(raw_score["critical_count"])

        normalized.append(row)
        accuracy_flags.append(_score_has_accuracy(row))

    if not normalized:
        return [], "No rated Classic charts found in submission."

    if any(accuracy_flags) and not all(accuracy_flags):
        return [], "If any score includes accuracy, every score must include accuracy."

    normalized.sort(key=lambda row: (str(row["song"]), str(row["difficulty"])))
    return normalized, None


def recompute_ex_rating(scores: list[dict[str, object]]) -> float:
    ratings = build_ratings_from_stored_scores(scores)
    if not ratings:
        return 0.0
    return player_ex_rating_with_completion(ratings)


def recompute_standard_rating(scores: list[dict[str, object]]) -> float:
    if not stored_scores_have_accuracy(scores):
        return 0.0
    ratings = build_ratings_from_stored_scores(scores)
    if not ratings:
        return 0.0
    return player_standard_rating_with_completion(ratings)


def evaluate_submission_improvement(
    *,
    player_id: str,
    scores: list[dict[str, object]],
    prev_ex_rating: float,
) -> SubmissionImprovement:
    computed_ex_rating = recompute_ex_rating(scores)
    prev_standard_rating = get_previous_standard_rating(player_id)
    computed_standard_rating = recompute_standard_rating(scores)
    return SubmissionImprovement(
        computed_ex_rating=computed_ex_rating,
        computed_standard_rating=computed_standard_rating,
        prev_standard_rating=prev_standard_rating,
        ex_rating_improved=computed_ex_rating > prev_ex_rating,
        standard_rating_improved=(
            stored_scores_have_accuracy(scores)
            and computed_standard_rating > prev_standard_rating
        ),
        has_accuracy_metadata=stored_scores_have_accuracy(scores),
    )


def submission_rejection_message(
    *,
    prev_ex_rating: float,
    improvement: SubmissionImprovement,
) -> str:
    ex_part = (
        f"Your submitted EX Rating ({format_rating_display(improvement.computed_ex_rating)}) must be higher than "
        f"your current leaderboard rating ({format_rating_display(prev_ex_rating)})."
    )
    if improvement.has_accuracy_metadata:
        standard_part = (
            f"Your submitted Standard Rating ({format_rating_display(improvement.computed_standard_rating)}) must be higher than "
            f"your stored Standard Rating ({format_rating_display(improvement.prev_standard_rating)})."
        )
        return f"{ex_part} {standard_part}"
    return ex_part


def validate_rating_submission(
    *,
    player_id: str,
    current_ex_rating: float,
    scores: list[dict[str, object]],
) -> tuple[bool, str | None]:
    if not scores:
        return False, "No rated Classic charts found in submission."

    improvement = evaluate_submission_improvement(
        player_id=player_id,
        scores=scores,
        prev_ex_rating=current_ex_rating,
    )
    if improvement.computed_ex_rating <= 0:
        return False, "No rated Classic charts found in submission."
    if improvement.accepted:
        return True, None

    return False, submission_rejection_message(
        prev_ex_rating=current_ex_rating,
        improvement=improvement,
    )


def compute_rank_after_update(
    player_id: str,
    new_rating: float,
    *,
    last_updated: str,
    overrides: dict[str, UpdatedRating] | None = None,
) -> int | None:
    baseline = load_baseline_leaderboard_csv()
    if not baseline:
        return None

    merged_overrides = dict(overrides or load_updated_ratings_from_supabase())
    merged_overrides[player_id] = UpdatedRating(
        ex_rating=float(new_rating),
        last_updated=last_updated,
    )
    merged = merge_baseline_with_updated_ratings(baseline, merged_overrides)
    ranked = rank_leaderboard_entries(merged)
    for entry in ranked:
        if entry.player_id == player_id:
            return entry.rank
    return None


def _write_submission_transaction(
    *,
    player_id: str,
    ex_rating: float,
    last_updated: str,
    scores: list[dict[str, object]],
    prev_rating: float,
    prev_rank: int,
    new_rank: int,
    record_activity: bool,
    submission_source: str | None = None,
    db_url: str | None = None,
) -> None:
    score_source = submission_source or SCORE_SOURCE_SUBMISSION
    postgres = _connect_postgres(db_url)
    score_payload = [
        (
            player_id,
            str(score["song"]),
            str(score["difficulty"]),
            int(score["score"]),
            score_source,
            score.get("accuracy"),
            score.get("miss_count"),
            score.get("max_combo"),
            score.get("cleared"),
            score.get("critical_count"),
        )
        for score in scores
    ]

    try:
        with postgres:
            with postgres.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO updated_ratings (player_id, ex_rating, last_updated)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (player_id) DO UPDATE SET
                        ex_rating = EXCLUDED.ex_rating,
                        last_updated = EXCLUDED.last_updated
                    """,
                    (player_id, float(ex_rating), last_updated),
                )
                cur.execute(
                    "DELETE FROM scores WHERE player_id = %s AND source = %s",
                    (player_id, score_source),
                )
                for batch in _batched(score_payload):
                    psycopg2.extras.execute_batch(
                        cur,
                        """
                        INSERT INTO scores (
                            player_id, song, difficulty, score, source,
                            accuracy, miss_count, max_combo, cleared, critical_count
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (player_id, song, difficulty) DO UPDATE SET
                            score = EXCLUDED.score,
                            source = EXCLUDED.source,
                            accuracy = EXCLUDED.accuracy,
                            miss_count = EXCLUDED.miss_count,
                            max_combo = EXCLUDED.max_combo,
                            cleared = EXCLUDED.cleared,
                            critical_count = EXCLUDED.critical_count
                        """,
                        batch,
                    )

                if record_activity:
                    cur.execute(
                        """
                        INSERT INTO leaderboard_activity (
                            player_id, prev_rating, new_rating, prev_rank, new_rank,
                            created_at, submission_source
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            player_id,
                            float(prev_rating),
                            float(ex_rating),
                            int(prev_rank),
                            int(new_rank),
                            last_updated,
                            submission_source,
                        ),
                    )
        postgres.commit()
    finally:
        postgres.close()


def process_player_submission(
    player_id: str,
    scores: list[dict[str, object]],
    last_updated: str | None = None,
    *,
    submission_source: str | None = None,
) -> SubmissionResult:
    if not get_supabase_db_url():
        return SubmissionResult(success=False, error="Database is not configured.")

    prev_ex_rating, player_error = get_effective_rating(player_id)
    if player_error or prev_ex_rating is None:
        return SubmissionResult(success=False, error=player_error or "Player not found.")

    if not scores:
        return SubmissionResult(success=False, error="No rated Classic charts found in submission.")

    improvement = evaluate_submission_improvement(
        player_id=player_id,
        scores=scores,
        prev_ex_rating=prev_ex_rating,
    )
    if improvement.computed_ex_rating <= 0:
        return SubmissionResult(success=False, error="No rated Classic charts found in submission.")

    if not improvement.accepted:
        return SubmissionResult(
            success=False,
            error=submission_rejection_message(
                prev_ex_rating=prev_ex_rating,
                improvement=improvement,
            ),
        )

    timestamp = last_updated or datetime.now(timezone.utc).isoformat()
    stored_ex_rating = (
        improvement.computed_ex_rating
        if improvement.ex_rating_improved
        else prev_ex_rating
    )

    overrides = load_updated_ratings_from_supabase()
    prev_rank = compute_rank_after_update(
        player_id,
        prev_ex_rating,
        last_updated=timestamp,
        overrides=overrides,
    )
    if prev_rank is None:
        return SubmissionResult(success=False, error="Could not determine current leaderboard rank.")

    rank_rating = stored_ex_rating
    new_rank = compute_rank_after_update(
        player_id,
        rank_rating,
        last_updated=timestamp,
        overrides=overrides,
    )
    if new_rank is None:
        return SubmissionResult(success=False, error="Could not determine updated leaderboard rank.")

    try:
        _write_submission_transaction(
            player_id=player_id,
            ex_rating=stored_ex_rating,
            last_updated=timestamp,
            scores=scores,
            prev_rating=prev_ex_rating,
            prev_rank=prev_rank,
            new_rank=new_rank,
            record_activity=improvement.ex_rating_improved,
            submission_source=submission_source,
        )
    except Exception as error:
        return SubmissionResult(success=False, error=f"Could not save submission: {error}")

    message = "Rating update saved to the leaderboard."
    if improvement.standard_rating_improved and not improvement.ex_rating_improved:
        message = "Score update saved to the leaderboard."

    return SubmissionResult(
        success=True,
        message=message,
        ex_rating=stored_ex_rating,
        new_rank=new_rank,
    )


def process_mod_submission(payload: dict[str, object]) -> SubmissionResult:
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        return SubmissionResult(success=False, error="player_id is required.")

    scores, scores_error = normalize_submission_scores(payload.get("scores"))
    if scores_error:
        return SubmissionResult(success=False, error=scores_error)

    last_updated_raw = payload.get("last_updated")
    last_updated = (
        last_updated_raw.strip()
        if isinstance(last_updated_raw, str) and last_updated_raw.strip()
        else None
    )
    return process_player_submission(
        player_id,
        scores,
        last_updated=last_updated,
        submission_source=SCORE_SOURCE_IN_GAME,
    )
