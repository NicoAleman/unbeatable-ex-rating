import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rating.constants import PROJECT_ROOT, SHARED_EX_RANKINGS_PATH


@dataclass
class SharedExRanking:
    player: str
    ex_rating: float
    date_added: str


def format_date_added(date_added: str) -> str:
    return datetime.fromisoformat(date_added).strftime("%B %d, %Y")


def load_shared_ex_rankings(path: Path = SHARED_EX_RANKINGS_PATH) -> list[SharedExRanking]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rankings = [
        SharedExRanking(
            player=entry["player"],
            ex_rating=float(entry["ex_rating"]),
            date_added=entry["date_added"],
        )
        for entry in data.get("rankings", [])
    ]
    return sorted(rankings, key=lambda ranking: ranking.ex_rating, reverse=True)


def _git_last_updated(path: Path) -> datetime | None:
    try:
        relative = path.relative_to(PROJECT_ROOT)
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(relative)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return datetime.fromisoformat(result.stdout.strip())
    except (OSError, ValueError):
        pass
    return None


def format_shared_rankings_last_updated(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%B %d, %Y at %I:%M %p UTC")


def shared_rankings_last_updated(path: Path = SHARED_EX_RANKINGS_PATH) -> datetime | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    manual = data.get("last_updated")
    if manual:
        return datetime.fromisoformat(manual)

    git_time = _git_last_updated(path)
    if git_time is not None:
        return git_time

    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
