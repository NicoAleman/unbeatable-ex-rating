import json
import re
from pathlib import Path


def load_highscores(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_critical_max_scores(path: Path) -> dict[str, int]:
    """Map chart keys (Song/Difficulty) to critical max score (last CSV column)."""
    max_scores: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([^,]+),.*?,(\d+),(\d+),(\d+)$", line)
        if match:
            max_scores[match.group(1)] = int(match.group(4))
    return max_scores
