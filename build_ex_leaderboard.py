#!/usr/bin/env python3
"""Build the local SQLite database and export the baseline EX rating CSV."""

from rating.constants import EX_RATING_BASELINE_PATH, EX_RATING_LEADERBOARD_DB_PATH, LEADERBOARDS_JUNE27_DIR
from rating.ex_leaderboard_db import build_ex_leaderboard_database


def main() -> None:
    player_count = build_ex_leaderboard_database()
    print(f"Wrote {player_count} players to {EX_RATING_LEADERBOARD_DB_PATH}")
    print(f"Exported baseline CSV to {EX_RATING_BASELINE_PATH}")
    print(f"Source directory: {LEADERBOARDS_JUNE27_DIR}")
    print("Upload top player scores: python sync_top_scores_to_supabase.py")


if __name__ == "__main__":
    main()
