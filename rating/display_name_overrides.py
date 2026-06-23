"""Manual display name corrections where the CSV title is not suitable for rating boards."""

# Keys match the raw song portion of chart keys (e.g. "SWING" from "SWING/Star").
SONG_DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    "BANG": "BANG!",
    "SWING": "SWING",
}


def resolve_song_display_name(raw_name: str, csv_name: str) -> str:
    return SONG_DISPLAY_NAME_OVERRIDES.get(raw_name, csv_name)
