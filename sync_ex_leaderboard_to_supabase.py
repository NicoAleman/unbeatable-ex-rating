#!/usr/bin/env python3
"""Upload the local EX rating SQLite database to Supabase."""

import argparse
import sys

from pathlib import Path

from rating.constants import EX_RATING_LEADERBOARD_DB_PATH
from rating.supabase_config import get_supabase_db_url
from rating.supabase_leaderboard import supabase_has_data, sync_sqlite_to_supabase


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=EX_RATING_LEADERBOARD_DB_PATH,
        help="Path to the local SQLite database",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Override Supabase Postgres URL (otherwise uses secrets/env)",
    )
    args = parser.parse_args()

    db_url = args.db_url or get_supabase_db_url()
    if not db_url:
        print(
            "Error: Supabase is not configured.\n"
            "Add supabase.db_url to .streamlit/secrets.toml or set SUPABASE_DB_URL.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    path = args.sqlite_path
    if not path.exists():
        print(f"Error: SQLite database not found: {path}", file=sys.stderr)
        raise SystemExit(1)

    if supabase_has_data(db_url):
        print("Supabase already has player data. Replacing all leaderboard tables…", file=sys.stderr)
    else:
        print("Uploading leaderboard data to Supabase…", file=sys.stderr)

    counts = sync_sqlite_to_supabase(path, db_url=db_url)
    print(
        "Sync complete: "
        f"{counts['players']} players, "
        f"{counts['scores']} scores, "
        f"{counts['rating_overrides']} overrides."
    )


if __name__ == "__main__":
    main()
