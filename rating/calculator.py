import sys
from pathlib import Path

from rating.data import load_critical_max_scores, load_highscores
from rating.entries import (
    chart_key,
    critical_count,
    is_classic_entry,
    miss_count,
    split_chart_key,
)
from rating.formulas import (
    compute_ex_grade,
    compute_grade_bonus,
    compute_standard_grade,
    song_star_rating,
)
from rating.level_overrides import resolve_chart_level
from rating.models import ChartRating


def ex_accuracy_percent(score: int, max_score: int) -> float:
    if max_score <= 0:
        return 0.0
    return (score / max_score) * 100


def rate_chart(entry: dict, critical_max_score: int) -> ChartRating:
    key = chart_key(entry["song"])
    song, difficulty = split_chart_key(key)
    level = resolve_chart_level(key, entry.get("level", 0))
    score = entry.get("score", 0)
    misses = miss_count(entry)
    criticals = critical_count(entry)
    cleared = entry.get("cleared", False)
    max_combo = entry.get("maxCombo", 0)

    standard_accuracy = entry.get("accuracy", 0) * 100
    ex_accuracy = ex_accuracy_percent(score, critical_max_score)

    standard_grade = compute_standard_grade(standard_accuracy, misses, cleared)
    ex_grade = compute_ex_grade(ex_accuracy, misses, cleared, criticals, max_combo)

    standard_bonus = compute_grade_bonus(standard_accuracy, misses, cleared)
    ex_bonus = compute_grade_bonus(ex_accuracy, misses, cleared)

    return ChartRating(
        song=song,
        difficulty=difficulty,
        level=level,
        score=score,
        max_score=critical_max_score,
        standard_accuracy=standard_accuracy,
        standard_grade=standard_grade,
        standard_rating=song_star_rating(standard_accuracy, level, standard_bonus),
        ex_accuracy=ex_accuracy,
        ex_grade=ex_grade,
        ex_rating=song_star_rating(ex_accuracy, level, ex_bonus),
    )


def build_ratings(
    highscores: Path | dict,
    max_scores_path: Path,
) -> list[ChartRating]:
    max_scores = load_critical_max_scores(max_scores_path)
    data = load_highscores(highscores) if isinstance(highscores, Path) else highscores

    ratings: list[ChartRating] = []
    for entry in data.get("highScores", []):
        if not is_classic_entry(entry):
            continue

        key = chart_key(entry["song"])
        critical_max = max_scores.get(key)
        if critical_max is None:
            print(f"Warning: no max score for {key}", file=sys.stderr)
            continue

        ratings.append(rate_chart(entry, critical_max))

    return ratings
