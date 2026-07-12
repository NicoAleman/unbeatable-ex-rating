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
    end_time: datetime | None = None,
    db_url: str | None = None,
) -> dict[tuple[str, str], tuple[dict[str, int], dict[str, list[int]]]]:
    """Return {(song, difficulty): (team_totals, player_bests_by_team)}.

    player_bests_by_team maps team -> list of each player's best score (unsorted).
    Scores are filtered to created_at >= start_time, and if end_time is set,
    created_at < end_time (cumulative through that instant).
    """
    if start_time is None:
        return {}

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if end_time is None:
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
                else:
                    cur.execute(
                        """
                        SELECT
                            player_id,
                            team,
                            song,
                            difficulty,
                            MAX(score)::BIGINT AS best_score
                        FROM bingo_scores
                        WHERE created_at >= %s AND created_at < %s
                        GROUP BY player_id, team, song, difficulty
                        """,
                        (start_time, end_time),
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
    end_time: datetime | None = None,
    db_url: str | None = None,
) -> dict[tuple[str, str], dict[str, int]]:
    """Return {(song, difficulty): {team: total}} using each player's PB since start."""
    return {
        key: totals
        for key, (totals, _bests) in load_bingo_chart_standings_data(
            start_time=start_time, end_time=end_time, db_url=db_url
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


def bingo_day_end(start_time: datetime, day: int) -> datetime:
    """Exclusive end instant of 1-based competition day."""
    return start_time + timedelta(days=max(1, int(day)))


def bingo_day_multiplier(day: int, day_count: int) -> int:
    """Point multiplier for a competition day.

    Days 1-2: 1x, days 3-4: 2x, remaining pre-final days: 3x, final day: 10x.
    """
    day = int(day)
    day_count = max(1, int(day_count))
    if day < 1 or day > day_count:
        return 0
    if day == day_count:
        return 10
    if day >= 5:
        return 3
    if day >= 3:
        return 2
    return 1


def completed_bingo_days(
    *,
    start_time: datetime,
    day_count: int,
    now: datetime | None = None,
) -> int:
    """How many full competition days have finished (0 .. day_count)."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if current < start_time:
        return 0
    elapsed = current - start_time
    finished = int(elapsed.total_seconds() // 86400)
    return max(0, min(int(day_count), finished))


def find_bingo_runs(
    leaders_by_coord: dict[tuple[int, int], str | None],
    *,
    rows: int,
    cols: int,
) -> list[tuple[str, list[tuple[int, int]], str, str]]:
    """Return bingo / near-bingo runs as (orientation, coords, team, style).

    style is "solid" for a full board bingo line, or "dashed" for exactly 4
    in a row. Full bingos never also emit overlapping 4-cell dashed runs on
    the same line.
    """

    def claimed_team(coords: list[tuple[int, int]]) -> str | None:
        if len(coords) < 2:
            return None
        teams = [leaders_by_coord.get(coord) for coord in coords]
        if any(team is None for team in teams):
            return None
        unique = set(teams)
        if len(unique) != 1:
            return None
        return next(iter(unique))

    runs: list[tuple[str, list[tuple[int, int]], str, str]] = []
    seen: set[tuple[tuple[int, int], ...]] = set()

    def add_line(
        orientation: str,
        coords: list[tuple[int, int]],
        team: str,
        style: str,
    ) -> None:
        key = tuple(coords)
        if key in seen:
            return
        seen.add(key)
        runs.append((orientation, coords, team, style))

    def add_runs_on_line(orientation: str, coords: list[tuple[int, int]]) -> None:
        if len(coords) < 4:
            return

        is_full_board_line = (
            (orientation == "h" and len(coords) == cols)
            or (orientation == "v" and len(coords) == rows)
            or (
                orientation in ("d", "a")
                and rows == cols
                and len(coords) == rows
            )
        )
        if is_full_board_line:
            full_team = claimed_team(coords)
            if full_team is not None:
                add_line(orientation, coords, full_team, "solid")
                return

        for start in range(0, len(coords) - 3):
            window = coords[start : start + 4]
            team = claimed_team(window)
            if team is not None:
                add_line(orientation, window, team, "dashed")

    for row in range(rows):
        add_runs_on_line("h", [(row, col) for col in range(cols)])

    for col in range(cols):
        add_runs_on_line("v", [(row, col) for row in range(rows)])

    for start_row in range(rows):
        for start_col in range(cols):
            if start_row > 0 and start_col > 0:
                continue
            coords: list[tuple[int, int]] = []
            row, col = start_row, start_col
            while row < rows and col < cols:
                coords.append((row, col))
                row += 1
                col += 1
            add_runs_on_line("d", coords)

    for start_row in range(rows):
        for start_col in range(cols):
            if start_row > 0 and start_col < cols - 1:
                continue
            coords = []
            row, col = start_row, start_col
            while row < rows and col >= 0:
                coords.append((row, col))
                row += 1
                col -= 1
            add_runs_on_line("a", coords)

    return runs


def group_claim_owners(
    charts: list[BingoChart],
    totals: dict[tuple[str, str], dict[str, int]],
    player_bests: dict[tuple[str, str], dict[str, list[int]]],
) -> dict[int, str]:
    """Return {group_id: team} when that team leads every chart in the group."""
    by_group: dict[int, list[BingoChart]] = {}
    for chart in charts:
        if chart.group is None:
            continue
        by_group.setdefault(int(chart.group), []).append(chart)

    claimed: dict[int, str] = {}
    for group_id, group_charts in by_group.items():
        leaders = [
            build_cell_standing(chart, totals, player_bests).leader
            for chart in group_charts
        ]
        if not leaders or any(leader is None for leader in leaders):
            continue
        first = leaders[0]
        if first is not None and all(leader == first for leader in leaders):
            claimed[group_id] = first
    return claimed


@dataclass(frozen=True)
class TeamDayPoints:
    day: int
    multiplier: int
    squares: int
    groups: int
    bingos: int
    fours: int
    raw_points: int
    points: int


def score_board_state(
    *,
    charts: list[BingoChart],
    standings_data: dict[
        tuple[str, str], tuple[dict[str, int], dict[str, list[int]]]
    ],
    board_width: int,
    day: int,
    day_count: int,
) -> dict[str, TeamDayPoints]:
    """Score each team from a board snapshot (cumulative through a day end)."""
    totals = {key: values[0] for key, values in standings_data.items()}
    player_bests = {key: values[1] for key, values in standings_data.items()}

    max_row = max((chart.row for chart in charts), default=0)
    max_col = max((chart.column for chart in charts), default=0)
    rows = max(board_width, max_row + 1)
    cols = max(board_width, max_col + 1)

    leaders_by_coord: dict[tuple[int, int], str | None] = {}
    square_counts = {team: 0 for team in TEAM_ORDER}
    for chart in charts:
        leader = build_cell_standing(chart, totals, player_bests).leader
        leaders_by_coord[(chart.row, chart.column)] = leader
        if leader is not None:
            square_counts[leader] = square_counts.get(leader, 0) + 1

    group_counts = {team: 0 for team in TEAM_ORDER}
    for team in group_claim_owners(charts, totals, player_bests).values():
        group_counts[team] = group_counts.get(team, 0) + 1

    bingo_counts = {team: 0 for team in TEAM_ORDER}
    four_counts = {team: 0 for team in TEAM_ORDER}
    for _orientation, _coords, team, style in find_bingo_runs(
        leaders_by_coord, rows=rows, cols=cols
    ):
        if style == "solid":
            bingo_counts[team] = bingo_counts.get(team, 0) + 1
        else:
            four_counts[team] = four_counts.get(team, 0) + 1

    multiplier = bingo_day_multiplier(day, day_count)
    result: dict[str, TeamDayPoints] = {}
    for team in TEAM_ORDER:
        squares = int(square_counts.get(team, 0))
        groups = int(group_counts.get(team, 0))
        bingos = int(bingo_counts.get(team, 0))
        fours = int(four_counts.get(team, 0))
        raw = squares + (2 * groups) + (3 * bingos) + (1 * fours)
        result[team] = TeamDayPoints(
            day=day,
            multiplier=multiplier,
            squares=squares,
            groups=groups,
            bingos=bingos,
            fours=fours,
            raw_points=raw,
            points=raw * multiplier,
        )
    return result


@dataclass(frozen=True)
class BingoScoreboard:
    day_count: int
    completed_days: int
    # Per team: list length day_count; None means unfinished / blank.
    daily_points: dict[str, list[int | None]]
    totals: dict[str, int]


def compute_bingo_scoreboard(
    *,
    settings: BingoSettings,
    charts: list[BingoChart],
    now: datetime | None = None,
    db_url: str | None = None,
) -> BingoScoreboard | None:
    """Build the baseball-style daily points scoreboard."""
    if settings.start_time is None or settings.day_count is None:
        return None
    if not charts:
        return None

    day_count = max(1, int(settings.day_count))
    finished = completed_bingo_days(
        start_time=settings.start_time,
        day_count=day_count,
        now=now,
    )

    daily_points: dict[str, list[int | None]] = {
        team: [None] * day_count for team in TEAM_ORDER
    }
    totals = {team: 0 for team in TEAM_ORDER}

    for day in range(1, finished + 1):
        standings = load_bingo_chart_standings_data(
            start_time=settings.start_time,
            end_time=bingo_day_end(settings.start_time, day),
            db_url=db_url,
        )
        day_scores = score_board_state(
            charts=charts,
            standings_data=standings,
            board_width=int(settings.board_width),
            day=day,
            day_count=day_count,
        )
        for team in TEAM_ORDER:
            points = int(day_scores[team].points)
            daily_points[team][day - 1] = points
            totals[team] += points

    return BingoScoreboard(
        day_count=day_count,
        completed_days=finished,
        daily_points=daily_points,
        totals=totals,
    )


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
            cur.execute("SELECT song, difficulty FROM bingo_charts")
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


def seed_bingo_progressive_day_scores(
    *,
    days: int = 5,
    shift_start_to_past: bool = True,
    db_url: str | None = None,
) -> tuple[int, datetime]:
    """Clear scores and insert rising random scores through the middle of each day.

    Day N scores are random in [1_000_000 + (N-1)*100_000, 1_100_000 + (N-1)*100_000]
    with created_at at the midpoint of that competition day.

    When shift_start_to_past is True, moves start_time so that ``days`` full
    competition days have completed (for scoreboard simulation).
    """
    import random

    settings = load_bingo_settings(db_url)
    if settings is None:
        raise RuntimeError("bingo_settings are required to seed scores.")
    day_count = max(1, int(settings.day_count or days))
    days = max(1, min(int(days), day_count))

    now = datetime.now(timezone.utc)
    if shift_start_to_past:
        # Place "now" just after day ``days`` ends so those days are complete.
        start_time = now - timedelta(days=days, hours=1)
    else:
        if settings.start_time is None:
            raise RuntimeError("bingo_settings.start_time is required.")
        start_time = settings.start_time

    with _connect(db_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if shift_start_to_past:
                cur.execute(
                    """
                    UPDATE bingo_settings
                    SET start_time = %s
                    WHERE id = 1
                    """,
                    (start_time,),
                )

            cur.execute("SELECT player_id, display_name, team FROM bingo_teams")
            players = cur.fetchall()
            cur.execute("SELECT song, difficulty FROM bingo_charts")
            charts = cur.fetchall()
            if not players or not charts:
                conn.commit()
                return 0, start_time

            cur.execute("DELETE FROM bingo_scores")
            rows = []
            for day in range(1, days + 1):
                score_min = 1_000_000 + (day - 1) * 100_000
                score_max = 1_100_000 + (day - 1) * 100_000
                created_at = start_time + timedelta(days=day - 1, hours=12)
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
    return len(rows), start_time
