"""Bingo game data loading and board score aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

from rating.chart_levels import load_chart_rating_levels, resolve_chart_rating_level
from rating.formatting import format_song_display_name
from rating.supabase_config import get_supabase_db_url

TEAM_ORDER = ("Eve", "Grace", "Rest")
TEAM_COLORS = {
    "Eve": "#1f6feb",
    "Grace": "#d1242f",
    "Rest": "#1a7f37",
}


@dataclass(frozen=True)
class BingoSettings:
    board_width: int
    start_time: datetime | None
    day_count: int | None


@dataclass(frozen=True)
class BingoChart:
    row: int
    column: int
    group: int | None
    song: str
    difficulty: str
    display_name: str
    level: int | None


@dataclass(frozen=True)
class BingoCellStanding:
    chart: BingoChart
    team_totals: dict[str, int]
    leader: str | None
    leader_score: int
    trailers: list[tuple[str, int]]


@dataclass(frozen=True)
class BingoTeamPlayer:
    player_id: str
    display_name: str
    team: str
    ex_rating: float


def _connect(db_url: str | None = None):
    url = db_url or get_supabase_db_url()
    if not url:
        raise RuntimeError(
            "Supabase is not configured. Set supabase.db_url in .streamlit/secrets.toml "
            "or SUPABASE_DB_URL in the environment."
        )
    return psycopg2.connect(url)


def load_bingo_settings(db_url: str | None = None) -> BingoSettings | None:
    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT board_width, start_time, day_count
                    FROM bingo_settings
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()
    except psycopg2.errors.UndefinedTable:
        return None
    if row is None:
        return None
    start_time = row["start_time"]
    if isinstance(start_time, datetime) and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    return BingoSettings(
        board_width=int(row["board_width"]),
        start_time=start_time,
        day_count=int(row["day_count"]) if row["day_count"] is not None else None,
    )


def load_bingo_charts(db_url: str | None = None) -> list[BingoChart]:
    levels = load_chart_rating_levels()
    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT "row", "column", "group", song, difficulty
                    FROM bingo_charts
                    ORDER BY "row", "column"
                    """
                )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return []

    charts: list[BingoChart] = []
    for row in rows:
        song = str(row["song"])
        difficulty = str(row["difficulty"])
        chart_key = f"{song}/{difficulty}"
        level = resolve_chart_rating_level(chart_key, levels)
        charts.append(
            BingoChart(
                row=int(row["row"]),
                column=int(row["column"]),
                group=int(row["group"]) if row["group"] is not None else None,
                song=song,
                difficulty=difficulty,
                display_name=format_song_display_name(song),
                level=level,
            )
        )
    return charts


def load_bingo_teams_by_ex_rating(
    db_url: str | None = None,
) -> dict[str, list[BingoTeamPlayer]]:
    """Load bingo roster grouped by team, each ordered by EX Rating desc."""
    from rating.public_leaderboard import load_ex_leaderboard

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT player_id, display_name, team
                    FROM bingo_teams
                    """
                )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return {team: [] for team in TEAM_ORDER}

    ratings_by_id = {
        entry.player_id: float(entry.ex_rating) for entry in load_ex_leaderboard()
    }
    grouped: dict[str, list[BingoTeamPlayer]] = {team: [] for team in TEAM_ORDER}
    for row in rows:
        team = str(row["team"])
        if team not in grouped:
            grouped[team] = []
        player_id = str(row["player_id"])
        grouped[team].append(
            BingoTeamPlayer(
                player_id=player_id,
                display_name=str(row["display_name"]),
                team=team,
                ex_rating=ratings_by_id.get(player_id, 0.0),
            )
        )

    for team, players in grouped.items():
        players.sort(
            key=lambda player: (-player.ex_rating, player.display_name.casefold())
        )
    return grouped


def load_bingo_chart_standings_data(
    *,
    start_time: datetime | None,
    db_url: str | None = None,
) -> dict[tuple[str, str], tuple[dict[str, int], dict[str, list[int]]]]:
    """Return {(song, difficulty): (team_totals, player_bests_by_team)}.

    player_bests_by_team maps team -> list of each player's best score (unsorted).
    """
    if start_time is None:
        return {}

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        player_id,
                        team,
                        song,
                        difficulty,
                        MAX(score)::BIGINT AS best_score
                    FROM bingo_scores
                    WHERE created_at >= %s
                    GROUP BY player_id, team, song, difficulty
                    """,
                    (start_time,),
                )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return {}

    player_bests: dict[tuple[str, str], dict[str, list[int]]] = {}
    for row in rows:
        key = (str(row["song"]), str(row["difficulty"]))
        team = str(row["team"])
        by_team = player_bests.setdefault(
            key, {team_name: [] for team_name in TEAM_ORDER}
        )
        if team not in by_team:
            by_team[team] = []
        by_team[team].append(int(row["best_score"]))

    result: dict[tuple[str, str], tuple[dict[str, int], dict[str, list[int]]]] = {}
    for key, by_team in player_bests.items():
        totals = {
            team: int(sum(scores)) for team, scores in by_team.items()
        }
        for team in TEAM_ORDER:
            totals.setdefault(team, 0)
            by_team.setdefault(team, [])
        result[key] = (totals, by_team)
    return result


def load_bingo_team_totals_by_chart(
    *,
    start_time: datetime | None,
    db_url: str | None = None,
) -> dict[tuple[str, str], dict[str, int]]:
    """Return {(song, difficulty): {team: total}} using each player's PB since start."""
    return {
        key: totals
        for key, (totals, _bests) in load_bingo_chart_standings_data(
            start_time=start_time, db_url=db_url
        ).items()
    }


def _team_tiebreak_key(team: str, player_bests: list[int]) -> tuple:
    """Higher is better: sorted individual scores desc, then Eve > Grace > Rest."""
    scores_desc = tuple(sorted((int(score) for score in player_bests), reverse=True))
    priority = len(TEAM_ORDER) - TEAM_ORDER.index(team)
    return (scores_desc, priority)


def pick_leading_team(
    team_totals: dict[str, int],
    player_bests_by_team: dict[str, list[int]],
) -> str | None:
    """Pick the leading team, breaking total ties by top individual scores."""
    max_total = max((int(total) for total in team_totals.values()), default=0)
    if max_total <= 0:
        return None

    candidates = [team for team in TEAM_ORDER if int(team_totals.get(team, 0)) == max_total]
    if len(candidates) == 1:
        return candidates[0]

    return max(
        candidates,
        key=lambda team: _team_tiebreak_key(
            team, player_bests_by_team.get(team, [])
        ),
    )


def build_cell_standing(
    chart: BingoChart,
    team_totals_by_chart: dict[tuple[str, str], dict[str, int]],
    player_bests_by_chart: dict[tuple[str, str], dict[str, list[int]]] | None = None,
) -> BingoCellStanding:
    raw = team_totals_by_chart.get((chart.song, chart.difficulty), {})
    team_totals = {team: int(raw.get(team, 0)) for team in TEAM_ORDER}
    max_score = max(team_totals.values()) if team_totals else 0
    if max_score <= 0:
        return BingoCellStanding(
            chart=chart,
            team_totals=team_totals,
            leader=None,
            leader_score=0,
            trailers=[],
        )

    bests = {}
    if player_bests_by_chart is not None:
        bests = player_bests_by_chart.get((chart.song, chart.difficulty), {})
    leader = pick_leading_team(team_totals, bests)
    trailers: list[tuple[str, int]] = []
    if leader is not None:
        for team in TEAM_ORDER:
            if team == leader:
                continue
            trailers.append((team, max_score - team_totals[team]))

    return BingoCellStanding(
        chart=chart,
        team_totals=team_totals,
        leader=leader,
        leader_score=max_score,
        trailers=trailers,
    )


def format_leader_score(score: int) -> str:
    """17,032,277 -> 17,032,277"""
    return f"{int(score):,}"


def format_score_diff(diff: int) -> str:
    """Trailing amount as -10,000 or -1,500,000."""
    amount = abs(int(diff))
    return f"-{amount:,}"


def seed_bingo_test_scores(
    *,
    score_min: int = 1_500_000,
    score_max: int = 1_800_000,
    db_url: str | None = None,
) -> int:
    """Insert one random score per player per chart at start_time + 1 hour."""
    import random

    settings = load_bingo_settings(db_url)
    if settings is None or settings.start_time is None:
        raise RuntimeError("bingo_settings.start_time is required to seed scores.")

    created_at = settings.start_time + timedelta(hours=1)
    with _connect(db_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT player_id, display_name, team FROM bingo_teams")
            players = cur.fetchall()
            cur.execute('SELECT song, difficulty FROM bingo_charts')
            charts = cur.fetchall()
            if not players or not charts:
                return 0

            cur.execute("DELETE FROM bingo_scores")
            rows = []
            for player in players:
                for chart in charts:
                    rows.append(
                        (
                            player["player_id"],
                            player["display_name"],
                            player["team"],
                            chart["song"],
                            chart["difficulty"],
                            random.randint(score_min, score_max),
                            "submission",
                            created_at,
                        )
                    )
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO bingo_scores (
                    player_id, display_name, team, song, difficulty,
                    score, source, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
                page_size=500,
            )
        conn.commit()
    return len(rows)
