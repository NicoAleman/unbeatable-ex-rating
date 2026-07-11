from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg2.errors

from rating.baseline_leaderboard import load_baseline_leaderboard_csv
from rating.constants import EX_RATING_BASELINE_PATH, PLAYER_SCORE_SOURCES, SCORE_SOURCE_IN_GAME, SCORE_SOURCE_SUBMISSION
from rating.formatting import rating_increased, ratings_are_equal
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import _connect_postgres, _format_timestamp

ACTIVITY_HOURLY_COMBINE_WINDOW = timedelta(hours=2)


@dataclass(frozen=True)
class LeaderboardActivityEntry:
    player_id: str
    display_name: str
    prev_rating: float
    new_rating: float
    prev_rank: int
    new_rank: int
    created_at: datetime
    submission_source: str | None = None


def activity_entry_has_rating_change(entry: LeaderboardActivityEntry) -> bool:
    return not ratings_are_equal(entry.prev_rating, entry.new_rating)


def format_submission_source_label(submission_source: str | None) -> str | None:
    if submission_source == SCORE_SOURCE_IN_GAME:
        return "In-game"
    if submission_source == SCORE_SOURCE_SUBMISSION:
        return "Submission"
    return None


def record_leaderboard_activity(
    *,
    player_id: str,
    prev_rating: float,
    new_rating: float,
    prev_rank: int,
    new_rank: int,
    created_at: str | None = None,
    submission_source: str | None = None,
    db_url: str | None = None,
) -> None:
    if not rating_increased(prev_rating, new_rating):
        return

    if submission_source is not None and submission_source not in PLAYER_SCORE_SOURCES:
        raise ValueError(f"Invalid submission_source: {submission_source!r}")

    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    conn = _connect_postgres(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO leaderboard_activity (
                        player_id, prev_rating, new_rating, prev_rank, new_rank,
                        created_at, submission_source
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        player_id,
                        float(prev_rating),
                        float(new_rating),
                        int(prev_rank),
                        int(new_rank),
                        timestamp,
                        submission_source,
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
            try:
                cur.execute(
                    """
                    SELECT player_id, prev_rating, new_rating, prev_rank, new_rank,
                           created_at, submission_source
                    FROM leaderboard_activity
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            except psycopg2.errors.UndefinedColumn:
                conn.rollback()
                cur.execute(
                    """
                    SELECT player_id, prev_rating, new_rating, prev_rank, new_rank, created_at
                    FROM leaderboard_activity
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = [(*row, None) for row in cur.fetchall()]
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
        submission_source = str(row[6]) if row[6] is not None else None
        entries.append(
            LeaderboardActivityEntry(
                player_id=player_id,
                display_name=display_names.get(player_id, player_id),
                prev_rating=float(row[1]),
                new_rating=float(row[2]),
                prev_rank=int(row[3]),
                new_rank=int(row[4]),
                created_at=created_at,
                submission_source=submission_source,
            )
        )
    return entries


def filter_unchanged_activity_entries(
    entries: list[LeaderboardActivityEntry],
) -> list[LeaderboardActivityEntry]:
    return [entry for entry in entries if activity_entry_has_rating_change(entry)]


def _oldest_meaningful_activity_entry(
    entries: list[LeaderboardActivityEntry],
    *,
    start: int,
    end: int,
) -> LeaderboardActivityEntry | None:
    for index in range(end, start - 1, -1):
        entry = entries[index]
        if activity_entry_has_rating_change(entry):
            return entry
    return None


def _combine_activity_streak(
    entries: list[LeaderboardActivityEntry],
    *,
    start: int,
    end: int,
) -> LeaderboardActivityEntry | None:
    newest = entries[start]
    oldest = entries[end]
    oldest_meaningful = _oldest_meaningful_activity_entry(entries, start=start, end=end)

    if start == end:
        combined_entry = newest
    else:
        source = oldest_meaningful or oldest
        combined_entry = LeaderboardActivityEntry(
            player_id=newest.player_id,
            display_name=newest.display_name,
            prev_rating=source.prev_rating,
            new_rating=newest.new_rating,
            prev_rank=source.prev_rank,
            new_rank=newest.new_rank,
            created_at=newest.created_at,
            submission_source=newest.submission_source,
        )

    if activity_entry_has_rating_change(combined_entry):
        return combined_entry
    return None


def combine_hourly_activity_entries(
    entries: list[LeaderboardActivityEntry],
) -> list[LeaderboardActivityEntry]:
    """Merge same-player rows within two hours, scanning oldest-first and keeping the later timestamp."""
    meaningful_entries = filter_unchanged_activity_entries(entries)
    if not meaningful_entries:
        return []

    oldest_first = sorted(meaningful_entries, key=lambda entry: entry.created_at)
    by_player: dict[str, list[LeaderboardActivityEntry]] = {}
    for entry in oldest_first:
        by_player.setdefault(entry.player_id, []).append(entry)

    merged: list[LeaderboardActivityEntry] = []
    for player_entries in by_player.values():
        index = 0
        while index < len(player_entries):
            streak_end = index
            group_latest = player_entries[index].created_at

            while streak_end + 1 < len(player_entries):
                next_entry = player_entries[streak_end + 1]
                if next_entry.created_at - group_latest > ACTIVITY_HOURLY_COMBINE_WINDOW:
                    break
                streak_end += 1
                group_latest = next_entry.created_at

            streak = player_entries[index : streak_end + 1]
            combined_entry = _combine_activity_streak(
                list(reversed(streak)),
                start=0,
                end=len(streak) - 1,
            )
            if combined_entry is not None:
                merged.append(combined_entry)

            index = streak_end + 1

    merged.sort(key=lambda entry: entry.created_at, reverse=True)
    return merged


def combine_consecutive_activity_entries(
    entries: list[LeaderboardActivityEntry],
) -> list[LeaderboardActivityEntry]:
    """Merge consecutive same-player rows (newest-first) into one displayed update."""
    meaningful_entries = filter_unchanged_activity_entries(entries)
    if not meaningful_entries:
        return []

    combined: list[LeaderboardActivityEntry] = []
    index = 0
    while index < len(meaningful_entries):
        streak_end = index
        player_id = meaningful_entries[index].player_id

        while (
            streak_end + 1 < len(meaningful_entries)
            and meaningful_entries[streak_end + 1].player_id == player_id
        ):
            streak_end += 1

        combined_entry = _combine_activity_streak(meaningful_entries, start=index, end=streak_end)
        if combined_entry is not None:
            combined.append(combined_entry)

        index = streak_end + 1

    return combined


def load_leaderboard_activity_feed(
    *,
    limit: int = 20,
    db_url: str | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> list[LeaderboardActivityEntry]:
    """Load, merge, and filter activity rows, skipping unchanged rating updates."""
    if limit <= 0:
        return []

    fetch_limit = max(limit * 3, limit)
    max_fetch = max(limit * 20, fetch_limit)

    while True:
        raw = load_leaderboard_activity(
            limit=fetch_limit,
            db_url=db_url,
            baseline_path=baseline_path,
        )
        combined = combine_consecutive_activity_entries(combine_hourly_activity_entries(raw))
        if len(combined) >= limit or len(raw) < fetch_limit or fetch_limit >= max_fetch:
            return combined[:limit]
        fetch_limit = min(fetch_limit * 2, max_fetch)
