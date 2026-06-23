from dataclasses import dataclass


@dataclass
class ChartRating:
    song: str
    difficulty: str
    level: int
    score: int
    max_score: int
    standard_accuracy: float
    standard_grade: str
    standard_rating: float
    ex_accuracy: float
    ex_grade: str
    ex_rating: float
