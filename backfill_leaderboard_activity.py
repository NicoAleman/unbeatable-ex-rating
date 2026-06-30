#!/usr/bin/env python3
"""Backfill leaderboard_activity from baseline ratings and timed rating overrides."""

import argparse
import sys
from pathlib import Path

from rating.constants import EX_RATING_BASELINE_PATH, EX_RATING_LEADERBOARD_DB_PATH, RATING_OVERRIDES_PATH
from rating.leaderboard_activity_backfill import backfill_leaderboard_activity
from rating.supabase_config import get_supabase_db_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("supabase", "json", "sqlite"),
        default="supabase",
        help="Where timed rating overrides are loaded from (default: supabase updated_ratings)",
    )
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=EX_RATING_BASELINE_PATH,
        help="Original full EX rating baseline CSV",
    )
    parser.add_argument(
        "--overrides-path",
        type=Path,
        default=RATING_OVERRIDES_PATH,
        help="JSON overrides file when --source=json",
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=EX_RATING_LEADERBOARD_DB_PATH,
        help="SQLite database when --source=sqlite",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Override Supabase Postgres URL",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete existing leaderboard_activity rows before inserting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print computed entries without writing to Supabase",
    )
    args = parser.parse_args()

    db_url = args.db_url or get_supabase_db_url()
    if not args.dry_run and not db_url:
        print(
            "Error: Supabase is not configured. Add supabase.db_url to .streamlit/secrets.toml.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        entries = backfill_leaderboard_activity(
            source=args.source,
            baseline_path=args.baseline_path,
            overrides_path=args.overrides_path,
            sqlite_path=args.sqlite_path,
            db_url=db_url,
            clear_existing=args.clear,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    for entry in entries:
        delta = entry.new_rating - entry.prev_rating
        rank_delta = entry.prev_rank - entry.new_rank
        rank_suffix = ""
        if rank_delta > 0:
            rank_suffix = f" (up {rank_delta})"
        elif rank_delta < 0:
            rank_suffix = f" (down {abs(rank_delta)})"
        print(
            f"{entry.created_at.isoformat(timespec='seconds')}  "
            f"{entry.display_name}  "
            f"{entry.prev_rating:.3f} -> {entry.new_rating:.3f} (+{delta:.3f})  "
            f"rank {entry.prev_rank} -> {entry.new_rank}{rank_suffix}"
        )

    if args.dry_run:
        print(f"\nDry run: {len(entries)} activity entries computed, nothing written.")
    else:
        print(f"\nInserted {len(entries)} activity entries into leaderboard_activity.")


if __name__ == "__main__":
    main()
