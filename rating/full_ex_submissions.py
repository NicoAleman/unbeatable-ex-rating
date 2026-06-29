from datetime import datetime, timezone

from rating.constants import DEFAULT_MAX_SCORES_PATH, SCORE_SOURCE_SUBMISSION
from rating.data import load_critical_max_scores
from rating.entries import chart_key, is_classic_entry, split_chart_key
from rating.formatting import format_rating_display
from rating.imported_players import resolve_max_score_chart_key
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import submit_player_update_to_supabase


def extract_classic_chart_scores(
    highscores: dict,
    max_scores_path=DEFAULT_MAX_SCORES_PATH,
) -> list[tuple[str, str, int]]:
    """Return best Classic chart scores as (song, difficulty, score) tuples."""
    max_scores = load_critical_max_scores(max_scores_path)
    best_by_chart: dict[tuple[str, str], int] = {}

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
        if existing is None or score > existing:
            best_by_chart[chart] = score

    return [
        (song, difficulty, chart_score)
        for (song, difficulty), chart_score in sorted(best_by_chart.items())
    ]


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
    except Exception as error:
        return False, f"Could not save submission: {error}"

    return True, "Rating update saved to the leaderboard."
