#!/usr/bin/env python3
"""Build the EX rating leaderboard SQLite database from imported player scores."""

from rating.constants import EX_RATING_LEADERBOARD_DB_PATH, LEADERBOARDS_JUNE27_DIR
from rating.ex_leaderboard_db import build_ex_leaderboard_database


def main() -> None:
    player_count = build_ex_leaderboard_database()
    print(f"Wrote {player_count} players to {EX_RATING_LEADERBOARD_DB_PATH}")
    print(f"Source directory: {LEADERBOARDS_JUNE27_DIR}")


if __name__ == "__main__":
    main()
