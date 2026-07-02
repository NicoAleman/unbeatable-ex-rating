from rating.constants import DEFAULT_MAX_SCORES_PATH, DISPLAY_RATING_DECIMALS


def format_rating_display(value: float) -> str:
    return f"{value:.{DISPLAY_RATING_DECIMALS}f}"


def ratings_are_equal(prev_rating: float, new_rating: float) -> bool:
    return float(prev_rating) == float(new_rating)


def format_potential_gain_display(value: float) -> str:
    return f"+{value:.{DISPLAY_RATING_DECIMALS}f}"


def format_activity_rating_delta(prev_rating: float, new_rating: float) -> str | None:
    prev = float(prev_rating)
    new = float(new_rating)
    if new <= prev:
        return None
    if format_rating_display(prev) == format_rating_display(new):
        return format_potential_gain_display(0.0)
    return format_potential_gain_display(new - prev)


def format_song_display_name(raw_name: str, max_scores_path=None) -> str:
    from rating.constants import DEFAULT_MAX_SCORES_PATH
    from rating.data import load_song_display_names
    from rating.display_name_overrides import resolve_song_display_name

    path = max_scores_path or DEFAULT_MAX_SCORES_PATH
    csv_name = load_song_display_names(path).get(raw_name, raw_name)
    return resolve_song_display_name(raw_name, csv_name)
