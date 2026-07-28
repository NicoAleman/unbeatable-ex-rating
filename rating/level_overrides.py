"""Manual level corrections for charts where the save file level is wrong."""

# Keys match chart_key format: "Song Name/Difficulty"
LEVEL_OVERRIDES: dict[str, int] = {}


def resolve_chart_level(chart_key: str, json_level: int) -> int:
    return LEVEL_OVERRIDES.get(chart_key, json_level)
