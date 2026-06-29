import csv
import json
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from rating.board import competition_ranks_for_values, player_ex_rating_with_completion
from rating.calculator import rate_chart
from rating.chart_levels import load_chart_rating_levels, resolve_chart_rating_level
from rating.constants import DEFAULT_MAX_SCORES_PATH, FULL_EX_RATING_LEADERBOARD_PATH, LEADERBOARDS_JUNE27_DIR
from rating.data import load_critical_max_scores
from rating.formatting import format_rating_display
from rating.models import ChartRating

FULL_EX_LEADERBOARD_HEADERS = ["Rank", "Player ID", "Player", "EX Rating", "Charts Rated"]
FULL_EX_LEADERBOARD_DISPLAY_HEADERS = ["Rank", "Player", "EX Rating"]


@dataclass(frozen=True)
class FullExRankingEntry:
    rank: int
    player_id: str
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


def _leaderboard_score_to_highscore_entry(score: dict, chart_key: str, level: int) -> dict:
    song, difficulty = chart_key.rsplit("/", 1)
    return {
        "song": f"{song}/{difficulty}\\Classic",
        "score": score.get("score", 0),
        "level": level,
        "cleared": True,
        "accuracy": 0,
        "notes": [],
        "maxCombo": 1,
    }


def build_ratings_from_imported_player(
    player_data: dict,
    max_scores_path: Path = DEFAULT_MAX_SCORES_PATH,
    chart_rating_levels: dict[str, int] | None = None,
) -> list[ChartRating]:
    max_scores = load_critical_max_scores(max_scores_path)
    levels = chart_rating_levels if chart_rating_levels is not None else load_chart_rating_levels()
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

        level = resolve_chart_rating_level(chart_key, levels)
        if level is None:
            continue

        entry = _leaderboard_score_to_highscore_entry(score, chart_key, level)
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
    chart_rating_levels = load_chart_rating_levels()

    for index, player_path in enumerate(sorted(leaderboard_scores_dir.glob("*.json")), 1):
        player_data = json.loads(player_path.read_text(encoding="utf-8"))
        player_id = str(player_data.get("playerId", "")).strip()
        display_name = str(player_data.get("displayName", "")).strip()
        if not player_id:
            print(
                f"Warning: skipping {player_path.name} with no playerId",
                file=sys.stderr,
            )
            continue
        if not display_name:
            print(
                f"Warning: skipping {player_path.name} with no displayName",
                file=sys.stderr,
            )
            continue

        ratings = build_ratings_from_imported_player(
            player_data,
            max_scores_path,
            chart_rating_levels,
        )
        if not ratings:
            continue

        rankings.append(
            FullExRankingEntry(
                rank=0,
                player_id=player_id,
                player=display_name,
                ex_rating=player_ex_rating_with_completion(ratings),
                charts_rated=len(ratings),
            )
        )

        if index % 5000 == 0:
            print(f"Processed {index} player files…", file=sys.stderr)

    rankings.sort(key=lambda entry: entry.ex_rating, reverse=True)
    ranks = competition_ranks_for_values([entry.ex_rating for entry in rankings])
    return [
        FullExRankingEntry(
            rank=rank,
            player_id=entry.player_id,
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
                entry.player_id,
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
        player_id = str(row.get("Player ID", "")).strip()
        ex_rating_text = str(row.get("EX Rating", "")).strip()
        charts_rated_text = str(row.get("Charts Rated", "")).strip()
        if not player or not ex_rating_text:
            continue
        rankings.append(
            FullExRankingEntry(
                rank=int(str(row.get("Rank", "")).strip() or 0),
                player_id=player_id,
                player=player,
                ex_rating=float(ex_rating_text),
                charts_rated=int(charts_rated_text or 0),
            )
        )
    return rankings
