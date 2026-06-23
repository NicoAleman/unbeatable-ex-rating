import json
from functools import lru_cache
from pathlib import Path


def load_highscores(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_arcade_max_scores_line(line: str) -> tuple[str, str, int] | None:
    """Return chart key, display name, and critical max score from one CSV row."""
    parts = line.rsplit(",", 3)
    if len(parts) != 4:
        return None
    head, level_str, _score, critical_str = parts
    if not level_str.isdigit() or not critical_str.isdigit():
        return None
    chart_key, _, display_name = head.partition(",")
    if not display_name:
        return None
    return chart_key, display_name, int(critical_str)


@lru_cache(maxsize=4)
def _load_arcade_max_scores_data(path_str: str) -> tuple[dict[str, int], dict[str, str]]:
    max_scores: dict[str, int] = {}
    display_names: dict[str, str] = {}
    for line in Path(path_str).read_text(encoding="utf-8").splitlines():
        parsed = _parse_arcade_max_scores_line(line)
        if parsed is None:
            continue
        chart_key, display_name, critical_max = parsed
        max_scores[chart_key] = critical_max
        song_id = chart_key.rsplit("/", 1)[0]
        display_names.setdefault(song_id, display_name)
    return max_scores, display_names


def load_critical_max_scores(path: Path) -> dict[str, int]:
    """Map chart keys (Song/Difficulty) to critical max score (last CSV column)."""
    return _load_arcade_max_scores_data(str(path))[0]


def load_song_display_names(path: Path) -> dict[str, str]:
    """Map raw song identifiers to display names (CSV column 2)."""
    return _load_arcade_max_scores_data(str(path))[1]
