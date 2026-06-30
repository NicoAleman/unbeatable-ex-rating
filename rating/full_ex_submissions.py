from datetime import datetime, timezone

from rating.constants import DEFAULT_MAX_SCORES_PATH, SCORE_SOURCE_SUBMISSION
from rating.data import load_critical_max_scores
from rating.entries import chart_key, critical_count, is_classic_entry, miss_count, split_chart_key
from rating.formatting import format_rating_display
from rating.imported_players import resolve_max_score_chart_key
from rating.leaderboard_activity import record_leaderboard_activity
from rating.public_leaderboard import player_rank_on_leaderboard
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import load_updated_ratings_from_supabase, submit_player_update_to_supabase


def extract_classic_chart_scores(
    highscores: dict,
    max_scores_path=DEFAULT_MAX_SCORES_PATH,
) -> list[dict[str, object]]:
    """Return best Classic chart scores with accuracy metadata from a save file."""
    max_scores = load_critical_max_scores(max_scores_path)
    best_by_chart: dict[tuple[str, str], dict[str, object]] = {}

    for entry in highscores.get("highScores", []):
        if not is_classic_entry(entry):
            continue

        key = chart_key(entry["song"])
        if resolve_max_score_chart_key(*split_chart_key(key), max_scores) is None:
            continue

        song, difficulty = split_chart_key(key)
        score = int(entry.get("score", 0))
        chart = (song, difficulty)
        existing = best_by_chart.get(chart)
        if existing is not None and score <= int(existing["score"]):
            continue

        accuracy = entry.get("accuracy")
        best_by_chart[chart] = {
            "song": song,
            "difficulty": difficulty,
            "score": score,
            "accuracy": float(accuracy) * 100 if accuracy is not None else None,
            "miss_count": miss_count(entry),
            "max_combo": int(entry.get("maxCombo", 0)),
            "cleared": bool(entry.get("cleared", False)),
            "critical_count": critical_count(entry),
        }

    return sorted(best_by_chart.values(), key=lambda row: (row["song"], row["difficulty"]))


def validate_full_ex_rating_submission(
    current_rating: float,
    new_rating: float,
) -> tuple[bool, str | None]:
    if new_rating <= current_rating:
        return False, (
            f"Your submitted rating ({format_rating_display(new_rating)}) must be higher than "
            f"your current leaderboard rating ({format_rating_display(current_rating)})."
        )
    return True, None


def submit_full_ex_rating_update(
    *,
    player_id: str,
    ex_rating: float,
    highscores: dict,
    last_updated: str | None = None,
    prev_rating: float | None = None,
    prev_rank: int | None = None,
) -> tuple[bool, str]:
    if not supabase_configured():
        return False, "Supabase is not configured yet."

    scores = extract_classic_chart_scores(highscores)
    if not scores:
        return False, "No rated Classic charts found in that file."

    timestamp = last_updated or datetime.now(timezone.utc).isoformat()
    try:
        submit_player_update_to_supabase(
            player_id=player_id,
            ex_rating=ex_rating,
            last_updated=timestamp,
            scores=scores,
            source=SCORE_SOURCE_SUBMISSION,
        )

        if prev_rating is not None and prev_rank is not None:
            overrides = load_updated_ratings_from_supabase()
            stored_rating = overrides.get(player_id)
            ranked_rating = stored_rating.ex_rating if stored_rating is not None else ex_rating
            new_rank = player_rank_on_leaderboard(
                player_id,
                rating_overrides=overrides,
            )
            if new_rank is not None:
                record_leaderboard_activity(
                    player_id=player_id,
                    prev_rating=prev_rating,
                    new_rating=ranked_rating,
                    prev_rank=prev_rank,
                    new_rank=new_rank,
                    created_at=timestamp,
                )
    except Exception as error:
        return False, f"Could not save submission: {error}"

    return True, "Rating update saved to the leaderboard."
