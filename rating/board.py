import csv
from io import StringIO
from pathlib import Path

from rating.constants import COMPLETION_BONUS, TOP_N
from rating.formatting import format_rating_display, format_song_display_name
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


def get_rating_boards(
    ratings: list[ChartRating],
    top_n: int = TOP_N,
) -> tuple[float, float, list[ChartRating], list[ChartRating]]:
    ex_top = _top_by(ratings, "ex_rating", top_n)
    standard_top = _top_by(ratings, "standard_rating", top_n)
    ex_total = sum(chart.ex_rating for chart in ex_top)
    standard_total = sum(chart.standard_rating for chart in standard_top)
    return ex_total, standard_total, ex_top, standard_top


def player_ex_rating_with_completion(
    ratings: list[ChartRating],
    top_n: int = TOP_N,
) -> float:
    ex_total, _, _, _ = get_rating_boards(ratings, top_n)
    return ex_total + COMPLETION_BONUS


def format_rating_board_csv(
    ratings: list[ChartRating],
    top_n: int = TOP_N,
) -> str:
    ex_total, standard_total, ex_top, standard_top = get_rating_boards(ratings, top_n)
    buffer = StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["Player EX Rating", format_rating_display(ex_total)])
    writer.writerow(["(w/ 2.0 Completion)", format_rating_display(ex_total + COMPLETION_BONUS)])
    writer.writerow(EX_BOARD_HEADERS)
    for rank, chart in enumerate(ex_top, 1):
        writer.writerow(_ex_row(rank, chart))

    writer.writerow([])
    writer.writerow([])

    writer.writerow(["Player Rating", format_rating_display(standard_total)])
    writer.writerow(["(w/ 2.0 Completion)", format_rating_display(standard_total + COMPLETION_BONUS)])
    writer.writerow(STANDARD_BOARD_HEADERS)
    for rank, chart in enumerate(standard_top, 1):
        writer.writerow(_standard_row(rank, chart))

    return buffer.getvalue()


def write_rating_board(
    ratings: list[ChartRating],
    output_path: Path,
    top_n: int = TOP_N,
) -> tuple[float, float]:
    ex_total, standard_total, _, _ = get_rating_boards(ratings, top_n)
    output_path.write_text(format_rating_board_csv(ratings, top_n), encoding="utf-8")
    return ex_total, standard_total


def _ex_row(rank: int, chart: ChartRating) -> list:
    return [
        rank,
        format_song_display_name(chart.song),
        chart.difficulty,
        chart.level,
        f"{chart.standard_accuracy:.2f}",
        chart.score,
        chart.max_score,
        f"{chart.ex_accuracy:.2f}",
        chart.ex_grade,
        format_rating_display(chart.ex_rating),
    ]


def _standard_row(rank: int, chart: ChartRating) -> list:
    return [
        rank,
        format_song_display_name(chart.song),
        chart.difficulty,
        chart.level,
        f"{chart.standard_accuracy:.2f}",
        chart.standard_grade,
        format_rating_display(chart.standard_rating),
    ]
