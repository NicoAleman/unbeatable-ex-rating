import csv
import json
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from rating.board import competition_ranks_for_values, player_ex_rating_with_completion
from rating.calculator import rate_chart
from rating.constants import DEFAULT_MAX_SCORES_PATH, FULL_EX_RATING_LEADERBOARD_PATH, LEADERBOARDS_JUNE27_DIR
from rating.data import load_critical_max_scores
from rating.formatting import format_rating_display
from rating.models import ChartRating

FULL_EX_LEADERBOARD_HEADERS = ["Rank", "Player", "EX Rating", "Charts Rated"]


@dataclass(frozen=True)
class FullExRankingEntry:
    rank: int
    player: str
    ex_rating: float
    charts_rated: int


def resolve_max_score_chart_key(
    song: str,
    difficulty: str,
    max_scores: dict[str, int],
) -> str | None:
    key = f"{song}/{difficulty}"
    if key in max_scores:
        return key

    key_lower = key.casefold()
    for chart_key in max_scores:
        if chart_key.casefold() == key_lower:
            return chart_key
    return None


def _leaderboard_score_to_highscore_entry(score: dict, chart_key: str) -> dict:
    song, difficulty = chart_key.rsplit("/", 1)
    return {
        "song": f"{song}/{difficulty}\\Classic",
        "score": score.get("score", 0),
        "level": score.get("level", 0),
        "cleared": True,
        "accuracy": 0,
        "notes": [],
        "maxCombo": 1,
    }


def build_ratings_from_imported_player(
    player_data: dict,
    max_scores_path: Path = DEFAULT_MAX_SCORES_PATH,
) -> list[ChartRating]:
    max_scores = load_critical_max_scores(max_scores_path)
    best_by_chart: dict[str, ChartRating] = {}

    for score in player_data.get("scores", []):
        if score.get("speed") != "Classic":
            continue

        song = str(score.get("song", "")).strip()
        difficulty = str(score.get("difficulty", "")).strip()
        if not song or not difficulty:
            continue

        chart_key = resolve_max_score_chart_key(song, difficulty, max_scores)
        if chart_key is None:
            continue

        entry = _leaderboard_score_to_highscore_entry(score, chart_key)
        rating = rate_chart(entry, max_scores[chart_key])
        existing = best_by_chart.get(chart_key)
        if existing is None or rating.ex_rating > existing.ex_rating:
            best_by_chart[chart_key] = rating

    return list(best_by_chart.values())


def build_full_ex_rankings(
    leaderboard_scores_dir: Path = LEADERBOARDS_JUNE27_DIR,
    max_scores_path: Path = DEFAULT_MAX_SCORES_PATH,
) -> list[FullExRankingEntry]:
    rankings: list[FullExRankingEntry] = []

    for player_path in sorted(leaderboard_scores_dir.glob("*.json")):
        player_data = json.loads(player_path.read_text(encoding="utf-8"))
        display_name = str(player_data.get("displayName", "")).strip()
        if not display_name:
            print(
                f"Warning: skipping {player_path.name} with no displayName",
                file=sys.stderr,
            )
            continue

        ratings = build_ratings_from_imported_player(player_data, max_scores_path)
        if not ratings:
            continue

        rankings.append(
            FullExRankingEntry(
                rank=0,
                player=display_name,
                ex_rating=player_ex_rating_with_completion(ratings),
                charts_rated=len(ratings),
            )
        )

    rankings.sort(key=lambda entry: entry.ex_rating, reverse=True)
    ranks = competition_ranks_for_values([entry.ex_rating for entry in rankings])
    return [
        FullExRankingEntry(
            rank=rank,
            player=entry.player,
            ex_rating=entry.ex_rating,
            charts_rated=entry.charts_rated,
        )
        for rank, entry in zip(ranks, rankings, strict=True)
    ]


def format_full_ex_leaderboard_csv(rankings: list[FullExRankingEntry]) -> str:
    ranks = competition_ranks_for_values([entry.ex_rating for entry in rankings])
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(FULL_EX_LEADERBOARD_HEADERS)
    for rank, entry in zip(ranks, rankings, strict=True):
        writer.writerow(
            [
                rank,
                entry.player,
                format_rating_display(entry.ex_rating),
                entry.charts_rated,
            ]
        )
    return buffer.getvalue()


def write_full_ex_leaderboard_csv(
    output_path: Path = FULL_EX_RATING_LEADERBOARD_PATH,
    leaderboard_scores_dir: Path = LEADERBOARDS_JUNE27_DIR,
    max_scores_path: Path = DEFAULT_MAX_SCORES_PATH,
) -> list[FullExRankingEntry]:
    rankings = build_full_ex_rankings(leaderboard_scores_dir, max_scores_path)
    output_path.write_text(
        format_full_ex_leaderboard_csv(rankings),
        encoding="utf-8",
    )
    return rankings


def load_full_ex_leaderboard_csv(
    csv_path: Path = FULL_EX_RATING_LEADERBOARD_PATH,
) -> list[FullExRankingEntry]:
    text = csv_path.read_text(encoding="utf-8")
    reader = csv.DictReader(StringIO(text))
    rankings: list[FullExRankingEntry] = []
    for row in reader:
        player = str(row.get("Player", "")).strip()
        ex_rating_text = str(row.get("EX Rating", "")).strip()
        charts_rated_text = str(row.get("Charts Rated", "")).strip()
        if not player or not ex_rating_text:
            continue
        rankings.append(
            FullExRankingEntry(
                rank=int(str(row.get("Rank", "")).strip() or 0),
                player=player,
                ex_rating=float(ex_rating_text),
                charts_rated=int(charts_rated_text or 0),
            )
        )
    return rankings
