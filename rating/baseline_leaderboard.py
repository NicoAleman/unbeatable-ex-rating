import csv
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from rating.constants import BASELINE_CSV_HEADERS, EX_RATING_BASELINE_PATH, EX_RATING_LEADERBOARD_DB_PATH
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
