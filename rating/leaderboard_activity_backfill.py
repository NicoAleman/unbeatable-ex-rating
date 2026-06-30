"""Build leaderboard activity entries from baseline ratings and timed overrides."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.extras

from rating.baseline_leaderboard import (
    BaselineLeaderboardEntry,
    UpdatedRating,
    load_baseline_leaderboard_csv,
)
from rating.constants import EX_RATING_BASELINE_PATH, EX_RATING_LEADERBOARD_DB_PATH, RATING_OVERRIDES_PATH
from rating.leaderboard_activity import LeaderboardActivityEntry
from rating.public_leaderboard import merge_baseline_with_updated_ratings, rank_leaderboard_entries
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import _connect_postgres, _format_timestamp, load_updated_ratings_from_supabase


@dataclass(frozen=True)
class TimedRatingOverride:
    player_id: str
    ex_rating: float
    updated_at: datetime


def parse_override_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        text = _format_timestamp(value).replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def load_timed_rating_overrides_from_supabase(
    db_url: str | None = None,
) -> list[TimedRatingOverride]:
    updated = load_updated_ratings_from_supabase(db_url)
    return [
        TimedRatingOverride(
            player_id=player_id,
            ex_rating=rating.ex_rating,
            updated_at=parse_override_timestamp(rating.last_updated),
        )
        for player_id, rating in updated.items()
    ]


def load_timed_rating_overrides_from_json(
    overrides_path: Path = RATING_OVERRIDES_PATH,
) -> list[TimedRatingOverride]:
    if not overrides_path.exists():
        return []

    raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    overrides: list[TimedRatingOverride] = []
    for player_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        ex_rating = payload.get("ex_rating")
        updated_raw = payload.get("updated_at") or payload.get("last_updated")
        if ex_rating is None or not updated_raw:
            continue
        overrides.append(
            TimedRatingOverride(
                player_id=str(player_id).strip(),
                ex_rating=float(ex_rating),
                updated_at=parse_override_timestamp(updated_raw),
            )
        )
    return overrides


def load_timed_rating_overrides_from_sqlite(
    sqlite_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
) -> list[TimedRatingOverride]:
    if not sqlite_path.exists():
        return []

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT player_id, ex_rating, updated_at
            FROM rating_overrides
            ORDER BY updated_at, player_id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    return [
        TimedRatingOverride(
            player_id=str(row["player_id"]),
            ex_rating=float(row["ex_rating"]),
            updated_at=parse_override_timestamp(row["updated_at"]),
        )
        for row in rows
    ]


def load_timed_rating_overrides(
    *,
    source: str,
    overrides_path: Path = RATING_OVERRIDES_PATH,
    sqlite_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    db_url: str | None = None,
) -> list[TimedRatingOverride]:
    if source == "supabase":
        return load_timed_rating_overrides_from_supabase(db_url)
    if source == "json":
        return load_timed_rating_overrides_from_json(overrides_path)
    if source == "sqlite":
        return load_timed_rating_overrides_from_sqlite(sqlite_path)
    raise ValueError(f"Unknown override source: {source}")


def _player_rank(
    baseline: list[BaselineLeaderboardEntry],
    active_overrides: dict[str, UpdatedRating],
    player_id: str,
) -> int:
    ranked = rank_leaderboard_entries(
        merge_baseline_with_updated_ratings(baseline, active_overrides)
    )
    for entry in ranked:
        if entry.player_id == player_id:
            return entry.rank
    raise KeyError(f"Player not found on ranked leaderboard: {player_id}")


def build_leaderboard_activity_from_overrides(
    *,
    baseline: list[BaselineLeaderboardEntry],
    overrides: list[TimedRatingOverride],
) -> list[LeaderboardActivityEntry]:
    """Replay overrides chronologically and compute rank changes at each step."""
    if not baseline or not overrides:
        return []

    baseline_by_id = {entry.player_id: entry for entry in baseline}
    sorted_overrides = sorted(overrides, key=lambda item: (item.updated_at, item.player_id))

    active_overrides: dict[str, UpdatedRating] = {}
    entries: list[LeaderboardActivityEntry] = []

    for override in sorted_overrides:
        baseline_entry = baseline_by_id.get(override.player_id)
        if baseline_entry is None:
            print(
                f"Warning: skipping override for unknown player {override.player_id}",
                file=sys.stderr,
            )
            continue

        prev_rating = (
            active_overrides[override.player_id].ex_rating
            if override.player_id in active_overrides
            else baseline_entry.ex_rating
        )
        prev_rank = _player_rank(baseline, active_overrides, override.player_id)

        timestamp_text = override.updated_at.isoformat()
        active_overrides[override.player_id] = UpdatedRating(
            ex_rating=override.ex_rating,
            last_updated=timestamp_text,
        )

        if prev_rating == override.ex_rating:
            continue

        new_rank = _player_rank(baseline, active_overrides, override.player_id)
        entries.append(
            LeaderboardActivityEntry(
                player_id=override.player_id,
                display_name=baseline_entry.display_name,
                prev_rating=prev_rating,
                new_rating=override.ex_rating,
                prev_rank=prev_rank,
                new_rank=new_rank,
                created_at=override.updated_at,
            )
        )

    return entries


def insert_leaderboard_activity_entries(
    entries: list[LeaderboardActivityEntry],
    *,
    db_url: str | None = None,
    clear_existing: bool = False,
) -> int:
    if not entries:
        return 0
    if not supabase_configured() and not db_url:
        raise RuntimeError(
            "Supabase is not configured. Set supabase.db_url in .streamlit/secrets.toml."
        )

    conn = _connect_postgres(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                if clear_existing:
                    cur.execute("DELETE FROM leaderboard_activity")
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO leaderboard_activity (
                        player_id, prev_rating, new_rating, prev_rank, new_rank, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            entry.player_id,
                            float(entry.prev_rating),
                            float(entry.new_rating),
                            int(entry.prev_rank),
                            int(entry.new_rank),
                            entry.created_at,
                        )
                        for entry in entries
                    ],
                    page_size=200,
                )
    finally:
        conn.close()

    return len(entries)


def backfill_leaderboard_activity(
    *,
    source: str = "supabase",
    baseline_path: Path = EX_RATING_BASELINE_PATH,
    overrides_path: Path = RATING_OVERRIDES_PATH,
    sqlite_path: Path = EX_RATING_LEADERBOARD_DB_PATH,
    db_url: str | None = None,
    clear_existing: bool = False,
    dry_run: bool = False,
) -> list[LeaderboardActivityEntry]:
    baseline = load_baseline_leaderboard_csv(baseline_path)
    if not baseline:
        raise FileNotFoundError(f"Baseline leaderboard not found or empty: {baseline_path}")

    overrides = load_timed_rating_overrides(
        source=source,
        overrides_path=overrides_path,
        sqlite_path=sqlite_path,
        db_url=db_url,
    )
    if not overrides:
        raise RuntimeError(f"No timed rating overrides found for source={source!r}")

    entries = build_leaderboard_activity_from_overrides(
        baseline=baseline,
        overrides=overrides,
    )
    if dry_run:
        return entries

    insert_leaderboard_activity_entries(
        entries,
        db_url=db_url,
        clear_existing=clear_existing,
    )
    return entries
