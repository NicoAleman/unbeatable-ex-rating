#!/usr/bin/env python3
"""Export the baseline EX rating CSV from the local SQLite build."""

from rating.baseline_leaderboard import export_baseline_leaderboard_from_sqlite
from rating.constants import EX_RATING_BASELINE_PATH, EX_RATING_LEADERBOARD_DB_PATH


def main() -> None:
    count = export_baseline_leaderboard_from_sqlite(
        EX_RATING_LEADERBOARD_DB_PATH,
        EX_RATING_BASELINE_PATH,
    )
    print(f"Wrote {count} players to {EX_RATING_BASELINE_PATH}")


if __name__ == "__main__":
    main()
