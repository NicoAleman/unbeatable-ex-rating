import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rating.board import competition_ranks_for_values, player_ex_rating_with_completion
from rating.constants import (
    DEFAULT_MAX_SCORES_PATH,
    EX_RATING_LEADERBOARD_DB_PATH,
    FULL_EX_RATING_LEADERBOARD_PATH,
    LEADERBOARDS_JUNE27_DIR,
    RATING_OVERRIDES_PATH,
)
from rating.imported_players import build_ratings_from_imported_player
from rating.models import ChartRating

DEFAULT_INITIAL_UPDATED_AT = "2026-06-27T00:00:00+00:00"
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ExLeaderboardEntry:
    rank: int
    player_id: str
    player: str
    ex_rating: float
    last_updated: str


@dataclass(frozen=True)
class RatingOverride:
    ex_rating: float
    reason: str = ""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            player_name TEXT,
            ex_rating REAL NOT NULL,
            rank INTEGER NOT NULL,
            last_updated TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scores (
            player_id TEXT NOT NULL,
            song TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            score INTEGER NOT NULL,
            PRIMARY KEY (player_id, song, difficulty),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        );

        CREATE TABLE IF NOT EXISTS rating_overrides (
            player_id TEXT PRIMARY KEY,
            ex_rating REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_players_rank ON players(rank);
        CREATE INDEX IF NOT EXISTS idx_players_ex_rating ON players(ex_rating DESC);
        CREATE INDEX IF NOT EXISTS idx_players_display_name ON players(display_name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_scores_player ON scores(player_id);
        """
    )


def load_rating_overrides(
    overrides_path: Path = RATING_OVERRIDES_PATH,
) -> dict[str, RatingOverride]:
    if not overrides_path.exists():
        return {}

    raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    overrides: dict[str, RatingOverride] = {}
    for player_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        ex_rating = payload.get("ex_rating")
        if ex_rating is None:
            continue
        overrides[str(player_id).strip()] = RatingOverride(
            ex_rating=float(ex_rating),
            reason=str(payload.get("reason", "")).strip(),
        )
    return overrides


def _score_rows_from_player(player_id: str, player_data: dict) -> list[tuple]:
    best_by_chart: dict[tuple[str, str], int] = {}
    for score in player_data.get("scores", []):
        if score.get("speed") != "Classic":
            continue

        song = str(score.get("song", "")).strip()
        difficulty = str(score.get("difficulty", "")).strip()
        if not song or not difficulty:
            continue

        chart = (song, difficulty)
        value = int(score.get("score", 0))
        existing = best_by_chart.get(chart)
        if existing is None or value > existing:
            best_by_chart[chart] = value

    return [
        (player_id, song, difficulty, chart_score)
        for (song, difficulty), chart_score in best_by_chart.items()
    ]


def _recalculate_ranks(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT player_id, ex_rating FROM players ORDER BY ex_rating DESC, display_name COLLATE NOCASE"
    ).fetchall()
    ranks = competition_ranks_for_values([float(row["ex_rating"]) for row in rows])
    conn.executemany(
        "UPDATE players SET rank = ? WHERE player_id = ?",
        [(rank, row["player_id"]) for rank, row in zip(ranks, rows, strict=True)],
    )


def _store_rating_overrides(
    conn: sqlite3.Connection,
    overrides: dict[str, RatingOverride],
    *,
    updated_at: str,
) -> None:
    conn.execute("DELETE FROM rating_overrides")
    conn.executemany(
        """
        INSERT INTO rating_overrides (player_id, ex_rating, reason, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        [
            (player_id, override.ex_rating, override.reason, updated_at)
            for player_id, override in overrides.items()
        ],
    )


def _apply_rating_overrides(conn: sqlite3.Connection, overrides: dict[str, RatingOverride]) -> None:
    for player_id, override in overrides.items():
        conn.execute(
            "UPDATE players SET ex_rating = ? WHERE player_id = ?",
            (override.ex_rating, player_id),
        )


def rebuild_ex_ratings(conn: sqlite3.Connection) -> None:
    from rating.calculator import rate_chart
    from rating.chart_levels import load_chart_rating_levels, resolve_chart_rating_level
    from rating.data import load_critical_max_scores
    from rating.imported_players import (
        _leaderboard_score_to_highscore_entry,
        resolve_max_score_chart_key,
    )

    max_scores = load_critical_max_scores(DEFAULT_MAX_SCORES_PATH)
    chart_rating_levels = load_chart_rating_levels()
    player_ids = [
        row["player_id"]
        for row in conn.execute("SELECT player_id FROM players ORDER BY player_id").fetchall()
    ]

    for index, player_id in enumerate(player_ids, 1):
        score_rows = conn.execute(
            """
            SELECT song, difficulty, score
            FROM scores
            WHERE player_id = ?
            """,
            (player_id,),
        ).fetchall()

        best_by_chart: dict[str, ChartRating] = {}
        for score_row in score_rows:
            song = str(score_row["song"] or "").strip()
            difficulty = str(score_row["difficulty"] or "").strip()
            if not song or not difficulty:
                continue

            chart_key = resolve_max_score_chart_key(song, difficulty, max_scores)
            if chart_key is None:
                continue

            level = resolve_chart_rating_level(chart_key, chart_rating_levels)
            if level is None:
                continue

            entry = _leaderboard_score_to_highscore_entry(
                {"score": score_row["score"]},
                chart_key,
                level,
            )
            rating = rate_chart(entry, max_scores[chart_key])
            existing = best_by_chart.get(chart_key)
            if existing is None or rating.ex_rating > existing.ex_rating:
                best_by_chart[chart_key] = rating

        if not best_by_chart:
            conn.execute("DELETE FROM players WHERE player_id = ?", (player_id,))
            continue

        ex_rating = player_ex_rating_with_completion(list(best_by_chart.values()))
        conn.execute(
            "UPDATE players SET ex_rating = ? WHERE player_id = ?",
            (ex_rating, player_id),
        )

        if index % 5000 == 0:
            print(f"Recalculated ratings for {index} players…", file=sys.stderr)


def recalculate_all_ex_ratings(
    db_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    overrides_path: Path = RATING_OVERRIDES_PATH,
) -> None:
    """Recalculate stored EX ratings from scores and re-apply manual overrides."""
    overrides = load_rating_overrides(overrides_path)
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN")
        rebuild_ex_ratings(conn)
        _apply_rating_overrides(conn, overrides)
        _recalculate_ranks(conn)
        conn.execute(
            """
            INSERT INTO metadata (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("last_rating_recalculation", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def build_ex_leaderboard_database(
    db_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    leaderboard_scores_dir: Path = LEADERBOARDS_JUNE27_DIR,
    overrides_path: Path = RATING_OVERRIDES_PATH,
    *,
    initial_updated_at: str = DEFAULT_INITIAL_UPDATED_AT,
    max_scores_path: Path = DEFAULT_MAX_SCORES_PATH,
) -> int:
    overrides = load_rating_overrides(overrides_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = _connect(db_path)
    try:
        create_schema(conn)
        conn.execute("BEGIN")

        player_rows: list[tuple] = []
        score_rows: list[tuple] = []

        for index, player_path in enumerate(sorted(leaderboard_scores_dir.glob("*.json")), 1):
            player_data = json.loads(player_path.read_text(encoding="utf-8"))
            player_id = str(player_data.get("playerId", "")).strip()
            display_name = str(player_data.get("displayName", "")).strip()
            player_name = str(player_data.get("playerName", "")).strip() or None
            if not player_id:
                print(
                    f"Warning: skipping {player_path.name} with no playerId",
                    file=sys.stderr,
                )
                continue
            if not display_name:
                print(
                    f"Warning: skipping {player_path.name} with no displayName",
                    file=sys.stderr,
                )
                continue

            ratings = build_ratings_from_imported_player(player_data, max_scores_path)
            if not ratings:
                continue

            ex_rating = player_ex_rating_with_completion(ratings)
            override = overrides.get(player_id)
            if override is not None:
                ex_rating = override.ex_rating

            player_rows.append(
                (
                    player_id,
                    display_name,
                    player_name,
                    ex_rating,
                    0,
                    initial_updated_at,
                )
            )
            score_rows.extend(_score_rows_from_player(player_id, player_data))

            if index % 5000 == 0:
                print(f"Processed {index} player files…", file=sys.stderr)

        conn.executemany(
            """
            INSERT INTO players (
                player_id, display_name, player_name, ex_rating, rank, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            player_rows,
        )
        conn.executemany(
            """
            INSERT INTO scores (player_id, song, difficulty, score)
            VALUES (?, ?, ?, ?)
            """,
            score_rows,
        )

        _store_rating_overrides(conn, overrides, updated_at=initial_updated_at)
        _apply_rating_overrides(conn, overrides)
        _recalculate_ranks(conn)

        conn.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("last_full_rebuild", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        player_count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    finally:
        conn.close()

    return int(player_count)


def _load_ex_leaderboard_from_csv(
    csv_path: Path = FULL_EX_RATING_LEADERBOARD_PATH,
    *,
    search: str = "",
    limit: int | None = None,
) -> list[ExLeaderboardEntry]:
    from rating.imported_players import load_full_ex_leaderboard_csv

    rankings = load_full_ex_leaderboard_csv(csv_path)
    trimmed_search = search.strip()
    if trimmed_search:
        needle = trimmed_search.casefold()
        rankings = [entry for entry in rankings if needle in entry.player.casefold()]
    if limit is not None:
        rankings = rankings[:limit]

    return [
        ExLeaderboardEntry(
            rank=int(entry.rank),
            player_id=str(entry.player_id),
            player=str(entry.player),
            ex_rating=float(entry.ex_rating),
            last_updated="",
        )
        for entry in rankings
    ]


def leaderboard_available(
    db_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    csv_path: Path = FULL_EX_RATING_LEADERBOARD_PATH,
) -> bool:
    from rating.leaderboard_config import use_sql_leaderboard

    if not use_sql_leaderboard():
        return csv_path.exists()

    from rating.supabase_config import supabase_configured
    from rating.supabase_leaderboard import supabase_has_data

    if supabase_configured():
        return supabase_has_data()
    return db_path.exists()


def load_ex_leaderboard(
    db_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    csv_path: Path = FULL_EX_RATING_LEADERBOARD_PATH,
    *,
    search: str = "",
    limit: int | None = None,
) -> list[ExLeaderboardEntry]:
    from rating.leaderboard_config import use_sql_leaderboard

    if not use_sql_leaderboard():
        if not csv_path.exists():
            return []
        return _load_ex_leaderboard_from_csv(csv_path, search=search, limit=limit)

    from rating.supabase_config import supabase_configured
    from rating.supabase_leaderboard import load_ex_leaderboard_from_supabase

    if supabase_configured():
        return load_ex_leaderboard_from_supabase(search=search, limit=limit)

    if not db_path.exists():
        return []

    conn = _connect(db_path)
    try:
        query = """
            SELECT rank, player_id, display_name, ex_rating, last_updated
            FROM players
        """
        params: list[object] = []
        trimmed_search = search.strip()
        if trimmed_search:
            query += " WHERE LOWER(display_name) LIKE LOWER(?)"
            params.append(f"%{trimmed_search}%")
        query += " ORDER BY rank ASC, display_name COLLATE NOCASE ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return [
        ExLeaderboardEntry(
            rank=int(row["rank"]),
            player_id=str(row["player_id"]),
            player=str(row["display_name"]),
            ex_rating=float(row["ex_rating"]),
            last_updated=str(row["last_updated"]),
        )
        for row in rows
    ]


def get_player_count(db_path: Path = EX_RATING_LEADERBOARD_DB_PATH) -> int:
    if not db_path.exists():
        return 0
    conn = _connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0])
    finally:
        conn.close()
