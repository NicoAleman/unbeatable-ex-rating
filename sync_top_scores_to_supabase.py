#!/usr/bin/env python3
"""Upload top-rated players' chart scores to Supabase (seed import)."""

import argparse
import sys

from rating.constants import EX_RATING_LEADERBOARD_DB_PATH, TOP_SCORES_SYNC_PLAYER_COUNT
from rating.supabase_config import get_supabase_db_url
from rating.supabase_leaderboard import sync_top_scores_to_supabase


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=str,
        default=str(EX_RATING_LEADERBOARD_DB_PATH),
        help="Path to the local SQLite database",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=TOP_SCORES_SYNC_PLAYER_COUNT,
        help="Number of top-rated players whose scores to upload",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Override Supabase Postgres URL",
    )
    args = parser.parse_args()

    db_url = args.db_url or get_supabase_db_url()
    if not db_url:
        print(
            "Error: Supabase is not configured. Add supabase.db_url to .streamlit/secrets.toml.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    from pathlib import Path

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        print(f"Error: SQLite database not found: {sqlite_path}", file=sys.stderr)
        raise SystemExit(1)

    counts = sync_top_scores_to_supabase(
        sqlite_path,
        db_url,
        top_n=args.top_n,
    )
    print(
        f"Sync complete: {counts['players']} players, {counts['scores']} seed scores uploaded."
    )


if __name__ == "__main__":
    main()
