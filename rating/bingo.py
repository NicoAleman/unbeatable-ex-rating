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


@dataclass(frozen=True)
class BingoChartLeaderboardEntry:
    player_id: str
    display_name: str
    team: str
    score: int


@dataclass(frozen=True)
class BingoSquareClaimEvent:
    """A team taking a square that was empty or held by another team."""

    song: str
    difficulty: str
    chart_display_name: str
    level: int | None
    row: int
    column: int
    team: str
    prev_team: str | None
    player_id: str
    player_display_name: str
    score: int
    created_at: datetime
    formed_bingo: bool = False
    formed_four: bool = False
    captured_group: bool = False
    # (team, delta) ordered: gainer first, then losers by most points lost.
    point_impacts: tuple[tuple[str, int], ...] = ()

    @property
    def is_flip(self) -> bool:
        return self.prev_team is not None


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


def load_bingo_chart_player_leaderboard(
    *,
    song: str,
    difficulty: str,
    start_time: datetime | None,
    end_time: datetime | None = None,
    db_url: str | None = None,
) -> list[BingoChartLeaderboardEntry]:
    """Return per-player best scores for one chart within the board time window."""
    if start_time is None:
        return []

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if end_time is None:
                    cur.execute(
                        """
                        SELECT
                            player_id,
                            display_name,
                            team,
                            MAX(score)::BIGINT AS best_score
                        FROM bingo_scores
                        WHERE song = %s
                          AND difficulty = %s
                          AND created_at >= %s
                        GROUP BY player_id, display_name, team
                        ORDER BY best_score DESC, LOWER(display_name) ASC
                        """,
                        (song, difficulty, start_time),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            player_id,
                            display_name,
                            team,
                            MAX(score)::BIGINT AS best_score
                        FROM bingo_scores
                        WHERE song = %s
                          AND difficulty = %s
                          AND created_at >= %s
                          AND created_at < %s
                        GROUP BY player_id, display_name, team
                        ORDER BY best_score DESC, LOWER(display_name) ASC
                        """,
                        (song, difficulty, start_time, end_time),
                    )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return []

    return [
        BingoChartLeaderboardEntry(
            player_id=str(row["player_id"]),
            display_name=str(row["display_name"]),
            team=str(row["team"]),
            score=int(row["best_score"]),
        )
        for row in rows
    ]


def load_all_bingo_chart_player_leaderboards(
    *,
    start_time: datetime | None,
    end_time: datetime | None = None,
    db_url: str | None = None,
) -> dict[tuple[str, str], list[BingoChartLeaderboardEntry]]:
    """Return {(song, difficulty): [player entries]} for the board time window."""
    if start_time is None:
        return {}

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if end_time is None:
                    cur.execute(
                        """
                        SELECT
                            song,
                            difficulty,
                            player_id,
                            display_name,
                            team,
                            MAX(score)::BIGINT AS best_score
                        FROM bingo_scores
                        WHERE created_at >= %s
                        GROUP BY song, difficulty, player_id, display_name, team
                        ORDER BY song, difficulty, best_score DESC, LOWER(display_name) ASC
                        """,
                        (start_time,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            song,
                            difficulty,
                            player_id,
                            display_name,
                            team,
                            MAX(score)::BIGINT AS best_score
                        FROM bingo_scores
                        WHERE created_at >= %s
                          AND created_at < %s
                        GROUP BY song, difficulty, player_id, display_name, team
                        ORDER BY song, difficulty, best_score DESC, LOWER(display_name) ASC
                        """,
                        (start_time, end_time),
                    )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return {}

    result: dict[tuple[str, str], list[BingoChartLeaderboardEntry]] = {}
    for row in rows:
        key = (str(row["song"]), str(row["difficulty"]))
        result.setdefault(key, []).append(
            BingoChartLeaderboardEntry(
                player_id=str(row["player_id"]),
                display_name=str(row["display_name"]),
                team=str(row["team"]),
                score=int(row["best_score"]),
            )
        )
    return result


def merge_chart_leaderboard_with_roster(
    roster: dict[str, list[BingoTeamPlayer]],
    entries: list[BingoChartLeaderboardEntry],
) -> list[BingoChartLeaderboardEntry]:
    """Include every roster player; missing scores become 0."""
    best_by_id = {entry.player_id: entry for entry in entries}
    merged: list[BingoChartLeaderboardEntry] = []
    seen: set[str] = set()

    for team in TEAM_ORDER:
        for player in roster.get(team, []):
            seen.add(player.player_id)
            existing = best_by_id.get(player.player_id)
            if existing is not None:
                merged.append(existing)
            else:
                merged.append(
                    BingoChartLeaderboardEntry(
                        player_id=player.player_id,
                        display_name=player.display_name,
                        team=player.team,
                        score=0,
                    )
                )

    for entry in entries:
        if entry.player_id not in seen:
            merged.append(entry)

    merged.sort(key=lambda entry: (-entry.score, entry.display_name.casefold()))
    return merged


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


def _leader_for_chart_bests(
    player_bests: dict[str, tuple[str, int]],
) -> str | None:
    """player_bests maps player_id -> (team, best_score)."""
    by_team_scores: dict[str, list[int]] = {team: [] for team in TEAM_ORDER}
    for team, score in player_bests.values():
        if team not in by_team_scores:
            by_team_scores[team] = []
        by_team_scores[team].append(int(score))
    totals = {team: int(sum(scores)) for team, scores in by_team_scores.items()}
    for team in TEAM_ORDER:
        totals.setdefault(team, 0)
        by_team_scores.setdefault(team, [])
    return pick_leading_team(totals, by_team_scores)


def _standings_maps_from_player_bests(
    bests_by_chart: dict[tuple[str, str], dict[str, tuple[str, int]]],
) -> tuple[
    dict[tuple[str, str], dict[str, int]],
    dict[tuple[str, str], dict[str, list[int]]],
]:
    totals: dict[tuple[str, str], dict[str, int]] = {}
    player_bests: dict[tuple[str, str], dict[str, list[int]]] = {}
    for key, players in bests_by_chart.items():
        by_team: dict[str, list[int]] = {team: [] for team in TEAM_ORDER}
        for team, score in players.values():
            if team not in by_team:
                by_team[team] = []
            by_team[team].append(int(score))
        for team in TEAM_ORDER:
            by_team.setdefault(team, [])
        totals[key] = {team: int(sum(scores)) for team, scores in by_team.items()}
        player_bests[key] = by_team
    return totals, player_bests


def _leaders_by_coord_from_charts(
    charts: list[BingoChart],
    leaders: dict[tuple[str, str], str | None],
) -> dict[tuple[int, int], str | None]:
    return {
        (int(chart.row), int(chart.column)): leaders.get((chart.song, chart.difficulty))
        for chart in charts
    }


def _standings_data_from_maps(
    totals: dict[tuple[str, str], dict[str, int]],
    player_bests: dict[tuple[str, str], dict[str, list[int]]],
) -> dict[tuple[str, str], tuple[dict[str, int], dict[str, list[int]]]]:
    keys = set(totals) | set(player_bests)
    empty_totals = {team: 0 for team in TEAM_ORDER}
    empty_bests = {team: [] for team in TEAM_ORDER}
    return {
        key: (
            totals.get(key, empty_totals),
            player_bests.get(key, empty_bests),
        )
        for key in keys
    }


def bingo_day_for_instant(
    *,
    start_time: datetime,
    day_count: int,
    moment: datetime,
) -> int:
    """1-based competition day containing ``moment``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    day_count = max(1, int(day_count))
    if moment < start_time:
        return 1
    elapsed_days = int((moment - start_time).total_seconds() // 86400)
    return max(1, min(day_count, elapsed_days + 1))


def compute_claim_point_impacts(
    *,
    charts: list[BingoChart],
    board_width: int,
    prev_totals: dict[tuple[str, str], dict[str, int]],
    prev_best_lists: dict[tuple[str, str], dict[str, list[int]]],
    new_totals: dict[tuple[str, str], dict[str, int]],
    new_best_lists: dict[tuple[str, str], dict[str, list[int]]],
    day: int,
    day_count: int,
) -> tuple[tuple[str, int], ...]:
    """Per-team point deltas from a square claim, ordered for display."""
    prev_scores = score_board_state(
        charts=charts,
        standings_data=_standings_data_from_maps(prev_totals, prev_best_lists),
        board_width=board_width,
        day=day,
        day_count=day_count,
    )
    new_scores = score_board_state(
        charts=charts,
        standings_data=_standings_data_from_maps(new_totals, new_best_lists),
        board_width=board_width,
        day=day,
        day_count=day_count,
    )
    deltas: dict[str, int] = {}
    for team in TEAM_ORDER:
        delta = int(new_scores[team].points) - int(prev_scores[team].points)
        if delta != 0:
            deltas[team] = delta

    team_rank = {team: index for index, team in enumerate(TEAM_ORDER)}
    gainers = sorted(
        [(team, delta) for team, delta in deltas.items() if delta > 0],
        key=lambda item: (-item[1], team_rank.get(item[0], 99)),
    )
    losers = sorted(
        [(team, delta) for team, delta in deltas.items() if delta < 0],
        key=lambda item: (item[1], team_rank.get(item[0], 99)),
    )
    return tuple(gainers + losers)


def _run_keys_for_cell(
    runs: list[tuple[str, list[tuple[int, int]], str, str]],
    *,
    row: int,
    column: int,
    team: str,
) -> tuple[set[tuple], set[tuple]]:
    """Return (bingo_keys, four_keys) for runs owned by team that include the cell."""
    cell = (int(row), int(column))
    bingos: set[tuple] = set()
    fours: set[tuple] = set()
    for orientation, coords, run_team, style in runs:
        if run_team != team or cell not in coords:
            continue
        key = (orientation, tuple(coords), style)
        if style == "solid":
            bingos.add(key)
        elif style == "dashed":
            fours.add(key)
    return bingos, fours


def load_bingo_square_claim_feed(
    *,
    start_time: datetime | None,
    charts: list[BingoChart] | None = None,
    board_width: int | None = None,
    limit: int = 40,
    db_url: str | None = None,
) -> list[BingoSquareClaimEvent]:
    """Replay bingo_scores chronologically and emit square claim / flip events.

    An event is recorded when a score causes a square's leading team to change
    from uncontested → a team, or from one team → another. Events also note
    when that claim newly forms a bingo, 4-in-a-row, or group capture.
    """
    if start_time is None or limit <= 0:
        return []

    settings = load_bingo_settings(db_url)
    if board_width is None:
        board_width = int(settings.board_width) if settings is not None else 5
    day_count = (
        max(1, int(settings.day_count))
        if settings is not None and settings.day_count is not None
        else 1
    )

    board_charts = charts if charts is not None else load_bingo_charts(db_url)
    board_charts = bingo_charts_on_board(board_charts, int(board_width))
    chart_by_key = {
        (chart.song, chart.difficulty): chart for chart in board_charts
    }
    if not chart_by_key:
        return []

    max_row = max(chart.row for chart in board_charts)
    max_col = max(chart.column for chart in board_charts)
    width = max(1, int(board_width))
    rows = max(width, max_row + 1)
    cols = max(width, max_col + 1)

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        player_id,
                        display_name,
                        team,
                        song,
                        difficulty,
                        score,
                        created_at
                    FROM bingo_scores
                    WHERE created_at >= %s
                    ORDER BY created_at ASC, score ASC, player_id ASC
                    """,
                    (start_time,),
                )
                score_rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        return []

    # chart_key -> player_id -> (team, best_score)
    bests_by_chart: dict[tuple[str, str], dict[str, tuple[str, int]]] = {
        key: {} for key in chart_by_key
    }
    leaders: dict[tuple[str, str], str | None] = {key: None for key in chart_by_key}
    events: list[BingoSquareClaimEvent] = []

    for row in score_rows:
        key = (str(row["song"]), str(row["difficulty"]))
        chart = chart_by_key.get(key)
        if chart is None:
            continue

        player_id = str(row["player_id"])
        team = str(row["team"])
        score = int(row["score"])
        player_bests = bests_by_chart[key]
        previous = player_bests.get(player_id)
        if previous is not None and score <= previous[1]:
            continue

        # Snapshot achievements before this score lands.
        prev_coord_leaders = _leaders_by_coord_from_charts(board_charts, leaders)
        prev_runs = find_bingo_runs(prev_coord_leaders, rows=rows, cols=cols)
        prev_bingos, prev_fours = _run_keys_for_cell(
            prev_runs,
            row=chart.row,
            column=chart.column,
            team=team,
        )
        prev_totals, prev_best_lists = _standings_maps_from_player_bests(bests_by_chart)
        prev_groups = group_claim_owners(board_charts, prev_totals, prev_best_lists)
        prev_group_owner = (
            prev_groups.get(int(chart.group)) if chart.group is not None else None
        )

        player_bests[player_id] = (team, score)
        prev_leader = leaders[key]
        new_leader = _leader_for_chart_bests(player_bests)
        leaders[key] = new_leader

        if new_leader is None or new_leader == prev_leader:
            continue
        # Only count when the scoring team becomes the new leader.
        if new_leader != team:
            continue

        new_coord_leaders = _leaders_by_coord_from_charts(board_charts, leaders)
        new_runs = find_bingo_runs(new_coord_leaders, rows=rows, cols=cols)
        new_bingos, new_fours = _run_keys_for_cell(
            new_runs,
            row=chart.row,
            column=chart.column,
            team=team,
        )
        new_totals, new_best_lists = _standings_maps_from_player_bests(bests_by_chart)
        new_groups = group_claim_owners(board_charts, new_totals, new_best_lists)
        new_group_owner = (
            new_groups.get(int(chart.group)) if chart.group is not None else None
        )

        created_at = row["created_at"]
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        claim_day = bingo_day_for_instant(
            start_time=start_time,
            day_count=day_count,
            moment=created_at,
        )
        point_impacts = compute_claim_point_impacts(
            charts=board_charts,
            board_width=width,
            prev_totals=prev_totals,
            prev_best_lists=prev_best_lists,
            new_totals=new_totals,
            new_best_lists=new_best_lists,
            day=claim_day,
            day_count=day_count,
        )

        events.append(
            BingoSquareClaimEvent(
                song=chart.song,
                difficulty=chart.difficulty,
                chart_display_name=chart.display_name,
                level=chart.level,
                row=int(chart.row),
                column=int(chart.column),
                team=new_leader,
                prev_team=prev_leader,
                player_id=player_id,
                player_display_name=str(row["display_name"]),
                score=score,
                created_at=created_at,
                formed_bingo=bool(new_bingos - prev_bingos),
                formed_four=bool(new_fours - prev_fours),
                captured_group=(
                    chart.group is not None
                    and new_group_owner == team
                    and prev_group_owner != team
                ),
                point_impacts=point_impacts,
            )
        )

    events.reverse()
    return events[:limit]


def bingo_charts_on_board(
    charts: list[BingoChart],
    board_width: int,
) -> list[BingoChart]:
    """Charts inside the configured board_width × board_width grid."""
    width = max(1, int(board_width))
    return [
        chart
        for chart in charts
        if 0 <= int(chart.row) < width and 0 <= int(chart.column) < width
    ]


def load_bingo_player_chart_best(
    *,
    player_id: str,
    song: str,
    difficulty: str,
    start_time: datetime | None,
    db_url: str | None = None,
) -> int | None:
    """Best bingo score for one player on one chart since competition start."""
    if start_time is None:
        return None
    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT MAX(score)::BIGINT AS best_score
                    FROM bingo_scores
                    WHERE player_id = %s
                      AND song = %s
                      AND difficulty = %s
                      AND created_at >= %s
                    """,
                    (player_id, song, difficulty, start_time),
                )
                row = cur.fetchone()
    except psycopg2.errors.UndefinedTable:
        return None
    if row is None or row["best_score"] is None:
        return None
    return int(row["best_score"])


def submit_bingo_score(
    *,
    player_id: str,
    song: str,
    difficulty: str,
    score: int,
    source: str | None = None,
    require_live: bool = False,
    accuracy: float | None = None,
    critical: int | None = None,
    perfect: int | None = None,
    great: int | None = None,
    good: int | None = None,
    okay: int | None = None,
    barely: int | None = None,
    miss: int | None = None,
    db_url: str | None = None,
) -> tuple[bool, str]:
    """Insert a bingo score if it beats the player's current best since event start.

    Returns (success, message).
    """
    from rating.constants import SCORE_SOURCE_IN_GAME, SCORE_SOURCE_SUBMISSION

    score_source = source or SCORE_SOURCE_SUBMISSION
    if score_source not in {SCORE_SOURCE_SUBMISSION, SCORE_SOURCE_IN_GAME}:
        return False, "Invalid score source."

    try:
        score_value = int(score)
    except (TypeError, ValueError):
        return False, "Score must be a whole number."
    if score_value <= 0:
        return False, "Score must be greater than zero."

    chart_max = bingo_chart_max_score(song, difficulty)
    if chart_max is not None and score_value > chart_max:
        return (
            False,
            f"Score cannot exceed the chart max ({format_leader_score(chart_max)}).",
        )

    settings = load_bingo_settings(db_url)
    if settings is None:
        return False, "Bingo settings are not available."
    if settings.start_time is None:
        return False, "Bingo has not started yet."

    if require_live:
        if settings.day_count is None:
            return False, "Bingo competition is not configured."
        if (
            bingo_in_progress_day(
                start_time=settings.start_time,
                day_count=settings.day_count,
            )
            is None
        ):
            return False, "Bingo competition is not live."

    charts = bingo_charts_on_board(load_bingo_charts(db_url), settings.board_width)
    chart = next(
        (
            item
            for item in charts
            if item.song == song and item.difficulty == difficulty
        ),
        None,
    )
    if chart is None:
        return False, "That chart is not on the current Bingo board."

    try:
        with _connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT player_id, display_name, team
                    FROM bingo_teams
                    WHERE player_id = %s
                    """,
                    (player_id,),
                )
                player = cur.fetchone()
                if player is None:
                    return False, "That player is not on a Bingo team."

                cur.execute(
                    """
                    SELECT MAX(score)::BIGINT AS best_score
                    FROM bingo_scores
                    WHERE player_id = %s
                      AND song = %s
                      AND difficulty = %s
                      AND created_at >= %s
                    """,
                    (player_id, song, difficulty, settings.start_time),
                )
                best_row = cur.fetchone()
                current_best = (
                    int(best_row["best_score"])
                    if best_row is not None and best_row["best_score"] is not None
                    else None
                )
                if current_best is not None and score_value <= current_best:
                    return (
                        False,
                        f"Score must be higher than the current best "
                        f"({format_leader_score(current_best)}).",
                    )

                cur.execute(
                    """
                    INSERT INTO bingo_scores (
                        player_id, display_name, team, song, difficulty,
                        score, accuracy, critical, perfect, great, good, okay,
                        barely, miss, source
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        player["player_id"],
                        player["display_name"],
                        player["team"],
                        song,
                        difficulty,
                        score_value,
                        accuracy,
                        critical,
                        perfect,
                        great,
                        good,
                        okay,
                        barely,
                        miss,
                        score_source,
                    ),
                )
            conn.commit()
    except psycopg2.errors.UndefinedTable:
        return False, "Bingo tables are not available."
    except Exception as exc:
        return False, f"Could not save score: {exc}"

    return (
        True,
        f"Saved {format_leader_score(score_value)} for {player['display_name']} "
        f"on {chart.display_name}.",
    )


def _optional_int(value: object, field: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"{field} must be a whole number."


def _optional_float(value: object, field: str) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, f"{field} must be a number."


def process_bingo_mod_submission(payload: dict[str, object]) -> tuple[bool, str]:
    """Validate and persist one Bingo chart score from the game mod API."""
    from rating.constants import SCORE_SOURCE_IN_GAME

    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        return False, "player_id is required."

    song = str(payload.get("song", "")).strip()
    difficulty = str(payload.get("difficulty", "")).strip()
    if not song or not difficulty:
        return False, "song and difficulty are required."

    if "score" not in payload or payload["score"] is None:
        return False, "score is required."

    try:
        score_value = int(payload["score"])
    except (TypeError, ValueError):
        return False, "Score must be a whole number."

    accuracy, accuracy_error = _optional_float(payload.get("accuracy"), "accuracy")
    if accuracy_error:
        return False, accuracy_error

    judgement_fields: dict[str, int | None] = {}
    for field in ("critical", "perfect", "great", "good", "okay", "barely", "miss"):
        value, error = _optional_int(payload.get(field), field)
        if error:
            return False, error
        judgement_fields[field] = value

    return submit_bingo_score(
        player_id=player_id,
        song=song,
        difficulty=difficulty,
        score=score_value,
        source=SCORE_SOURCE_IN_GAME,
        require_live=True,
        accuracy=accuracy,
        **judgement_fields,
    )


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


def bingo_chart_max_score(song: str, difficulty: str) -> int | None:
    """Absolute max score for a chart from ArcadeMaxScores (critical max)."""
    from rating.constants import DEFAULT_MAX_SCORES_PATH
    from rating.data import load_critical_max_scores
    from rating.imported_players import resolve_max_score_chart_key

    max_scores = load_critical_max_scores(DEFAULT_MAX_SCORES_PATH)
    chart_key = resolve_max_score_chart_key(song, difficulty, max_scores)
    if chart_key is None:
        return None
    return int(max_scores[chart_key])


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


def bingo_in_progress_day(
    *,
    start_time: datetime | None,
    day_count: int | None,
    now: datetime | None = None,
) -> int | None:
    """1-based day currently underway, or None before start / after final day."""
    if start_time is None or day_count is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if current < start_time:
        return None
    finished = completed_bingo_days(
        start_time=start_time,
        day_count=int(day_count),
        now=current,
    )
    total_days = max(1, int(day_count))
    if finished >= total_days:
        return None
    return finished + 1


def bingo_has_started(
    *,
    start_time: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True once the competition start time has been reached."""
    if start_time is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= start_time


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
    # In-progress day whose daily_points are provisional (shown grey); None if none.
    prospective_day: int | None = None


@dataclass(frozen=True)
class BingoFinalStandings:
    first: str
    second: str | None = None
    third: str | None = None


def _bingo_team_day_points(
    scoreboard: BingoScoreboard,
    team: str,
    *,
    day_index: int,
) -> int:
    points = scoreboard.daily_points.get(team, [])
    if day_index < 0 or day_index >= len(points):
        return 0
    value = points[day_index]
    return 0 if value is None else int(value)


def _order_tied_teams_by_daily_points(
    teams: list[str],
    *,
    scoreboard: BingoScoreboard,
    day_count: int,
) -> list[str]:
    """Break ties using final-day points first, then earlier days.

    Teams eliminated on a day are no longer considered on earlier days.
    Identical points on every day is a true tie (stable TEAM_ORDER fallback).
    """
    if len(teams) <= 1:
        return teams

    remaining = list(teams)
    for day_index in range(day_count - 1, -1, -1):
        scores = {
            team: _bingo_team_day_points(scoreboard, team, day_index=day_index)
            for team in remaining
        }
        max_score = max(scores.values())
        top_teams = [team for team in remaining if scores[team] == max_score]
        bottom_teams = [team for team in remaining if scores[team] < max_score]

        if bottom_teams:
            return (
                _order_tied_teams_by_daily_points(
                    top_teams, scoreboard=scoreboard, day_count=day_count
                )
                + _order_tied_teams_by_daily_points(
                    bottom_teams, scoreboard=scoreboard, day_count=day_count
                )
            )

        remaining = top_teams
        if day_index == 0 and len(remaining) > 1:
            return sorted(remaining, key=lambda team: TEAM_ORDER.index(team))

    return remaining


def compute_bingo_final_standings(
    *,
    scoreboard: BingoScoreboard,
) -> BingoFinalStandings | None:
    """Return 1st/2nd/3rd after all days finish, with daily-point tiebreaks."""
    day_count = max(1, int(scoreboard.day_count))
    if int(scoreboard.completed_days) < day_count:
        return None

    max_total = max(int(scoreboard.totals.get(team, 0)) for team in TEAM_ORDER)
    if max_total <= 0:
        return None

    groups: dict[int, list[str]] = {}
    for team in TEAM_ORDER:
        total = int(scoreboard.totals.get(team, 0))
        groups.setdefault(total, []).append(team)

    ordered: list[str] = []
    for total in sorted(groups.keys(), reverse=True):
        group = groups[total]
        ordered.extend(
            _order_tied_teams_by_daily_points(
                group,
                scoreboard=scoreboard,
                day_count=day_count,
            )
        )

    if not ordered:
        return None

    return BingoFinalStandings(
        first=ordered[0],
        second=ordered[1] if len(ordered) > 1 else None,
        third=ordered[2] if len(ordered) > 2 else None,
    )


def compute_bingo_winner(
    *,
    scoreboard: BingoScoreboard,
) -> str | None:
    """Return the winning team after all competition days finish."""
    standings = compute_bingo_final_standings(scoreboard=scoreboard)
    return standings.first if standings else None


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
    in_progress = bingo_in_progress_day(
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

    if in_progress is not None:
        live_standings = load_bingo_chart_standings_data(
            start_time=settings.start_time,
            end_time=None,
            db_url=db_url,
        )
        live_scores = score_board_state(
            charts=charts,
            standings_data=live_standings,
            board_width=int(settings.board_width),
            day=in_progress,
            day_count=day_count,
        )
        for team in TEAM_ORDER:
            daily_points[team][in_progress - 1] = int(live_scores[team].points)

    return BingoScoreboard(
        day_count=day_count,
        completed_days=finished,
        daily_points=daily_points,
        totals=totals,
        prospective_day=in_progress,
    )



def seed_bingo_test_scores(
    *,
    score_min: int = 1_500_000,
    score_max: int = 1_800_000,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
    db_url: str | None = None,
) -> int:
    """Insert one random score per player per chart with random created_at in a window."""
    import random

    settings = load_bingo_settings(db_url)
    if settings is None:
        raise RuntimeError("bingo_settings are required to seed scores.")

    start = time_start if time_start is not None else settings.start_time
    if start is None:
        raise RuntimeError("bingo_settings.start_time is required to seed scores.")
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    end = time_end if time_end is not None else datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise RuntimeError("time_end must be after the seed window start.")

    time_span = max(1, int((end - start).total_seconds()) - 1)
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
                    created_at = start + timedelta(
                        seconds=random.randint(0, time_span)
                    )
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
    """Clear scores and insert rising random scores across each competition day.

    Day N scores are random in [1_000_000 + (N-1)*100_000, 1_100_000 + (N-1)*100_000]
    with created_at randomized throughout that competition day.

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
                day_start = start_time + timedelta(days=day - 1)
                day_span = max(
                    1,
                    int((bingo_day_end(start_time, day) - day_start).total_seconds()) - 1,
                )
                for player in players:
                    for chart in charts:
                        created_at = day_start + timedelta(
                            seconds=random.randint(0, day_span)
                        )
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
