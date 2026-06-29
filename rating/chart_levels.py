import json
from pathlib import Path

from rating.constants import CHART_RATING_LEVELS_PATH, PROJECT_ROOT
from rating.entries import chart_key, is_classic_entry


def collect_levels_from_highscores(path: Path, levels: dict[str, int]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data.get("highScores", []):
        if not is_classic_entry(entry):
            continue
        key = chart_key(entry["song"])
        level = int(entry.get("level") or 0)
        if level <= 0:
            continue
        levels[key] = max(levels.get(key, 0), level)


def build_chart_rating_levels(sources: list[Path]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for source in sources:
        if not source.exists():
            continue
        collect_levels_from_highscores(source, levels)
    return dict(sorted(levels.items()))


def load_chart_rating_levels(path: Path = CHART_RATING_LEVELS_PATH) -> dict[str, int]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_chart_rating_level(
    chart_key: str,
    chart_rating_levels: dict[str, int],
) -> int | None:
    """Look up a chart's rating level by song/difficulty key."""
    mapped = chart_rating_levels.get(chart_key)
    if mapped is not None and mapped > 0:
        return mapped

    key_lower = chart_key.casefold()
    for level_key, level in chart_rating_levels.items():
        if level_key.casefold() == key_lower and level > 0:
            return level
    return None


def write_chart_rating_levels(
    sources: list[Path],
    output_path: Path = CHART_RATING_LEVELS_PATH,
) -> dict[str, int]:
    levels = build_chart_rating_levels(sources)
    output_path.write_text(json.dumps(levels, indent=2), encoding="utf-8")
    return levels


DEFAULT_LEVEL_SOURCES = [
    Path(r"c:\Users\NicoA\Downloads\null_scores.json"),
    Path(r"c:\Users\NicoA\Downloads\Bobob_scores.json"),
]

if __name__ == "__main__":
    levels = write_chart_rating_levels(DEFAULT_LEVEL_SOURCES)
    print(f"Wrote {len(levels)} chart levels to {CHART_RATING_LEVELS_PATH}")
