import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

from rating.constants import (
    EX_RATING_LEADERBOARD_DB_PATH,
    SCORE_SOURCE_SEED,
    SCORE_SOURCE_SUBMISSION,
    TOP_SCORES_SYNC_PLAYER_COUNT,
)
from rating.ex_leaderboard_db import _connect as connect_sqlite
from rating.baseline_leaderboard import UpdatedRating
from rating.supabase_config import get_supabase_db_url, supabase_configured

BATCH_SIZE = 2000


def _connect_postgres(db_url: str | None = None):
    url = db_url or get_supabase_db_url()
    if not url:
        raise RuntimeError(
            "Supabase is not configured. Set supabase.db_url in .streamlit/secrets.toml "
            "or SUPABASE_DB_URL in the environment."
        )
    return psycopg2.connect(url)


def _format_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat() + "+00:00"
        return value.isoformat()
    return str(value)


def _batched(rows: list[tuple], batch_size: int = BATCH_SIZE):
    for index in range(0, len(rows), batch_size):
        yield rows[index : index + batch_size]


def load_updated_ratings_from_supabase(
    db_url: str | None = None,
) -> dict[str, UpdatedRating]:
    if not supabase_configured() and not db_url:
        return {}

    conn = _connect_postgres(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT player_id, ex_rating, last_updated
                FROM updated_ratings
                ORDER BY player_id
                """
            )
            rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return {}
    finally:
        conn.close()

    return {
        str(row["player_id"]): UpdatedRating(
            ex_rating=float(row["ex_rating"]),
            last_updated=_format_timestamp(row["last_updated"]),
        )
        for row in rows
    }


def load_submission_scores_from_supabase(
    db_url: str | None = None,
) -> list[dict[str, object]]:
    """Scores added via site features — exclude the initial seed import."""
    if not supabase_configured() and not db_url:
        return []

    conn = _connect_postgres(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT player_id, song, difficulty, score, source
                FROM scores
                WHERE source = %s
                ORDER BY player_id, song, difficulty
                """,
                (SCORE_SOURCE_SUBMISSION,),
            )
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.errors.UndefinedTable:
        return []
    finally:
        conn.close()


def sync_top_scores_to_supabase(
    sqlite_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    db_url: str | None = None,
    *,
    top_n: int = TOP_SCORES_SYNC_PLAYER_COUNT,
    source: str = SCORE_SOURCE_SEED,
) -> dict[str, int]:
    """Upload chart scores for the top N rated players (seed import)."""
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    sqlite = connect_sqlite(sqlite_path)
    try:
        top_players = sqlite.execute(
            """
            SELECT player_id
            FROM players
            ORDER BY ex_rating DESC, display_name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()
        top_player_ids = [row["player_id"] for row in top_players]
        if not top_player_ids:
            return {"players": 0, "scores": 0}

        placeholders = ",".join("?" for _ in top_player_ids)
        score_rows = sqlite.execute(
            f"""
            SELECT player_id, song, difficulty, score
            FROM scores
            WHERE player_id IN ({placeholders})
            ORDER BY player_id, song, difficulty
            """,
            top_player_ids,
        ).fetchall()
    finally:
        sqlite.close()

    score_payload = [
        (row["player_id"], row["song"], row["difficulty"], int(row["score"]), source)
        for row in score_rows
    ]

    postgres = _connect_postgres(db_url)
    with postgres:
        with postgres.cursor() as cur:
            cur.execute("DELETE FROM scores WHERE source = %s", (source,))
            print(f"Cleared existing {source} scores from Supabase", file=sys.stderr)

            for batch_index, batch in enumerate(_batched(score_payload), 1):
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO scores (player_id, song, difficulty, score, source)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    batch,
                    page_size=BATCH_SIZE,
                )
                print(
                    f"Inserted batch {batch_index} ({min(batch_index * BATCH_SIZE, len(score_payload))}/{len(score_payload)} scores)…",
                    file=sys.stderr,
                )
        postgres.commit()

    return {"players": len(top_player_ids), "scores": len(score_payload)}
