import csv
from io import StringIO
from pathlib import Path

from dataclasses import dataclass

from rating.constants import COMPLETION_BONUS, TOP_N
from rating.formatting import format_rating_display, format_song_display_name
from rating.formulas import compute_grade_bonus, song_star_rating
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

EX_BOARD_HEADERS_WITHOUT_ACCURACY = [
    header for header in EX_BOARD_HEADERS if header != "Accuracy"
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


def _top_n_sum(values: list[float], n: int = TOP_N) -> float:
    return sum(sorted(values, reverse=True)[:n])


def target_chart_rating(level: int, target_accuracy: float) -> float:
    """Rating for a hypothetical score at target accuracy with no misses."""
    bonus = compute_grade_bonus(target_accuracy, 0, True)
    return song_star_rating(target_accuracy, level, bonus)


def perfect_chart_rating(level: int) -> float:
    """Rating for 100% accuracy / EX accuracy with no misses."""
    return target_chart_rating(level, 100.0)


@dataclass(frozen=True)
class PotentialGain:
    chart: ChartRating
    potential_gain: float


def potential_gains_from_perfect(
    ratings: list[ChartRating],
    rating_attr: str,
    top_n: int = TOP_N,
    level_cap: int = 25,
    target_accuracy: float = 100.0,
) -> list[PotentialGain]:
    """Charts that would add profile rating from a hypothetical score on that chart."""
    current_values = [getattr(chart, rating_attr) for chart in ratings]
    current_total = _top_n_sum(current_values, top_n)

    gains: list[PotentialGain] = []
    for index, chart in enumerate(ratings):
        if chart.level > level_cap:
            continue

        target_rating = target_chart_rating(chart.level, target_accuracy)
        if target_rating <= current_values[index]:
            continue

        modified_values = list(current_values)
        modified_values[index] = target_rating
        gain = _top_n_sum(modified_values, top_n) - current_total
        if gain > 0:
            gains.append(PotentialGain(chart=chart, potential_gain=gain))

    gains.sort(key=lambda entry: entry.potential_gain, reverse=True)
    return gains


def competition_ranks_for_values(values: list[float]) -> list[int]:
    """Tied values share a rank; the next rank skips (e.g. 1, 1, 3)."""
    if not values:
        return []
    ranks = [1]
    for index in range(1, len(values)):
        if values[index] == values[index - 1]:
            ranks.append(ranks[-1])
        else:
            ranks.append(index + 1)
    return ranks


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


def player_standard_rating_with_completion(
    ratings: list[ChartRating],
    top_n: int = TOP_N,
) -> float:
    _, standard_total, _, _ = get_rating_boards(ratings, top_n)
    return standard_total + COMPLETION_BONUS


def format_ex_rating_board_csv(
    ratings: list[ChartRating],
    top_n: int = TOP_N,
    *,
    include_accuracy: bool = False,
) -> str:
    ex_total, _, ex_top, _ = get_rating_boards(ratings, top_n)
    buffer = StringIO()
    writer = csv.writer(buffer)
    headers = EX_BOARD_HEADERS if include_accuracy else EX_BOARD_HEADERS_WITHOUT_ACCURACY

    writer.writerow(["Player EX Rating", format_rating_display(ex_total)])
    writer.writerow(["(w/ 2.0 Completion)", format_rating_display(ex_total + COMPLETION_BONUS)])
    writer.writerow(headers)
    for rank, chart in enumerate(ex_top, 1):
        writer.writerow(_ex_row(rank, chart, include_accuracy=include_accuracy))

    return buffer.getvalue()


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


def _ex_row(rank: int, chart: ChartRating, *, include_accuracy: bool = True) -> list:
    row = [
        rank,
        format_song_display_name(chart.song),
        chart.difficulty,
        chart.level,
    ]
    if include_accuracy:
        row.append(f"{chart.standard_accuracy:.2f}")
    row.extend(
        [
            chart.score,
            chart.max_score,
            f"{chart.ex_accuracy:.2f}",
            chart.ex_grade,
            format_rating_display(chart.ex_rating),
        ]
    )
    return row


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
