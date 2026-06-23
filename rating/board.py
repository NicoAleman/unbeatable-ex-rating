import csv
from pathlib import Path

from rating.constants import COMPLETION_BONUS, TOP_N
from rating.models import ChartRating

EX_BOARD_HEADERS = [
    "Rank",
    "Chart",
    "Difficulty",
    "Level",
    "Accuracy",
    "Score",
    "Critical Max Score",
    "EX Accuracy",
    "EX Grade",
    "EX Rating",
]

STANDARD_BOARD_HEADERS = [
    "Rank",
    "Chart",
    "Difficulty",
    "Level",
    "Accuracy",
    "Grade",
    "Rating",
]


def _top_by(ratings: list[ChartRating], key: str, n: int = TOP_N) -> list[ChartRating]:
    return sorted(ratings, key=lambda chart: getattr(chart, key), reverse=True)[:n]


def write_rating_board(
    ratings: list[ChartRating],
    output_path: Path,
    top_n: int = TOP_N,
) -> tuple[float, float]:
    ex_top = _top_by(ratings, "ex_rating", top_n)
    standard_top = _top_by(ratings, "standard_rating", top_n)
    ex_total = sum(chart.ex_rating for chart in ex_top)
    standard_total = sum(chart.standard_rating for chart in standard_top)

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)

        writer.writerow(["Player EX Rating", f"{ex_total:.3f}"])
        writer.writerow(EX_BOARD_HEADERS)
        for rank, chart in enumerate(ex_top, 1):
            writer.writerow(_ex_row(rank, chart))

        writer.writerow([])
        writer.writerow([])

        writer.writerow(["Player Rating", f"{standard_total:.3f}"])
        writer.writerow(["(w/ 2.0 Completion)", f"{standard_total + COMPLETION_BONUS:.3f}"])
        writer.writerow(STANDARD_BOARD_HEADERS)
        for rank, chart in enumerate(standard_top, 1):
            writer.writerow(_standard_row(rank, chart))

    return ex_total, standard_total


def _ex_row(rank: int, chart: ChartRating) -> list:
    return [
        rank,
        chart.song,
        chart.difficulty,
        chart.level,
        f"{chart.standard_accuracy:.2f}",
        chart.score,
        chart.max_score,
        f"{chart.ex_accuracy:.2f}",
        chart.ex_grade,
        f"{chart.ex_rating:.3f}",
    ]


def _standard_row(rank: int, chart: ChartRating) -> list:
    return [
        rank,
        chart.song,
        chart.difficulty,
        chart.level,
        f"{chart.standard_accuracy:.2f}",
        chart.standard_grade,
        f"{chart.standard_rating:.3f}",
    ]
