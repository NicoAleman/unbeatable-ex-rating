from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg2.errors

from rating.baseline_leaderboard import load_baseline_leaderboard_csv
from rating.constants import EX_RATING_BASELINE_PATH
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import _connect_postgres, _format_timestamp


@dataclass(frozen=True)
class LeaderboardActivityEntry:
    player_id: str
    display_name: str
    prev_rating: float
    new_rating: float
    prev_rank: int
    new_rank: int
    created_at: datetime


def record_leaderboard_activity(
    *,
    player_id: str,
    prev_rating: float,
    new_rating: float,
    prev_rank: int,
    new_rank: int,
    created_at: str | None = None,
    db_url: str | None = None,
) -> None:
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    conn = _connect_postgres(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO leaderboard_activity (
                        player_id, prev_rating, new_rating, prev_rank, new_rank, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        player_id,
                        float(prev_rating),
                        float(new_rating),
                        int(prev_rank),
                        int(new_rank),
                        timestamp,
                    ),
                )
    finally:
        conn.close()


def load_leaderboard_activity(
    *,
    limit: int = 20,
    db_url: str | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> list[LeaderboardActivityEntry]:
    if not supabase_configured() and not db_url:
        return []

    display_names = {
        entry.player_id: entry.display_name
        for entry in load_baseline_leaderboard_csv(baseline_path)
    }

    conn = _connect_postgres(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT player_id, prev_rating, new_rating, prev_rank, new_rank, created_at
                FROM leaderboard_activity
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return []
    finally:
        conn.close()

    entries: list[LeaderboardActivityEntry] = []
    for row in rows:
        created_raw = row[5]
        if isinstance(created_raw, datetime):
            created_at = created_raw if created_raw.tzinfo else created_raw.replace(tzinfo=timezone.utc)
        else:
            created_at = datetime.fromisoformat(_format_timestamp(created_raw).replace("Z", "+00:00"))

        player_id = str(row[0])
        entries.append(
            LeaderboardActivityEntry(
                player_id=player_id,
                display_name=display_names.get(player_id, player_id),
                prev_rating=float(row[1]),
                new_rating=float(row[2]),
                prev_rank=int(row[3]),
                new_rank=int(row[4]),
                created_at=created_at,
            )
        )
    return entries
