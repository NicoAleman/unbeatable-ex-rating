"""Per-chart square claim scoring (v1 raw totals vs v2 accuracy + placement)."""

from __future__ import annotations

from dataclasses import dataclass

from rating.bingo_config import BINGO_SCORING_VERSION
from rating.calculator import ex_accuracy_percent

TEAM_ORDER = ("Eve", "Grace", "Rest")

EX_ACCURACY_FLOOR = 70.0


@dataclass(frozen=True)
class ChartPlayerPointBreakdown:
    accuracy_points: float
    placement_bonus: int
    rank: int


@dataclass(frozen=True)
class ChartClaimScoring:
    team_totals: dict[str, float]
    player_points_by_team: dict[str, list[float]]


def bingo_scoring_version() -> str:
    version = str(BINGO_SCORING_VERSION).strip().lower()
    if version not in {"v1", "v2"}:
        return "v1"
    return version


def accuracy_formula_points(ex_accuracy: float) -> float:
    """Points from EX Accuracy percentage (x), before placement bonus."""
    x = max(float(ex_accuracy), EX_ACCURACY_FLOOR)
    accuracy_term = (x**3) / (100.0**3)
    denominator = 1.0 - ((x - 1.0) / 100.0)
    if denominator <= 0.0:
        return 0.0
    return accuracy_term * (75.0 + (0.25 / denominator))


def placement_bonus_points(rank: int) -> int:
    """Bonus points for competition rank on a chart (1-based)."""
    if rank <= 0:
        return 0
    if rank <= 11:
        return 100 - (rank - 1) * 3
    if rank <= 22:
        return 68 - (rank - 12) * 2
    if rank <= 30:
        return 47 - (rank - 23)
    return max(0, 40 - (rank - 30))


def _competition_ranks(player_values: dict[str, float | int]) -> dict[str, int]:
    ordered = sorted(
        player_values.items(),
        key=lambda item: (-item[1], item[0]),
    )
    ranks: dict[str, int] = {}
    index = 0
    while index < len(ordered):
        next_index = index + 1
        while (
            next_index < len(ordered)
            and ordered[next_index][1] == ordered[index][1]
        ):
            next_index += 1
        rank = index + 1
        for player_index in range(index, next_index):
            ranks[ordered[player_index][0]] = rank
        index = next_index
    return ranks


def _placement_ranks_by_score(
    players: dict[str, tuple[str, int]],
) -> dict[str, int]:
    """Rank players by raw chart score for placement bonus (no EX accuracy floor)."""
    scores = {player_id: int(score) for player_id, (_team, score) in players.items()}
    return _competition_ranks(scores)


def _floored_accuracy_points() -> float:
    return accuracy_formula_points(EX_ACCURACY_FLOOR)


def _player_accuracy_points(*, score: int, song: str, difficulty: str) -> float:
    """Accuracy formula points; no submission scores 1 below the EX accuracy floor."""
    if int(score) <= 0:
        return float(max(0, _floored_accuracy_points() - 1))
    ex_accuracy = _player_ex_accuracy(
        score=int(score),
        song=song,
        difficulty=difficulty,
    )
    return accuracy_formula_points(ex_accuracy)


def compute_chart_player_point_breakdowns(
    *,
    song: str,
    difficulty: str,
    players: dict[str, tuple[str, int]],
) -> dict[str, ChartPlayerPointBreakdown]:
    """Per-player accuracy points, placement bonus, and competition rank for one chart."""
    accuracy_by_player: dict[str, float] = {}
    for player_id, (_team, score) in players.items():
        accuracy_by_player[player_id] = _player_accuracy_points(
            score=int(score),
            song=song,
            difficulty=difficulty,
        )

    ranks = _placement_ranks_by_score(players)
    return {
        player_id: ChartPlayerPointBreakdown(
            accuracy_points=accuracy_points,
            placement_bonus=placement_bonus_points(ranks[player_id]),
            rank=ranks[player_id],
        )
        for player_id, accuracy_points in accuracy_by_player.items()
    }


def _chart_max_score(song: str, difficulty: str) -> int | None:
    from rating.bingo import bingo_chart_max_score

    return bingo_chart_max_score(song, difficulty)


def _player_ex_accuracy(*, score: int, song: str, difficulty: str) -> float:
    max_score = _chart_max_score(song, difficulty)
    if max_score is None or max_score <= 0:
        return EX_ACCURACY_FLOOR
    return ex_accuracy_percent(int(score), int(max_score))


def compute_chart_claim_scoring_v2(
    *,
    song: str,
    difficulty: str,
    players: dict[str, tuple[str, int]],
) -> ChartClaimScoring:
    """Score each roster player on a chart; rank by raw score for placement bonus."""
    accuracy_by_player: dict[str, float] = {}
    team_by_player: dict[str, str] = {}
    for player_id, (team, score) in players.items():
        team_by_player[player_id] = team
        accuracy_by_player[player_id] = _player_accuracy_points(
            score=int(score),
            song=song,
            difficulty=difficulty,
        )

    ranks = _placement_ranks_by_score(players)
    team_totals: dict[str, float] = {team: 0.0 for team in TEAM_ORDER}
    player_points_by_team: dict[str, list[float]] = {team: [] for team in TEAM_ORDER}

    for player_id, accuracy_points in accuracy_by_player.items():
        team = team_by_player[player_id]
        rank = ranks[player_id]
        player_total = accuracy_points + float(placement_bonus_points(rank))
        if team not in team_totals:
            team_totals[team] = 0.0
            player_points_by_team[team] = []
        team_totals[team] += player_total
        player_points_by_team[team].append(player_total)

    for team in TEAM_ORDER:
        team_totals.setdefault(team, 0.0)
        player_points_by_team.setdefault(team, [])

    return ChartClaimScoring(
        team_totals={team: float(team_totals.get(team, 0.0)) for team in TEAM_ORDER},
        player_points_by_team=player_points_by_team,
    )


def compute_chart_claim_scoring_v1(
    players: dict[str, tuple[str, int]],
) -> ChartClaimScoring:
    """Legacy scoring: team total is the sum of member raw chart scores."""
    player_points_by_team: dict[str, list[float]] = {team: [] for team in TEAM_ORDER}
    for _player_id, (team, score) in players.items():
        if team not in player_points_by_team:
            player_points_by_team[team] = []
        player_points_by_team[team].append(float(int(score)))

    team_totals = {
        team: float(sum(player_points_by_team.get(team, []))) for team in TEAM_ORDER
    }
    for team in TEAM_ORDER:
        player_points_by_team.setdefault(team, [])
        team_totals.setdefault(team, 0)

    return ChartClaimScoring(
        team_totals=team_totals,
        player_points_by_team=player_points_by_team,
    )


def compute_chart_claim_scoring(
    *,
    song: str,
    difficulty: str,
    players: dict[str, tuple[str, int]],
) -> ChartClaimScoring:
    if bingo_scoring_version() == "v2":
        return compute_chart_claim_scoring_v2(
            song=song,
            difficulty=difficulty,
            players=players,
        )
    return compute_chart_claim_scoring_v1(players)
