"""Bingo Board UI for Streamlit."""

from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

from rating.bingo import (
    BingoCellStanding,
    BingoScoreboard,
    BingoSettings,
    BingoTeamPlayer,
    TEAM_ORDER,
    build_cell_standing,
    compute_bingo_scoreboard,
    find_bingo_runs,
    format_leader_score,
    format_score_diff,
    group_claim_owners,
    load_bingo_chart_standings_data,
    load_bingo_charts,
    load_bingo_settings,
    load_bingo_teams_by_ex_rating,
)
from rating.supabase_config import supabase_configured

# Slightly darker than the app background (#0c0e29).
BINGO_CELL_BG = "#07091a"
BINGO_PAGE_BG = "#0c0e29"
BINGO_DISPLAY_TZ = ZoneInfo("America/Los_Angeles")
TEAM_CELL_BACKGROUNDS = {
    "Eve": "#0f1f3a",
    "Grace": "#2a1218",
    "Rest": "#0f2418",
}
# Stroke color for completed bingo lines (row / column / diagonal).
TEAM_BINGO_LINE_COLORS = {
    "Eve": "#3a6aa8",
    "Grace": "#a84a56",
    "Rest": "#3a8a5e",
}
TEAM_TEXT_COLORS = {
    "Eve": "#6eb0ff",
    "Grace": "#ff7a84",
    "Rest": "#5ee09a",
}
# bingo_charts."group" → outline color (1=Yellow, 2=Cyan, 3=Purple).
GROUP_BORDER_COLORS = {
    1: "#f5d547",
    2: "#3dd9f0",
    3: "#c084fc",
}
DEFAULT_CELL_BORDER = "1px solid rgba(234, 234, 234, 0.16)"
GROUP_BORDER_WIDTH = "3px"
TEAM_CLAIM_BORDER_WIDTH = "3px"


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bingo_charts():
    return load_bingo_charts()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bingo_teams():
    return load_bingo_teams_by_ex_rating()


def _on_bingo_refresh() -> None:
    """Mark a manual refresh; scores always load live on each run."""
    st.session_state.bingo_last_updated = time.time()
    _cached_bingo_charts.clear()
    _cached_bingo_teams.clear()


def _difficulty_label(difficulty: str, level: int | None) -> str:
    diff = difficulty.upper()
    if level is None:
        return f"[{diff}]"
    return f"[{diff} - {level}]"


def _team_label(team: str) -> str:
    return team.upper()


def _ordinal_day(day: int) -> str:
    if 11 <= (day % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _format_bingo_updated_ago(updated_at: float, *, now: float | None = None) -> str:
    elapsed = max(0, int((now if now is not None else time.time()) - updated_at))
    if elapsed < 60:
        unit = "Second" if elapsed == 1 else "Seconds"
        return f"{elapsed} {unit} ago"
    minutes = elapsed // 60
    if minutes < 60:
        unit = "Minute" if minutes == 1 else "Minutes"
        return f"{minutes} {unit} ago"
    hours = minutes // 60
    unit = "Hour" if hours == 1 else "Hours"
    return f"{hours} {unit} ago"


def _render_bingo_board_toolbar() -> None:
    if "bingo_last_updated" not in st.session_state:
        st.session_state.bingo_last_updated = time.time()
    updated_ms = int(float(st.session_state.bingo_last_updated) * 1000)

    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker) {
            width: min(100%, 1100px);
            margin: 0.05rem auto 0.2rem !important;
            padding: 0 !important;
            align-items: center !important;
            gap: 0.5rem !important;
        }
        div[data-testid="stElementContainer"]:has(.bingo-toolbar-marker),
        div[data-testid="element-container"]:has(.bingo-toolbar-marker) {
            margin-bottom: 0.2rem !important;
            padding-bottom: 0 !important;
        }
        div[data-testid="stElementContainer"]:has(.bingo-board-shell),
        div[data-testid="element-container"]:has(.bingo-board-shell) {
            margin-top: 0 !important;
            padding-top: 0 !important;
        }
        .bingo-board-shell {
            margin-top: -0.4rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"] {
            padding: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        .element-container,
        div[data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="stElementContainer"] {
            margin: 0 !important;
            padding: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="stCustomComponentV1"] {
            margin: 0 !important;
            padding: 0 !important;
            height: 1.7rem !important;
        }
        .st-key-bingo_refresh_row,
        .st-key-bingo-refresh-row {
            width: fit-content !important;
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_refresh_row [data-testid="stHorizontalBlock"],
        .st-key-bingo-refresh-row [data-testid="stHorizontalBlock"] {
            align-items: center !important;
            gap: 0.45rem !important;
            margin: 0 !important;
        }
        .st-key-bingo_refresh_board,
        .st-key-bingo-refresh-board {
            width: fit-content !important;
            min-width: 0 !important;
            flex: 0 0 auto !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_refresh_board [data-testid="stButton"],
        .st-key-bingo-refresh-board [data-testid="stButton"] {
            width: auto !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_refresh_board button,
        .st-key-bingo-refresh-board button {
            background-color: #008f68 !important;
            border-color: #008f68 !important;
            color: #ffffff !important;
            width: 1.7rem !important;
            height: 1.7rem !important;
            min-width: 1.7rem !important;
            min-height: 1.7rem !important;
            max-width: 1.7rem !important;
            max-height: 1.7rem !important;
            padding: 0 !important;
            margin: 0 !important;
            border-radius: 999px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            line-height: 1 !important;
            gap: 0 !important;
        }
        .st-key-bingo_refresh_board button:hover,
        .st-key-bingo-refresh-board button:hover {
            background-color: #007a58 !important;
            border-color: #007a58 !important;
        }
        .st-key-bingo_refresh_board button [data-testid="stIconMaterial"],
        .st-key-bingo-refresh-board button [data-testid="stIconMaterial"],
        .st-key-bingo_refresh_board button span,
        .st-key-bingo-refresh-board button span {
            font-size: 1.15rem !important;
            line-height: 1 !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_refresh_board button svg,
        .st-key-bingo-refresh-board button svg {
            width: 1.15rem !important;
            height: 1.15rem !important;
        }
        .st-key-bingo_last_updated,
        .st-key-bingo-last-updated {
            width: auto !important;
            min-width: 0 !important;
            flex: 1 1 auto !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        .st-key-bingo_last_updated iframe,
        .st-key-bingo-last-updated iframe {
            width: min(100%, 360px) !important;
            max-width: 360px !important;
            height: 1.7rem !important;
        }
        .bingo-board-controls-toolbar {
            padding-bottom: 0.8rem !important;
            margin: 0 !important;
            min-height: 1.7rem;
        }
        .bingo-toolbar-marker { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.15, 1.35], gap="small")
    with left:
        st.markdown(
            '<span class="bingo-toolbar-marker"></span>',
            unsafe_allow_html=True,
        )
        with st.container(horizontal=True, gap="xsmall", key="bingo_refresh_row"):
            st.button(
                "",
                key="bingo_refresh_board",
                type="primary",
                icon=":material/refresh:",
                help="Refresh board",
                on_click=_on_bingo_refresh,
            )
            with st.container(key="bingo_last_updated"):
                components.html(
                    f"""
                    <div class="bingo-last-updated" id="bingo-last-updated"></div>
                    <style>
                      html, body {{
                        margin: 0;
                        padding: 0;
                        background: transparent !important;
                        overflow: visible;
                      }}
                      .bingo-last-updated {{
                        display: flex;
                        align-items: center;
                        height: 1.7rem;
                        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
                        font-size: 1.15rem;
                        font-weight: 600;
                        color: rgba(200, 205, 215, 0.88);
                        white-space: nowrap;
                        overflow: visible;
                      }}
                    </style>
                    <script>
                      const updatedMs = {updated_ms};
                      const labelEl = document.getElementById("bingo-last-updated");
                      function formatAgo(ms) {{
                        const seconds = Math.max(0, Math.floor((Date.now() - ms) / 1000));
                        if (seconds < 30) {{
                          return "seconds ago";
                        }}
                        if (seconds < 60) {{
                          return "30 seconds ago";
                        }}
                        const minutes = Math.floor(seconds / 60);
                        if (minutes < 60) {{
                          return minutes === 1 ? "1 minute ago" : minutes + " minutes ago";
                        }}
                        const hours = Math.floor(minutes / 60);
                        return hours === 1 ? "1 hour ago" : hours + " hours ago";
                      }}
                      function tick() {{
                        labelEl.textContent = "Last Updated " + formatAgo(updatedMs);
                      }}
                      tick();
                      setInterval(tick, 1000);
                    </script>
                    """,
                    height=28,
                    width=360,
                )
    with right:
        st.markdown(
            """
            <div class="bingo-board-controls bingo-board-controls-toolbar">
              <label class="bingo-board-toggle-label">
                <input type="checkbox" class="bingo-board-toggle bingo-lines-toggle" />
                <span>Hide Bingo Lines</span>
              </label>
              <label class="bingo-board-toggle-label">
                <input type="checkbox" class="bingo-board-toggle bingo-simplified-toggle" />
                <span>Simplified Board</span>
              </label>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _format_bingo_schedule(settings: BingoSettings) -> str | None:
    if settings.start_time is None or settings.day_count is None:
        return None

    start_local = settings.start_time.astimezone(BINGO_DISPLAY_TZ)
    # Each day is a full 24h from start; display ends on the final minute of that window.
    end_local = start_local + timedelta(days=max(1, settings.day_count)) - timedelta(minutes=1)

    def _label(moment: datetime) -> str:
        return (
            f"{moment.strftime('%A')}, "
            f"{moment.strftime('%B')} {_ordinal_day(moment.day)} "
            f"@ {moment.strftime('%I:%M %p').removeprefix('0')} PDT"
        )

    return f"{_label(start_local)} - {_label(end_local)}"


def _render_bingo_countdown(settings: BingoSettings) -> None:
    if settings.start_time is None or settings.day_count is None:
        return

    start_utc = settings.start_time
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    start_ms = int(start_utc.timestamp() * 1000)
    day_count = max(1, int(settings.day_count))

    components.html(
        f"""
        <div class="bingo-countdown">
          <div class="bingo-countdown-label" id="bingo-countdown-label"></div>
          <div class="bingo-countdown-timer" id="bingo-countdown-timer"></div>
        </div>
        <style>
          html, body {{
            margin: 0;
            padding: 0;
            background: transparent !important;
            overflow: hidden;
          }}
          .bingo-countdown {{
            text-align: center;
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            color: #eaeaea;
            padding: 1.1rem 0 0 0;
          }}
          .bingo-countdown-label {{
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
            color: rgba(234, 234, 234, 0.92);
          }}
          .bingo-countdown-timer {{
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            font-variant-numeric: tabular-nums;
            color: #eaeaea;
            line-height: 1.2;
          }}
        </style>
        <script>
          const startMs = {start_ms};
          const dayCount = {day_count};
          const dayMs = 24 * 60 * 60 * 1000;
          const labelEl = document.getElementById("bingo-countdown-label");
          const timerEl = document.getElementById("bingo-countdown-timer");

          function pad(n) {{
            return String(n).padStart(2, "0");
          }}

          function formatRemaining(ms) {{
            const totalSeconds = Math.max(0, Math.floor(ms / 1000));
            const days = Math.floor(totalSeconds / 86400);
            const hours = Math.floor((totalSeconds % 86400) / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = totalSeconds % 60;
            return days + "d " + pad(hours) + "h " + pad(minutes) + "m " + pad(seconds) + "s";
          }}

          function tick() {{
            const now = Date.now();
            const gameEndMs = startMs + dayCount * dayMs;

            if (now < startMs) {{
              labelEl.textContent = "Game Starts:";
              timerEl.textContent = formatRemaining(startMs - now);
              return;
            }}

            if (now >= gameEndMs) {{
              labelEl.textContent = "Game Ended";
              timerEl.textContent = "0d 00h 00m 00s";
              return;
            }}

            const dayIndex = Math.floor((now - startMs) / dayMs) + 1;
            const dayEndMs = startMs + dayIndex * dayMs;
            if (dayIndex >= dayCount) {{
              labelEl.textContent = "Final Day Ends:";
            }} else {{
              labelEl.textContent = "Day " + dayIndex + " / " + dayCount + " Ends:";
            }}
            timerEl.textContent = formatRemaining(dayEndMs - now);
          }}

          tick();
          setInterval(tick, 1000);
        </script>
        """,
        height=78,
    )


def _render_bingo_header(settings: BingoSettings) -> None:
    schedule = _format_bingo_schedule(settings)
    schedule_html = (
        f'<div class="bingo-header-schedule">{html.escape(schedule)}</div>'
        if schedule
        else ""
    )
    st.markdown(
        f"""
        <style>
        .bingo-header {{
            text-align: center;
            margin: 0.15rem 0 0 0;
        }}
        .bingo-header-title {{
            margin: 0 0 0.35rem 0;
            font-size: 2.4rem;
            font-weight: 800;
            line-height: 1.15;
            color: #eaeaea;
            text-decoration: underline;
            text-underline-offset: 0.14em;
        }}
        .bingo-header-schedule {{
            margin-top: 0.85rem;
            font-size: 1.05rem;
            font-weight: 600;
            color: rgba(234, 234, 234, 0.88);
            line-height: 1.35;
        }}
        </style>
        <div class="bingo-header">
            <div class="bingo-header-title">UNBEATABLE Bingo</div>
            {schedule_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_bingo_countdown(settings)


def _cell_background(standing: BingoCellStanding) -> str:
    if standing.leader is None:
        return BINGO_CELL_BG
    return TEAM_CELL_BACKGROUNDS.get(standing.leader, BINGO_CELL_BG)


def _bingo_line_segments_by_cell(
    leaders_by_coord: dict[tuple[int, int], str | None],
    *,
    rows: int,
    cols: int,
) -> dict[tuple[int, int], list[tuple[str, str, str]]]:
    """Map cell -> list of (orientation, team, style) for bingo / near-bingo lines."""
    segments: dict[tuple[int, int], list[tuple[str, str, str]]] = {}
    for orientation, coords, team, style in find_bingo_runs(
        leaders_by_coord, rows=rows, cols=cols
    ):
        for coord in coords:
            segments.setdefault(coord, []).append((orientation, team, style))
    return segments


def _bingo_line_svg_html(segments: list[tuple[str, str, str]]) -> str:
    if not segments:
        return ""

    lines: list[str] = []
    for orientation, team, style in segments:
        color = TEAM_BINGO_LINE_COLORS.get(team, "#eaeaea")
        if orientation == "h":
            x1, y1, x2, y2 = "0", "0.5", "1", "0.5"
        elif orientation == "v":
            x1, y1, x2, y2 = "0.5", "0", "0.5", "1"
        elif orientation == "d":
            x1, y1, x2, y2 = "0", "0", "1", "1"
        else:  # anti-diagonal
            x1, y1, x2, y2 = "1", "0", "0", "1"
        dash = ' stroke-dasharray="10 8"' if style == "dashed" else ""
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="6" stroke-linecap="butt" '
            f'vector-effect="non-scaling-stroke"{dash} />'
        )
    return (
        '<svg class="bingo-line-svg" viewBox="0 0 1 1" preserveAspectRatio="none" '
        'aria-hidden="true">'
        f'{"".join(lines)}'
        "</svg>"
    )


def _leader_block_html(standing: BingoCellStanding) -> str:
    if standing.leader is None:
        return '<div class="bingo-cell-status">Not Contested</div>'

    color = TEAM_TEXT_COLORS.get(standing.leader, "#eaeaea")
    team_text = f"Team {html.escape(_team_label(standing.leader))}"
    score_text = html.escape(format_leader_score(standing.leader_score))
    return (
        '<div class="bingo-cell-leader">'
        f'<div class="bingo-cell-leader-team" style="color:{color};">{team_text}</div>'
        f'<div class="bingo-cell-leader-score">{score_text}</div>'
        "</div>"
    )


def _trailers_block_html(standing: BingoCellStanding) -> str:
    if standing.leader is None and standing.leader_score <= 0:
        trailers: list[tuple[str, int]] = []
    else:
        trailers = list(standing.trailers[:2])

    while len(trailers) < 2:
        trailers.append(("", 0))

    parts: list[str] = []
    for index, (team, diff) in enumerate(trailers):
        split_class = " bingo-cell-trailer-split" if index else ""
        if team:
            team_color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
            label = html.escape(format_score_diff(diff))
        else:
            team_color = "transparent"
            label = "&nbsp;"
        parts.append(
            f'<div class="bingo-cell-trailer{split_class}" style="color:{team_color};">'
            f"{label}</div>"
        )
    return f'<div class="bingo-cell-trailers">{"".join(parts)}</div>'


def _cell_border_css(
    row: int,
    col: int,
    group: int | None,
    groups_by_coord: dict[tuple[int, int], int | None],
) -> str:
    """Colored group outline on outer edges; keep normal grid lines between same-group cells."""
    if group is None:
        return f"border:{DEFAULT_CELL_BORDER};"

    color = GROUP_BORDER_COLORS.get(group)
    if color is None:
        return f"border:{DEFAULT_CELL_BORDER};"

    edge = f"{GROUP_BORDER_WIDTH} solid {color}"

    def same_group(nr: int, nc: int) -> bool:
        return groups_by_coord.get((nr, nc)) == group

    # Same-group neighbors keep the default grid border (not the group color).
    top = DEFAULT_CELL_BORDER if same_group(row - 1, col) else edge
    right = DEFAULT_CELL_BORDER if same_group(row, col + 1) else edge
    bottom = DEFAULT_CELL_BORDER if same_group(row + 1, col) else edge
    left = DEFAULT_CELL_BORDER if same_group(row, col - 1) else edge
    return (
        f"border-top:{top};border-right:{right};"
        f"border-bottom:{bottom};border-left:{left};"
    )


def _group_claim_owners(
    charts: list,
    totals: dict,
    player_bests: dict,
) -> dict[int, str]:
    """Return {group_id: team} when that team leads every chart in the group."""
    return group_claim_owners(charts, totals, player_bests)

def _claim_outline_html(
    row: int,
    col: int,
    group: int | None,
    groups_by_coord: dict[tuple[int, int], int | None],
    claim_team: str | None,
) -> str:
    """Inner team-colored outline when a team owns the whole group."""
    if group is None or claim_team is None:
        return ""
    color = TEAM_TEXT_COLORS.get(claim_team)
    if color is None:
        return ""

    edge = f"{TEAM_CLAIM_BORDER_WIDTH} solid {color}"

    def same_group(nr: int, nc: int) -> bool:
        return groups_by_coord.get((nr, nc)) == group

    top = "none" if same_group(row - 1, col) else edge
    right = "none" if same_group(row, col + 1) else edge
    bottom = "none" if same_group(row + 1, col) else edge
    left = "none" if same_group(row, col - 1) else edge
    return (
        '<div class="bingo-cell-claim-outline" style="'
        f"border-top:{top};border-right:{right};"
        f"border-bottom:{bottom};border-left:{left};"
        '"></div>'
    )


def _render_cell_html(
    standing: BingoCellStanding,
    *,
    groups_by_coord: dict[tuple[int, int], int | None],
    claim_team: str | None = None,
    bingo_segments: list[tuple[str, str, str]] | None = None,
) -> str:
    chart = standing.chart
    song = html.escape(chart.display_name)
    difficulty = html.escape(_difficulty_label(chart.difficulty, chart.level))
    cell_bg = _cell_background(standing)
    border_css = _cell_border_css(chart.row, chart.column, chart.group, groups_by_coord)
    claim_html = _claim_outline_html(
        chart.row,
        chart.column,
        chart.group,
        groups_by_coord,
        claim_team,
    )
    line_html = _bingo_line_svg_html(bingo_segments or [])
    return (
        f'<div class="bingo-cell" style="--bingo-cell-bg:{cell_bg};{border_css}">'
        f"{line_html}"
        f"{claim_html}"
        '<div class="bingo-cell-top">'
        f'<div class="bingo-cell-song">{song}</div>'
        f'<div class="bingo-cell-diff">{difficulty}</div>'
        "</div>"
        f'<div class="bingo-cell-mid">{_leader_block_html(standing)}</div>'
        f'<div class="bingo-cell-bot">{_trailers_block_html(standing)}</div>'
        "</div>"
    )


def build_bingo_board_css() -> str:
    return f"""
    <style>
    /* Keep custom HTML components (countdown / teams) full-width so content can center. */
    div[data-testid="stCustomComponentV1"] {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    div[data-testid="stCustomComponentV1"] iframe {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    .bingo-board-shell {{
        width: min(100%, 1100px);
        margin: -0.4rem auto 0;
    }}
    .bingo-board-controls {{
        display: flex;
        flex-direction: row;
        justify-content: flex-end;
        align-items: center;
        gap: 2rem;
        margin: 0;
        padding: 0 0 0.8rem 0;
    }}
    .bingo-board-controls-toolbar {{
        padding: 0 0 0.8rem 0 !important;
        margin: 0 !important;
        width: 100%;
        min-height: 1.7rem;
    }}
    .bingo-board-toggle-label {{
        display: inline-flex;
        align-items: center;
        gap: 0.6rem;
        cursor: pointer;
        user-select: none;
        font-size: 1.28rem;
        font-weight: 700;
        color: rgba(234, 234, 234, 0.95);
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
        line-height: 1.15;
    }}
    .bingo-board-toggle {{
        width: 1.4rem;
        height: 1.4rem;
        accent-color: #6eb0ff;
        cursor: pointer;
        margin: 0;
        flex-shrink: 0;
    }}
    [data-testid="stAppViewContainer"]:has(.bingo-lines-toggle:checked) .bingo-line-svg {{
        display: none !important;
    }}
    [data-testid="stAppViewContainer"]:has(.bingo-simplified-toggle:checked) .bingo-cell-mid,
    [data-testid="stAppViewContainer"]:has(.bingo-simplified-toggle:checked) .bingo-cell-bot {{
        display: none !important;
    }}
    [data-testid="stAppViewContainer"]:has(.bingo-simplified-toggle:checked) .bingo-cell {{
        justify-content: center;
        align-items: center;
    }}
    [data-testid="stAppViewContainer"]:has(.bingo-simplified-toggle:checked) .bingo-cell-top {{
        padding-bottom: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        flex: 1 1 auto;
        width: 100%;
    }}
    [data-testid="stAppViewContainer"]:has(.bingo-simplified-toggle:checked) .bingo-cell-song {{
        font-size: 1.05rem;
    }}
    [data-testid="stAppViewContainer"]:has(.bingo-simplified-toggle:checked) .bingo-cell-diff {{
        font-size: 0.95rem;
        margin-top: 0.25rem;
    }}
    .bingo-board-wrap {{
        width: 100%;
        overflow-x: auto;
        padding-bottom: 2rem;
    }}
    .bingo-board {{
        display: grid;
        gap: 0;
        width: 100%;
        margin: 0;
        border: 1px solid rgba(234, 234, 234, 0.22);
        background: {BINGO_PAGE_BG};
        align-items: stretch;
    }}
    .bingo-cell {{
        --bingo-cell-bg: {BINGO_CELL_BG};
        position: relative;
        background: var(--bingo-cell-bg);
        color: #eaeaea;
        text-align: center;
        padding: 0.6rem 0.4rem 0.55rem;
        min-height: 12.75rem;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-sizing: border-box;
        border: none;
        overflow: hidden;
    }}
    .bingo-cell-claim-outline {{
        position: absolute;
        inset: 0;
        z-index: 5;
        pointer-events: none;
        box-sizing: border-box;
    }}
    .bingo-line-svg {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        z-index: 3;
        pointer-events: none;
        overflow: visible;
    }}
    .bingo-cell-empty {{
        border: {DEFAULT_CELL_BORDER};
    }}
    .bingo-cell-top {{
        position: relative;
        z-index: 4;
        background: transparent;
        padding-bottom: 3.55rem;
    }}
    .bingo-cell-bot {{
        position: relative;
        z-index: 4;
        background: transparent;
        padding-top: 3.55rem;
    }}
    .bingo-cell-mid {{
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        z-index: 4;
        pointer-events: none;
        background: transparent;
    }}
    .bingo-cell-song {{
        font-size: 0.95rem;
        font-weight: 700;
        line-height: 1.15;
        width: 100%;
        color: #eaeaea;
    }}
    .bingo-cell-diff {{
        font-size: 0.88rem;
        font-weight: 600;
        line-height: 1.15;
        width: 100%;
        margin-top: 0.1rem;
        color: rgba(234, 234, 234, 0.82);
    }}
    .bingo-cell-leader {{
        font-weight: 800;
        line-height: 1.1;
        width: 100%;
        box-sizing: border-box;
        background: transparent;
        padding: 0.2rem 0.4rem;
    }}
    .bingo-cell-leader-team {{
        font-size: 1.05rem;
        display: inline-block;
        border-bottom: 1px solid currentColor;
        padding-bottom: 0.05em;
        line-height: 1.2;
    }}
    .bingo-cell-leader-score {{
        font-size: 1.15rem;
        margin-top: 0.35rem;
        color: #eaeaea;
    }}
    .bingo-cell-status {{
        font-size: 1rem;
        font-weight: 700;
        color: rgba(234, 234, 234, 0.55);
        width: 100%;
        box-sizing: border-box;
        background: var(--bingo-cell-bg);
        padding: 0.2rem 0.4rem;
    }}
    .bingo-cell-trailers {{
        display: flex;
        align-items: stretch;
        justify-content: center;
        min-height: 1.45rem;
        width: 100%;
        border-top: 1px solid rgba(234, 234, 234, 0.28);
        padding-top: 0.2rem;
    }}
    .bingo-cell-trailer {{
        flex: 1 1 0;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.05rem;
        font-weight: 700;
        padding: 0.05rem 0.15rem;
    }}
    .bingo-cell-trailer-split {{
        border-left: 1px solid rgba(234, 234, 234, 0.28);
    }}
    @media (max-width: 900px) {{
        .bingo-cell {{
            min-height: 11.25rem;
            padding: 0.45rem 0.25rem 0.4rem;
        }}
        .bingo-cell-top {{
            padding-bottom: 3rem;
        }}
        .bingo-cell-bot {{
            padding-top: 3rem;
        }}
        .bingo-cell-song {{
            font-size: 0.8rem;
        }}
        .bingo-cell-diff {{
            font-size: 0.74rem;
        }}
        .bingo-cell-leader-team {{
            font-size: 0.9rem;
        }}
        .bingo-cell-leader-score {{
            font-size: 1rem;
        }}
        .bingo-cell-trailer {{
            font-size: 0.9rem;
        }}
    }}
    </style>
    """


def _render_bingo_scoreboard(scoreboard: BingoScoreboard) -> None:
    day_headers = "".join(
        f'<th class="bingo-sb-day" scope="col">{day}</th>'
        for day in range(1, scoreboard.day_count + 1)
    )
    rows_html: list[str] = []
    # Slightly dimmer than board cell tints so the scoreboard stays subdued.
    scoreboard_row_bg = {
        "Eve": "#0c1528",
        "Grace": "#1a1016",
        "Rest": "#0c1814",
    }
    for team in TEAM_ORDER:
        color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
        row_bg = scoreboard_row_bg.get(team, BINGO_CELL_BG)
        cells = []
        for value in scoreboard.daily_points.get(team, []):
            if value is None:
                cells.append(
                    f'<td class="bingo-sb-score bingo-sb-blank" style="background:{row_bg};"></td>'
                )
            else:
                cells.append(
                    f'<td class="bingo-sb-score" style="background:{row_bg};">'
                    f"{html.escape(str(value))}</td>"
                )
        total = int(scoreboard.totals.get(team, 0))
        rows_html.append(
            "<tr>"
            f'<th class="bingo-sb-team" scope="row" style="color:{color};background:{row_bg};">'
            f"{html.escape(team.upper())}</th>"
            f'{"".join(cells)}'
            f'<td class="bingo-sb-total" style="background:{row_bg};">'
            f"{html.escape(str(total))}</td>"
            "</tr>"
        )

    st.markdown(
        f"""
        <style>
          .bingo-scoreboard-shell {{
            width: min(100%, 1100px);
            margin: 1.35rem auto 0.35rem;
            display: flex;
            justify-content: center;
          }}
          div[data-testid="stMarkdownContainer"]:has(.bingo-scoreboard-shell),
          div[data-testid="stElementContainer"]:has(.bingo-scoreboard-shell) {{
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
          }}
          div[data-testid="stMarkdownContainer"]:has(.bingo-scoreboard-shell) p {{
            margin: 0 !important;
            padding: 0 !important;
            min-height: 0 !important;
          }}
          .bingo-scoreboard-frame {{
            display: table;
            max-width: 100%;
            border: 1px solid rgba(234, 234, 234, 0.22);
            border-radius: 10px;
            overflow: hidden;
            background: transparent;
            padding: 0;
            margin: 0;
            line-height: normal;
          }}
          .bingo-scoreboard {{
            width: max-content;
            max-width: 100%;
            border-collapse: separate;
            border-spacing: 0 !important;
            table-layout: fixed;
            background: transparent;
            border: none !important;
            margin: 0 !important;
            padding: 0 !important;
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            color: rgba(234, 234, 234, 0.92);
          }}
          .bingo-scoreboard tr:last-child th,
          .bingo-scoreboard tr:last-child td {{
            padding-bottom: 0.55rem;
          }}
          .bingo-scoreboard th,
          .bingo-scoreboard td {{
            text-align: center;
            vertical-align: middle;
            padding: 0.55rem 0.2rem;
          }}
          .bingo-scoreboard thead th {{
            font-size: 0.95rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            color: rgba(234, 234, 234, 0.88);
            padding-top: 0.7rem;
            padding-bottom: 0.4rem;
            background: #080b22;
            border-bottom: 1px solid rgba(234, 234, 234, 0.18);
          }}
          .bingo-sb-team {{
            width: 6.25rem;
            text-align: left !important;
            padding-left: 0.85rem !important;
            font-size: 1.05rem;
            font-weight: 800;
            letter-spacing: 0.03em;
          }}
          .bingo-scoreboard thead .bingo-sb-team {{
            text-align: center !important;
            padding-left: 0.2rem !important;
            font-size: 0.95rem;
            letter-spacing: 0.04em;
          }}
          .bingo-sb-day-label {{
            color: rgba(234, 234, 234, 0.72) !important;
            font-weight: 700 !important;
            letter-spacing: 0.06em !important;
          }}
          .bingo-sb-day,
          .bingo-sb-score,
          .bingo-sb-runs,
          .bingo-sb-total {{
            width: 4.15rem;
            min-width: 4.15rem;
            max-width: 4.15rem;
            box-sizing: border-box;
          }}
          .bingo-sb-day,
          .bingo-sb-runs {{
            font-size: 0.95rem;
            font-weight: 800;
            letter-spacing: 0.04em;
          }}
          .bingo-sb-runs {{
            border-left: 1px solid rgba(234, 234, 234, 0.28);
            letter-spacing: 0.06em;
          }}
          .bingo-sb-score,
          .bingo-sb-total {{
            font-size: 1.12rem;
            font-weight: 800;
            line-height: 1.15;
            color: rgba(245, 245, 245, 0.96);
          }}
          .bingo-sb-blank {{
            min-height: 1.4rem;
          }}
          .bingo-sb-total {{
            border-left: 1px solid rgba(234, 234, 234, 0.28);
          }}
          @media (max-width: 700px) {{
            .bingo-sb-team {{
              width: 4.5rem;
              padding-left: 0.4rem !important;
              font-size: 0.85rem;
            }}
            .bingo-sb-day,
            .bingo-sb-score,
            .bingo-sb-runs,
            .bingo-sb-total {{
              width: 3rem;
              min-width: 3rem;
              max-width: 3rem;
              font-size: 0.85rem;
            }}
            .bingo-scoreboard thead th {{
              font-size: 0.75rem;
            }}
          }}
        </style>
        <div class="bingo-scoreboard-shell">
          <div class="bingo-scoreboard-frame">
            <table class="bingo-scoreboard" aria-label="Bingo daily points scoreboard">
              <thead>
                <tr>
                  <th class="bingo-sb-team bingo-sb-day-label" scope="col">Day</th>
                  {day_headers}
                  <th class="bingo-sb-runs" scope="col">TOTAL</th>
                </tr>
              </thead>
              <tbody>
                {"".join(rows_html)}
              </tbody>
            </table>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_bingo_teams(teams: dict[str, list[BingoTeamPlayer]]) -> None:
    columns: list[str] = []
    for index, team in enumerate(TEAM_ORDER):
        color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
        players = teams.get(team, [])
        names = "".join(
            f'<div class="bingo-team-player">{html.escape(player.display_name)}</div>'
            for player in players
        )
        columns.append(
            f'<div class="bingo-team-col bingo-team-col-{index}">'
            f'<div class="bingo-team-heading" style="color:{color};">'
            f"Team {html.escape(_team_label(team))}"
            "</div>"
            f'<div class="bingo-team-list">{names}</div>'
            "</div>"
        )

    # Use components.html so Streamlit theme CSS cannot override centering.
    components.html(
        f"""
        <div class="bingo-teams">{"".join(columns)}</div>
        <style>
          html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            background: transparent !important;
          }}
          .bingo-teams {{
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            column-gap: 0;
            align-items: stretch;
            width: 100%;
            margin: 0 auto;
            padding: 2.75rem 0 0.5rem 0;
            color: #eaeaea;
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            box-sizing: border-box;
          }}
          .bingo-team-col {{
            width: max-content;
            max-width: 100%;
            text-align: center;
          }}
          .bingo-team-col-0 {{
            justify-self: end;
            padding-right: 3.25rem;
          }}
          .bingo-team-col-1 {{
            justify-self: center;
            padding: 0 3.25rem;
            border-left: 1px solid rgba(234, 234, 234, 0.35);
            border-right: 1px solid rgba(234, 234, 234, 0.35);
          }}
          .bingo-team-col-2 {{
            justify-self: start;
            padding-left: 3.25rem;
          }}
          .bingo-team-heading {{
            display: block;
            text-align: center;
            font-size: 1.65rem;
            font-weight: 800;
            margin: 0 0 0.65rem 0;
            text-decoration: underline;
            text-underline-offset: 0.14em;
            line-height: 1.3;
            white-space: nowrap;
          }}
          .bingo-team-list {{
            margin: 0;
            padding: 0;
            text-align: center;
          }}
          .bingo-team-player {{
            font-size: 1.2rem;
            font-weight: 600;
            line-height: 1.6;
            color: rgba(234, 234, 234, 0.92);
            text-align: center;
            white-space: nowrap;
          }}
          @media (max-width: 700px) {{
            .bingo-teams {{
              display: flex;
              flex-direction: column;
              align-items: center;
              gap: 1.5rem;
            }}
            .bingo-team-col-0,
            .bingo-team-col-1,
            .bingo-team-col-2 {{
              justify-self: center;
              padding: 0;
              border: none;
            }}
          }}
        </style>
        """,
        height=420,
        width=None,
    )


def render_bingo_board() -> None:
    if not supabase_configured():
        st.warning("Supabase is not configured, so the Bingo board cannot load.")
        return

    if "bingo_last_updated" not in st.session_state:
        st.session_state.bingo_last_updated = time.time()

    try:
        settings = load_bingo_settings()
        charts = _cached_bingo_charts()
        teams = _cached_bingo_teams()
    except Exception as exc:
        st.error(f"Failed to load Bingo data: {exc}")
        return

    if settings is None:
        st.warning("Bingo settings are not available yet.")
        return

    _render_bingo_header(settings)

    if not charts:
        st.warning("No Bingo charts are configured yet.")
        return

    width = max(1, int(settings.board_width))
    standings_data = load_bingo_chart_standings_data(start_time=settings.start_time)
    totals = {key: values[0] for key, values in standings_data.items()}
    player_bests = {key: values[1] for key, values in standings_data.items()}
    by_coord = {(chart.row, chart.column): chart for chart in charts}
    groups_by_coord = {
        (chart.row, chart.column): chart.group for chart in charts
    }
    claim_owners = _group_claim_owners(charts, totals, player_bests)

    cells_html: list[str] = []
    max_row = max(chart.row for chart in charts)
    max_col = max(chart.column for chart in charts)
    rows = max(width, max_row + 1)
    cols = max(width, max_col + 1)

    standings_by_coord: dict[tuple[int, int], BingoCellStanding] = {}
    leaders_by_coord: dict[tuple[int, int], str | None] = {}
    for chart in charts:
        standing = build_cell_standing(chart, totals, player_bests)
        standings_by_coord[(chart.row, chart.column)] = standing
        leaders_by_coord[(chart.row, chart.column)] = standing.leader
    line_segments = _bingo_line_segments_by_cell(
        leaders_by_coord, rows=rows, cols=cols
    )

    for row in range(rows):
        for col in range(cols):
            chart = by_coord.get((row, col))
            if chart is None:
                cells_html.append('<div class="bingo-cell bingo-cell-empty"></div>')
                continue
            standing = standings_by_coord[(row, col)]
            claim_team = (
                claim_owners.get(int(chart.group))
                if chart.group is not None
                else None
            )
            cells_html.append(
                _render_cell_html(
                    standing,
                    groups_by_coord=groups_by_coord,
                    claim_team=claim_team,
                    bingo_segments=line_segments.get((row, col), []),
                )
            )

    st.markdown(build_bingo_board_css(), unsafe_allow_html=True)
    _render_bingo_board_toolbar()
    st.markdown(
        f"""
        <div class="bingo-board-shell">
          <div class="bingo-board-wrap">
            <div class="bingo-board" style="grid-template-columns: repeat({cols}, minmax(0, 1fr));">
              {"".join(cells_html)}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    try:
        scoreboard = compute_bingo_scoreboard(settings=settings, charts=charts)
    except Exception as exc:
        st.error(f"Failed to load Bingo scoreboard: {exc}")
        scoreboard = None
    if scoreboard is not None:
        _render_bingo_scoreboard(scoreboard)
    _render_bingo_teams(teams)
