import sys
from pathlib import Path

from rating.chart_levels import load_chart_rating_levels, resolve_chart_rating_level
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
    compute_ex_grade_bonus,
    compute_grade_bonus,
    compute_standard_grade,
    song_star_rating,
)
from rating.level_overrides import resolve_chart_level
from rating.models import ChartRating


def ex_accuracy_percent(score: int, max_score: int) -> float:
    if max_score <= 0:
        return 0.0
    # UGS occasionally returns impossible scores above critical max; never rate above 100%.
    return min((score / max_score) * 100, 100.0)


def _resolve_rating_level(
    key: str,
    entry_level: object,
    chart_rating_levels: dict[str, int] | None = None,
) -> int:
    """Prefer official chart_rating_levels.json over the level embedded in a save."""
    levels = (
        chart_rating_levels
        if chart_rating_levels is not None
        else load_chart_rating_levels()
    )
    official = resolve_chart_rating_level(key, levels)
    if official is not None and official > 0:
        base_level = official
    else:
        base_level = int(entry_level or 0)
    return resolve_chart_level(key, base_level)


def rate_chart(
    entry: dict,
    critical_max_score: int,
    chart_rating_levels: dict[str, int] | None = None,
) -> ChartRating:
    key = chart_key(entry["song"])
    song, difficulty = split_chart_key(key)
    level = _resolve_rating_level(
        key,
        entry.get("level", 0),
        chart_rating_levels=chart_rating_levels,
    )
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
    ex_bonus = compute_ex_grade_bonus(ex_accuracy, cleared)

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
    chart_rating_levels = load_chart_rating_levels()
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

        ratings.append(
            rate_chart(entry, critical_max, chart_rating_levels=chart_rating_levels)
        )

    return ratings
