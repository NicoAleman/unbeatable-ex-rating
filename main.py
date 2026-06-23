#!/usr/bin/env python3
"""Generate EX and standard rating boards from an arcade-highscores.json file."""

import sys
from pathlib import Path

from rating import DEFAULT_MAX_SCORES_PATH, build_ratings, write_rating_board


def main() -> None:
    root = Path(__file__).parent
    highscores_path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "arcade-highscores.json"
    max_scores_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_SCORES_PATH
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else root / "ex_rating_board.csv"

    if not highscores_path.exists():
        print(f"Error: file not found: {highscores_path}", file=sys.stderr)
        sys.exit(1)
    if not max_scores_path.exists():
        print(f"Error: file not found: {max_scores_path}", file=sys.stderr)
        sys.exit(1)

    ratings = build_ratings(highscores_path, max_scores_path)
    ex_total, standard_total = write_rating_board(ratings, output_path)

    print(f"Player EX Rating: {ex_total:.3f}")
    print(f"Player Rating: {standard_total:.3f}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
