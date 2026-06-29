import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from rating.constants import EX_RATING_LEADERBOARD_DB_PATH
from rating.ex_leaderboard_db import ExLeaderboardEntry, _connect as connect_sqlite
from rating.supabase_config import get_supabase_db_url

BATCH_SIZE = 5000


def _connect_postgres(db_url: str | None = None):
    url = db_url or get_supabase_db_url()
    if not url:
        raise RuntimeError(
            "Supabase is not configured. Set supabase.db_url in .streamlit/secrets.toml "
            "or SUPABASE_DB_URL in the environment."
        )
    return psycopg2.connect(url)


def supabase_has_data(db_url: str | None = None) -> bool:
    if not get_supabase_db_url() and not db_url:
        return False
    conn = _connect_postgres(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM players LIMIT 1)")
            return bool(cur.fetchone()[0])
    finally:
        conn.close()


def load_ex_leaderboard_from_supabase(
    *,
    search: str = "",
    limit: int | None = None,
    db_url: str | None = None,
) -> list[ExLeaderboardEntry]:
    conn = _connect_postgres(db_url)
    try:
        query = """
            SELECT rank, player_id, display_name, ex_rating, last_updated
            FROM players
        """
        params: list[object] = []
        trimmed_search = search.strip()
        if trimmed_search:
            query += " WHERE display_name ILIKE %s"
            params.append(f"%{trimmed_search}%")
        query += " ORDER BY rank ASC, display_name ASC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        ExLeaderboardEntry(
            rank=int(row["rank"]),
            player_id=str(row["player_id"]),
            player=str(row["display_name"]),
            ex_rating=float(row["ex_rating"]),
            last_updated=_format_timestamp(row["last_updated"]),
        )
        for row in rows
    ]


def _format_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat() + "+00:00"
        return value.isoformat()
    return str(value)


def _batched(rows: list[tuple], batch_size: int = BATCH_SIZE):
    for index in range(0, len(rows), batch_size):
        yield rows[index : index + batch_size]


def sync_sqlite_to_supabase(
    sqlite_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    db_url: str | None = None,
) -> dict[str, int]:
    """Replace Supabase leaderboard tables with data from the local SQLite build."""
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    postgres = _connect_postgres(db_url)
    sqlite = connect_sqlite(sqlite_path)
    try:
        player_rows = sqlite.execute(
            """
            SELECT player_id, display_name, player_name, ex_rating, rank, last_updated
            FROM players
            ORDER BY player_id
            """
        ).fetchall()
        score_rows = sqlite.execute(
            """
            SELECT player_id, song, difficulty, score
            FROM scores
            ORDER BY player_id, song, difficulty
            """
        ).fetchall()
        override_rows = sqlite.execute(
            """
            SELECT player_id, ex_rating, reason, updated_at
            FROM rating_overrides
            ORDER BY player_id
            """
        ).fetchall()
        metadata_rows = sqlite.execute(
            "SELECT key, value FROM metadata ORDER BY key"
        ).fetchall()
    finally:
        sqlite.close()

    counts = {
        "players": len(player_rows),
        "scores": len(score_rows),
        "rating_overrides": len(override_rows),
        "metadata": len(metadata_rows),
    }

    with postgres:
        with postgres.cursor() as cur:
            cur.execute("TRUNCATE rating_overrides, scores, players, metadata CASCADE")

            cur.executemany(
                """
                INSERT INTO players (
                    player_id, display_name, player_name, ex_rating, rank, last_updated
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        row["player_id"],
                        row["display_name"],
                        row["player_name"],
                        float(row["ex_rating"]),
                        int(row["rank"]),
                        row["last_updated"],
                    )
                    for row in player_rows
                ],
            )
            print(f"Inserted {counts['players']} players", file=sys.stderr)

            score_payload = [
                (row["player_id"], row["song"], row["difficulty"], int(row["score"]))
                for row in score_rows
            ]
            for batch_index, batch in enumerate(_batched(score_payload), 1):
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO scores (player_id, song, difficulty, score)
                    VALUES (%s, %s, %s, %s)
                    """,
                    batch,
                    page_size=BATCH_SIZE,
                )
                if batch_index % 20 == 0:
                    print(f"Inserted {batch_index * BATCH_SIZE} scores…", file=sys.stderr)
            print(f"Inserted {counts['scores']} scores", file=sys.stderr)

            if override_rows:
                cur.executemany(
                    """
                    INSERT INTO rating_overrides (player_id, ex_rating, reason, updated_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            row["player_id"],
                            float(row["ex_rating"]),
                            row["reason"],
                            row["updated_at"],
                        )
                        for row in override_rows
                    ],
                )

            if metadata_rows:
                cur.executemany(
                    "INSERT INTO metadata (key, value) VALUES (%s, %s)",
                    [(row["key"], row["value"]) for row in metadata_rows],
                )

            cur.execute(
                """
                INSERT INTO metadata (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                ("last_supabase_sync", datetime.now(timezone.utc).isoformat()),
            )

    return counts
