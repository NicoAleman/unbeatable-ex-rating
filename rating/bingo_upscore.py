"""Upscore calculator: project v2 chart points after a score improvement."""

from __future__ import annotations

from dataclasses import dataclass

from rating.bingo_chart_scoring import (
    EX_ACCURACY_FLOOR,
    ChartPlayerPointBreakdown,
    bingo_scoring_version,
    compute_chart_claim_scoring_v2,
    compute_chart_player_point_breakdowns,
    placement_bonus_points,
)
from rating.calculator import ex_accuracy_percent

TEAM_ORDER = ("Eve", "Grace", "Rest")


@dataclass(frozen=True)
class UpscorePlayerDelta:
    player_id: str
    team: str
    before_total: int
    after_total: int
    before_accuracy: int
    after_accuracy: int
    before_placement: int
    after_placement: int

    @property
    def total_delta(self) -> int:
        return int(self.after_total - self.before_total)


@dataclass(frozen=True)
class UpscoreScenarioResult:
    target_ex_accuracy: float
    required_score: int
    target_player: UpscorePlayerDelta
    team_deltas: dict[str, int]
    player_deltas: dict[str, UpscorePlayerDelta]


def score_for_ex_accuracy_percent(*, max_score: int, target_percent: float) -> int:
    """Minimum raw score to reach at least target_percent EX accuracy."""
    if max_score <= 0:
        return 0
    pct = max(0.0, min(float(target_percent), 100.0))
    return int((pct / 100.0) * max_score)


def ex_accuracy_for_score(*, score: int, max_score: int) -> float:
    if max_score <= 0:
        return 0.0
    return ex_accuracy_percent(int(score), int(max_score))


def _player_totals_from_breakdowns(
    breakdowns: dict[str, ChartPlayerPointBreakdown],
    players: dict[str, tuple[str, int]],
) -> dict[str, UpscorePlayerDelta]:
    result: dict[str, UpscorePlayerDelta] = {}
    for player_id, breakdown in breakdowns.items():
        team = players[player_id][0]
        total = int(breakdown.accuracy_points + breakdown.placement_bonus)
        result[player_id] = UpscorePlayerDelta(
            player_id=player_id,
            team=team,
            before_total=total,
            after_total=total,
            before_accuracy=int(breakdown.accuracy_points),
            after_accuracy=int(breakdown.accuracy_points),
            before_placement=int(breakdown.placement_bonus),
            after_placement=int(breakdown.placement_bonus),
        )
    return result


def compute_upscore_scenario(
    *,
    song: str,
    difficulty: str,
    max_score: int,
    players: dict[str, tuple[str, int]],
    target_player_id: str,
    target_ex_accuracy: float,
) -> UpscoreScenarioResult | None:
    """Compare team points before/after target player reaches target_ex_accuracy."""
    if bingo_scoring_version() != "v2" or max_score <= 0:
        return None
    if target_player_id not in players:
        return None

    target_pct = max(
        ex_accuracy_for_score(
            score=int(players[target_player_id][1]),
            max_score=max_score,
        ),
        min(float(target_ex_accuracy), 100.0),
    )
    required_score = score_for_ex_accuracy_percent(
        max_score=max_score,
        target_percent=target_pct,
    )

    before_breakdowns = compute_chart_player_point_breakdowns(
        song=song,
        difficulty=difficulty,
        players=players,
    )
    before_claim = compute_chart_claim_scoring_v2(
        song=song,
        difficulty=difficulty,
        players=players,
    )
    before_players = _player_totals_from_breakdowns(before_breakdowns, players)

    after_players_map = dict(players)
    team, _score = after_players_map[target_player_id]
    after_players_map[target_player_id] = (team, required_score)

    after_breakdowns = compute_chart_player_point_breakdowns(
        song=song,
        difficulty=difficulty,
        players=after_players_map,
    )
    after_claim = compute_chart_claim_scoring_v2(
        song=song,
        difficulty=difficulty,
        players=after_players_map,
    )

    player_deltas: dict[str, UpscorePlayerDelta] = {}
    for player_id in players:
        before = before_breakdowns[player_id]
        after = after_breakdowns[player_id]
        before_total = int(before.accuracy_points + before.placement_bonus)
        after_total = int(after.accuracy_points + after.placement_bonus)
        player_deltas[player_id] = UpscorePlayerDelta(
            player_id=player_id,
            team=players[player_id][0],
            before_total=before_total,
            after_total=after_total,
            before_accuracy=int(before.accuracy_points),
            after_accuracy=int(after.accuracy_points),
            before_placement=int(before.placement_bonus),
            after_placement=int(after.placement_bonus),
        )

    team_deltas = {
        team: int(after_claim.team_totals.get(team, 0))
        - int(before_claim.team_totals.get(team, 0))
        for team in TEAM_ORDER
    }

    return UpscoreScenarioResult(
        target_ex_accuracy=target_pct,
        required_score=required_score,
        target_player=player_deltas[target_player_id],
        team_deltas=team_deltas,
        player_deltas=player_deltas,
    )


def build_chart_upscore_payload(
    *,
    song: str,
    difficulty: str,
    roster: dict[str, list],
    entries_by_id: dict[str, tuple[str, str, int]],
    default_player_id: str | None,
    max_score: int | None,
) -> dict | None:
    """JSON-serializable upscore data for one chart modal."""
    if bingo_scoring_version() != "v2" or max_score is None or max_score <= 0:
        return None

    players: list[dict[str, object]] = []
    players_map: dict[str, tuple[str, int]] = {}
    for team in TEAM_ORDER:
        for player in roster.get(team, []):
            entry = entries_by_id.get(player.player_id)
            score = int(entry[2]) if entry is not None else 0
            players.append(
                {
                    "player_id": player.player_id,
                    "display_name": player.display_name,
                    "team": player.team,
                    "score": score,
                }
            )
            players_map[player.player_id] = (player.team, score)

    return {
        "song": song,
        "difficulty": difficulty,
        "max_score": int(max_score),
        "ex_accuracy_floor": EX_ACCURACY_FLOOR,
        "default_player_id": default_player_id,
        "players": players,
        "placement_bonus": [
            placement_bonus_points(rank)
            for rank in range(1, 32)
        ],
    }
