from rating.constants import (
    DEFAULT_MAX_SCORES_PATH,
    DISPLAY_RATING_DECIMALS,
    RATING_COMPARISON_DECIMALS,
)


def format_rating_display(value: float) -> str:
    return f"{value:.{DISPLAY_RATING_DECIMALS}f}"


def format_rating_comparison(value: float) -> str:
    return f"{value:.{RATING_COMPARISON_DECIMALS}f}"


def as_stored_rating(value: float) -> float:
    """Normalize a rating for increase comparisons (4 decimal places)."""
    return float(format_rating_comparison(value))

def ratings_are_equal(prev_rating: float, new_rating: float) -> bool:
    return format_rating_comparison(prev_rating) == format_rating_comparison(new_rating)


def rating_increased(prev_rating: float, new_rating: float) -> bool:
    return as_stored_rating(new_rating) > as_stored_rating(prev_rating)


def format_potential_gain_display(value: float) -> str:
    return f"+{value:.{DISPLAY_RATING_DECIMALS}f}"


def format_activity_rating_delta(prev_rating: float, new_rating: float) -> str | None:
    if not rating_increased(prev_rating, new_rating):
        return None
    return format_potential_gain_display(
        as_stored_rating(new_rating) - as_stored_rating(prev_rating)
    )


def format_song_display_name(raw_name: str, max_scores_path=None) -> str:
    from rating.constants import DEFAULT_MAX_SCORES_PATH
    from rating.data import load_song_display_names
    from rating.display_name_overrides import resolve_song_display_name

    path = max_scores_path or DEFAULT_MAX_SCORES_PATH
    csv_name = load_song_display_names(path).get(raw_name, raw_name)
    return resolve_song_display_name(raw_name, csv_name)
