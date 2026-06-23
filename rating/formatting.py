DISPLAY_RATING_DECIMALS = 3


def format_rating_display(value: float) -> str:
    return f"{value:.{DISPLAY_RATING_DECIMALS}f}"
