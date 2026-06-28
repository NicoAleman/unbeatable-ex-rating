#!/usr/bin/env python3
"""Generate the full EX rating leaderboard CSV from imported player scores."""

from rating.chart_levels import write_chart_rating_levels, DEFAULT_LEVEL_SOURCES
from rating.constants import FULL_EX_RATING_LEADERBOARD_PATH, LEADERBOARDS_JUNE27_DIR
from rating.imported_players import write_full_ex_leaderboard_csv


def main() -> None:
    levels = write_chart_rating_levels(DEFAULT_LEVEL_SOURCES)
    print(f"Loaded {len(levels)} chart rating levels")
    rankings = write_full_ex_leaderboard_csv()
    print(f"Wrote {len(rankings)} players to {FULL_EX_RATING_LEADERBOARD_PATH}")
    print(f"Source directory: {LEADERBOARDS_JUNE27_DIR}")


if __name__ == "__main__":
    main()
