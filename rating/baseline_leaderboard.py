import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from rating.constants import (
    BASELINE_CSV_HEADERS,
    EX_RATING_BASELINE_META_PATH,
    EX_RATING_BASELINE_PATH,
    EX_RATING_BASELINE_TOP_SCORES_PATH,
    EX_RATING_LEADERBOARD_DB_PATH,
)
from rating.ex_leaderboard_db import _connect as connect_sqlite


@dataclass(frozen=True)
class BaselineLeaderboardEntry:
    player_id: str
    display_name: str
    ex_rating: float
    last_updated: str


@dataclass(frozen=True)
class UpdatedRating:
    ex_rating: float
    last_updated: str


@dataclass(frozen=True)
class BaselineMeta:
    last_full_rebuild: str
    player_count: int = 0
    source_rebuild_dir: str = ""


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def load_baseline_meta(path: Path = EX_RATING_BASELINE_META_PATH) -> BaselineMeta | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    last_full_rebuild = str(raw.get("last_full_rebuild", "")).strip()
    if not last_full_rebuild:
        return None
    return BaselineMeta(
        last_full_rebuild=last_full_rebuild,
        player_count=int(raw.get("player_count") or 0),
        source_rebuild_dir=str(raw.get("source_rebuild_dir") or ""),
    )


def write_baseline_meta(
    meta: BaselineMeta,
    path: Path = EX_RATING_BASELINE_META_PATH,
) -> None:
    payload = {
        "last_full_rebuild": meta.last_full_rebuild,
        "player_count": meta.player_count,
        "source_rebuild_dir": meta.source_rebuild_dir,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_baseline_rebuild_cutoff(
    path: Path = EX_RATING_BASELINE_META_PATH,
) -> datetime | None:
    meta = load_baseline_meta(path)
    if meta is None:
        return None
    return parse_iso_timestamp(meta.last_full_rebuild)


def load_baseline_leaderboard_csv(
    csv_path: Path = EX_RATING_BASELINE_PATH,
) -> list[BaselineLeaderboardEntry]:
    if not csv_path.exists():
        return []

    text = csv_path.read_text(encoding="utf-8")
    reader = csv.DictReader(StringIO(text))
    entries: list[BaselineLeaderboardEntry] = []

    for row in reader:
        player_id = str(row.get("player_id", "")).strip()
        display_name = str(row.get("display_name", "")).strip()
        ex_rating_text = str(row.get("ex_rating", "")).strip()
        if not player_id or not display_name or not ex_rating_text:
            continue
        entries.append(
            BaselineLeaderboardEntry(
                player_id=player_id,
                display_name=display_name,
                ex_rating=float(ex_rating_text),
                last_updated=str(row.get("last_updated", "")).strip(),
            )
        )

    return entries


def format_baseline_leaderboard_csv(entries: list[BaselineLeaderboardEntry]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(BASELINE_CSV_HEADERS)
    for entry in entries:
        writer.writerow(
            [
                entry.player_id,
                entry.display_name,
                entry.ex_rating,
                entry.last_updated,
            ]
        )
    return buffer.getvalue()


def write_baseline_leaderboard_csv(
    entries: list[BaselineLeaderboardEntry],
    output_path: Path = EX_RATING_BASELINE_PATH,
) -> None:
    output_path.write_text(format_baseline_leaderboard_csv(entries), encoding="utf-8")


def export_baseline_leaderboard_from_sqlite(
    sqlite_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    output_path: Path = EX_RATING_BASELINE_PATH,
) -> int:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    conn = connect_sqlite(sqlite_path)
    try:
        rows = conn.execute(
            """
            SELECT player_id, display_name, ex_rating, last_updated
            FROM players
            ORDER BY ex_rating DESC, display_name COLLATE NOCASE ASC
            """
        ).fetchall()
    finally:
        conn.close()

    entries = [
        BaselineLeaderboardEntry(
            player_id=str(row["player_id"]),
            display_name=str(row["display_name"]),
            ex_rating=float(row["ex_rating"]),
            last_updated=str(row["last_updated"]),
        )
        for row in rows
    ]
    write_baseline_leaderboard_csv(entries, output_path)
    print(f"Wrote {len(entries)} players to {output_path}", file=sys.stderr)
    return len(entries)


def write_baseline_top_scores_from_rebuild(
    rebuild_top_scores_path: Path,
    output_path: Path = EX_RATING_BASELINE_TOP_SCORES_PATH,
) -> int:
    """Copy rebuild top-N score payload into the live baseline top-scores file."""
    if not rebuild_top_scores_path.is_file():
        raise FileNotFoundError(f"Missing rebuild top scores: {rebuild_top_scores_path}")
    payload = json.loads(rebuild_top_scores_path.read_text(encoding="utf-8"))
    by_player: dict[str, list[dict[str, object]]] = {}
    for player in payload.get("players") or []:
        player_id = str(player.get("player_id") or "").strip()
        if not player_id:
            continue
        rows: list[dict[str, object]] = []
        for score in player.get("scores") or []:
            song = str(score.get("song") or "").strip()
            difficulty = str(score.get("difficulty") or "").strip()
            if not song or not difficulty:
                continue
            rows.append(
                {
                    "song": song,
                    "difficulty": difficulty,
                    "score": int(score["score"]),
                }
            )
        if rows:
            by_player[player_id] = rows
    output_path.write_text(
        json.dumps({"by_player": by_player}, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(by_player)


def load_baseline_top_scores_for_player(
    player_id: str,
    path: Path = EX_RATING_BASELINE_TOP_SCORES_PATH,
) -> list[dict[str, object]]:
    if not player_id.strip() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = (payload.get("by_player") or {}).get(player_id.strip()) or []
    return [
        {
            "song": str(row.get("song") or "").strip(),
            "difficulty": str(row.get("difficulty") or "").strip(),
            "score": int(row["score"]),
        }
        for row in rows
        if str(row.get("song") or "").strip() and str(row.get("difficulty") or "").strip()
    ]


def merge_score_rows_preferring_higher(
    *sources: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Merge chart score rows, keeping the higher score per (song, difficulty).

    When scores tie, prefer the row that has accuracy / judgement metadata.
    """
    best: dict[tuple[str, str], dict[str, object]] = {}

    def _richness(row: dict[str, object]) -> int:
        return sum(
            1
            for key in ("accuracy", "miss_count", "max_combo", "critical_count", "cleared")
            if row.get(key) is not None
        )

    for rows in sources:
        for row in rows:
            song = str(row.get("song") or "").strip()
            difficulty = str(row.get("difficulty") or "").strip()
            if not song or not difficulty:
                continue
            try:
                score = int(row["score"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (song, difficulty)
            prev = best.get(key)
            if prev is None:
                best[key] = dict(row)
                best[key]["song"] = song
                best[key]["difficulty"] = difficulty
                best[key]["score"] = score
                continue
            prev_score = int(prev["score"])
            if score > prev_score:
                best[key] = dict(row)
                best[key]["song"] = song
                best[key]["difficulty"] = difficulty
                best[key]["score"] = score
            elif score == prev_score and _richness(row) > _richness(prev):
                merged = dict(prev)
                merged.update({k: v for k, v in row.items() if v is not None})
                merged["song"] = song
                merged["difficulty"] = difficulty
                merged["score"] = score
                best[key] = merged

    return list(best.values())
