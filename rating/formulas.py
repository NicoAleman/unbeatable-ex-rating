"""Shared rating formulas: accuracy power, grades, grade bonus, and star rating."""

from rating.constants import EX_S_PLUS_THRESHOLD, RATING_DIVISOR


def accuracy_power(acc_percent: float) -> float:
    if acc_percent <= 50:
        return 0.0
    return (acc_percent - 50) ** 1.12


def song_star_rating(acc_percent: float, diff_level: int, grade_bonus: int) -> float:
    return (diff_level * (accuracy_power(acc_percent) + grade_bonus)) / RATING_DIVISOR


def compute_standard_grade(acc_percent: float, miss_count: int, cleared: bool) -> str:
    if not cleared:
        return "F"

    has_misses = miss_count > 0

    if acc_percent >= 100.0:
        return "S++"
    if not has_misses and acc_percent > 99.0:
        return "S+"

    grade_acc = acc_percent + (1.0 if not has_misses else 0.0)

    if grade_acc >= 95.0:
        return "S"
    if grade_acc >= 85.0:
        return "A"
    if grade_acc >= 75.0:
        return "B"
    if grade_acc >= 65.0:
        return "C"
    if grade_acc >= 55.0:
        return "D"
    return "HOW?"


def compute_ex_grade(
    ex_accuracy: float,
    miss_count: int,
    cleared: bool,
    critical_count: int,
    max_combo: int,
) -> str:
    if not cleared:
        return "F"

    has_misses = miss_count > 0
    grade_acc = ex_accuracy + (1.0 if not has_misses else 0.0)

    if not has_misses and grade_acc >= 95.0 and critical_count == max_combo:
        return "S++"
    if not has_misses and ex_accuracy >= EX_S_PLUS_THRESHOLD:
        return "S+"
    if grade_acc >= 95.0:
        return "S"
    if grade_acc >= 85.0:
        return "A"
    if grade_acc >= 75.0:
        return "B"
    if grade_acc >= 65.0:
        return "C"
    if grade_acc >= 55.0:
        return "D"
    return "HOW?"


def compute_grade_bonus(acc_percent: float, miss_count: int, cleared: bool) -> int:
    if acc_percent > 90:
        return 25
    if miss_count == 0 and acc_percent > 89:
        return 25

    grade = compute_standard_grade(acc_percent, miss_count, cleared)
    if grade == "A":
        return 20
    if grade == "B":
        return 15
    if grade == "C":
        return 12
    if grade in ("D", "HOW?"):
        return 10
    return 0
