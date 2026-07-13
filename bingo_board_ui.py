"""Bingo Board UI for Streamlit."""

from __future__ import annotations

import html
import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

from rating.bingo import (
    BingoCellStanding,
    BingoChart,
    BingoChartLeaderboardEntry,
    BingoScoreboard,
    BingoSettings,
    BingoSquareClaimEvent,
    BingoTeamPlayer,
    TEAM_ORDER,
    bingo_charts_on_board,
    bingo_day_end,
    bingo_has_started,
    bingo_in_progress_day,
    build_cell_standing,
    completed_bingo_days,
    compute_bingo_scoreboard,
    find_bingo_runs,
    format_leader_score,
    format_score_diff,
    group_claim_owners,
    bingo_chart_max_score,
    load_all_bingo_chart_player_leaderboards,
    merge_chart_leaderboard_with_roster,
    load_bingo_chart_standings_data,
    load_bingo_charts,
    load_bingo_player_chart_best,
    load_bingo_settings,
    load_bingo_square_claim_feed,
    load_bingo_teams_by_ex_rating,
    submit_bingo_score,
)
from rating.formatting import format_difficulty_display_name
from rating.supabase_config import supabase_configured

# Slightly darker than the app background (#0c0e29).
BINGO_CELL_BG = "#07091a"
BINGO_PAGE_BG = "#0c0e29"
BINGO_DISPLAY_TZ = ZoneInfo("America/Los_Angeles")
BINGO_PLAYER_SELECT_PLACEHOLDER = "— Select a player —"
BINGO_CHART_SELECT_PLACEHOLDER = "— Select a chart —"
BINGO_SEARCH_LIMIT = 50
BINGO_ACTIVITY_FEED_LIMIT = 30
BINGO_ACTIVITY_FEED_VISIBLE_COUNT = 6
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
TEAM_ACTIVITY_TINTS = {
    "Eve": "rgba(110, 176, 255, 0.11)",
    "Grace": "rgba(255, 122, 132, 0.11)",
    "Rest": "rgba(94, 224, 154, 0.11)",
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


@st.cache_data(ttl=60, show_spinner=False)
def _cached_bingo_claim_feed(
    start_time_iso: str,
    limit: int = BINGO_ACTIVITY_FEED_LIMIT,
):
    start_time = datetime.fromisoformat(start_time_iso)
    return load_bingo_square_claim_feed(
        start_time=start_time,
        charts=_cached_bingo_charts(),
        limit=limit,
    )


BINGO_APP_RERUN_KEY = "bingo_app_rerun_requested"
BINGO_AUTO_REFRESH_STALE_SECONDS = 600


def _request_bingo_app_rerun(*, touch_live: bool = True) -> None:
    """Queue a full-app rerun (must be consumed outside Streamlit callbacks)."""
    if touch_live:
        _touch_bingo_live_updated()
    _cached_bingo_charts.clear()
    _cached_bingo_teams.clear()
    _cached_bingo_claim_feed.clear()
    st.session_state[BINGO_APP_RERUN_KEY] = True


def _maybe_rerun_bingo_app() -> None:
    if not st.session_state.pop(BINGO_APP_RERUN_KEY, False):
        return
    st.rerun(scope="app")


def _on_bingo_refresh() -> None:
    _request_bingo_app_rerun()


def _consume_bingo_auto_refresh_query() -> None:
    """After a JS-triggered full reload, bump the live clock and clear caches."""
    if not st.query_params.get("bingo_auto"):
        return
    _touch_bingo_live_updated()
    _cached_bingo_charts.clear()
    _cached_bingo_teams.clear()
    _cached_bingo_claim_feed.clear()
    del st.query_params["bingo_auto"]


def _touch_bingo_live_updated() -> None:
    """Reset the Live toolbar clock whenever live board data is (re)shown."""
    st.session_state.bingo_last_updated = time.time()
    st.session_state.bingo_live_updated_nonce = (
        int(st.session_state.get("bingo_live_updated_nonce", 0)) + 1
    )


def _difficulty_label(difficulty: str, level: int | None) -> str:
    diff = format_difficulty_display_name(difficulty).upper()
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


def _inject_bingo_board_layout_css(board_width: str) -> None:
    st.markdown(
        f"""
        <style>
        .st-key-bingo_board_viewport,
        .st-key-bingo-board-viewport {{
            width: min(100%, {board_width}) !important;
            max-width: 100% !important;
            margin: -2.1rem auto 0 !important;
            padding: 0 !important;
        }}
        .st-key-bingo_board_viewport [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-bingo-board-viewport [data-testid="stVerticalBlockBorderWrapper"] {{
            width: 100% !important;
            max-width: 100% !important;
            padding-top: 0 !important;
            gap: 0 !important;
        }}
        .st-key-bingo_board_viewport [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker),
        .st-key-bingo-board-viewport [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker) {{
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            align-items: flex-end !important;
            gap: 0 !important;
        }}
        .st-key-bingo_board_viewport [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker) [data-testid="column"],
        .st-key-bingo-board-viewport [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker) [data-testid="column"] {{
            padding: 0 !important;
        }}
        .st-key-bingo_board_viewport
        [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"]:first-child [data-testid="stVerticalBlock"],
        .st-key-bingo-board-viewport
        [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"]:first-child [data-testid="stVerticalBlock"] {{
            align-items: flex-start !important;
            gap: 0 !important;
        }}
        .st-key-bingo_board_viewport
        [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"]:last-child [data-testid="stVerticalBlock"],
        .st-key-bingo-board-viewport
        [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"]:last-child [data-testid="stVerticalBlock"] {{
            align-items: flex-end !important;
            gap: 0 !important;
        }}
        .st-key-bingo_board_viewport
        [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"]:first-child
        [data-testid="stElementContainer"]:has(.bingo-toolbar-marker),
        .st-key-bingo-board-viewport
        [data-testid="stHorizontalBlock"]:has(.bingo-toolbar-marker)
        [data-testid="column"]:first-child
        [data-testid="stElementContainer"]:has(.bingo-toolbar-marker) {{
            margin: 0 !important;
            padding: 0 !important;
            min-height: 0 !important;
            height: 0 !important;
            overflow: hidden !important;
        }}
        .st-key-bingo_board_viewport .bingo-board-controls-toolbar,
        .st-key-bingo-board-viewport .bingo-board-controls-toolbar {{
            padding-bottom: 0.8rem !important;
            margin: 0 !important;
        }}
        .st-key-bingo_board_viewport [data-testid="stCustomComponentV1"],
        .st-key-bingo-board-viewport [data-testid="stCustomComponentV1"] {{
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_bingo_board_toolbar(*, show_refresh: bool = True) -> None:
    if "bingo_last_updated" not in st.session_state:
        _touch_bingo_live_updated()
    updated_ms = int(float(st.session_state.bingo_last_updated) * 1000)
    updated_nonce = int(st.session_state.get("bingo_live_updated_nonce", 0))

    st.markdown(
        """
        <style>
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
            padding: 0 !important;
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
        [class*="st-key-bingo_last_updated"] {
            width: auto !important;
            min-width: 0 !important;
            flex: 1 1 auto !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        [class*="st-key-bingo_last_updated"] iframe {
            width: min(100%, 360px) !important;
            max-width: 360px !important;
            height: 1.7rem !important;
        }
        .bingo-board-controls-toolbar {
            padding-bottom: 0.8rem !important;
            margin: 0 !important;
            width: auto !important;
            min-height: 1.7rem;
        }
        .bingo-toolbar-marker { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([1, 1], gap="small")
    with left:
        st.markdown(
            '<span class="bingo-toolbar-marker"></span>',
            unsafe_allow_html=True,
        )
        with st.container(horizontal=True, gap="xsmall", key="bingo_refresh_row"):
            if show_refresh:
                st.button(
                    "",
                    key="bingo_refresh_board",
                    type="primary",
                    icon=":material/refresh:",
                    help="Refresh board",
                    on_click=_on_bingo_refresh,
                )
                # Dynamic key forces a fresh iframe; components.html often keeps
                # a stale script (old updatedMs) when only the HTML string changes.
                with st.container(key=f"bingo_last_updated_{updated_nonce}_{updated_ms}"):
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
                <input type="checkbox" class="bingo-board-toggle bingo-detailed-toggle" />
                <span>Detailed Board</span>
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


def _render_bingo_countdown(
    settings: BingoSettings,
    *,
    live_view: bool,
    updated_ms: int | None = None,
) -> None:
    if settings.start_time is None or settings.day_count is None:
        return

    start_utc = settings.start_time
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    start_ms = int(start_utc.timestamp() * 1000)
    day_count = max(1, int(settings.day_count))
    stale_ms = BINGO_AUTO_REFRESH_STALE_SECONDS * 1000
    updated_ms_json = "null" if updated_ms is None else str(int(updated_ms))
    live_view_json = "true" if live_view else "false"

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
            padding: calc(1.05rem + 20px) 0 0 0;
          }}
          .bingo-countdown-label {{
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.1rem;
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
          const staleMs = {stale_ms};
          const liveView = {live_view_json};
          const updatedMs = {updated_ms_json};
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

          function triggerAutoRefresh(storageKey, reason) {{
            try {{
              if (sessionStorage.getItem(storageKey) === "1") {{
                return;
              }}
              sessionStorage.setItem(storageKey, "1");
            }} catch (error) {{}}
            try {{
              const url = new URL(window.parent.location.href);
              url.searchParams.set("bingo_auto", reason);
              window.parent.location.href = url.toString();
            }} catch (error) {{
              window.parent.location.reload();
            }}
          }}

          function scheduleAutoRefresh() {{
            if (!liveView) {{
              return;
            }}
            const now = Date.now();
            const gameEndMs = startMs + dayCount * dayMs;
            const triggers = [];

            if (now < startMs) {{
              triggers.push({{
                at: startMs,
                storageKey: "bingo_refresh_start_" + startMs,
                reason: "start",
              }});
            }} else if (now < gameEndMs) {{
              const dayIndex = Math.floor((now - startMs) / dayMs) + 1;
              const dayEndMs = startMs + dayIndex * dayMs;
              triggers.push({{
                at: dayEndMs,
                storageKey: "bingo_refresh_day_" + dayIndex + "_" + dayEndMs,
                reason: "day",
              }});
            }}

            if (updatedMs !== null) {{
              triggers.push({{
                at: updatedMs + staleMs,
                storageKey: "bingo_refresh_stale_" + updatedMs,
                reason: "stale",
              }});
            }}

            for (const trigger of triggers) {{
              const delay = trigger.at - now;
              if (delay <= 0) {{
                triggerAutoRefresh(trigger.storageKey, trigger.reason);
                return;
              }}
              setTimeout(
                () => triggerAutoRefresh(trigger.storageKey, trigger.reason),
                delay
              );
            }}
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
          scheduleAutoRefresh();
        </script>
        """,
        height=86,
    )


def _render_bingo_header(
    settings: BingoSettings,
    *,
    live_view: bool,
    updated_ms: int | None = None,
) -> None:
    schedule = _format_bingo_schedule(settings)
    schedule_html = (
        f'<div class="bingo-header-schedule">{html.escape(schedule)}</div>'
        if schedule
        else ""
    )
    with st.container(key="bingo_page_header"):
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
        _render_bingo_countdown(
            settings,
            live_view=live_view,
            updated_ms=updated_ms,
        )
        st.markdown(
            '<span class="bingo-header-end-marker" style="display:none;"></span>',
            unsafe_allow_html=True,
        )


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
    *,
    rows: int,
    cols: int,
) -> str:
    """Colored group outline on outer edges; keep normal grid lines between same-group cells."""

    def on_board(r: int, c: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols

    def border_for_side(nr: int, nc: int) -> str:
        if on_board(nr, nc) and groups_by_coord.get((nr, nc)) == group:
            return DEFAULT_CELL_BORDER
        color = GROUP_BORDER_COLORS.get(group)
        if color is None:
            return DEFAULT_CELL_BORDER
        return f"{GROUP_BORDER_WIDTH} solid {color}"

    if group is None:
        return f"border:{DEFAULT_CELL_BORDER};"

    if group not in GROUP_BORDER_COLORS:
        return f"border:{DEFAULT_CELL_BORDER};"

    top = border_for_side(row - 1, col)
    right = border_for_side(row, col + 1)
    bottom = border_for_side(row + 1, col)
    left = border_for_side(row, col - 1)
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
    rows: int,
    cols: int,
) -> str:
    chart = standing.chart
    song = html.escape(chart.display_name)
    difficulty = html.escape(_difficulty_label(chart.difficulty, chart.level))
    cell_bg = _cell_background(standing)
    border_css = _cell_border_css(
        chart.row,
        chart.column,
        chart.group,
        groups_by_coord,
        rows=rows,
        cols=cols,
    )
    claim_html = _claim_outline_html(
        chart.row,
        chart.column,
        chart.group,
        groups_by_coord,
        claim_team,
    )
    line_html = _bingo_line_svg_html(bingo_segments or [])
    aria_label = html.escape(f"View leaderboard for {chart.display_name}")
    return (
        f'<div class="bingo-cell bingo-cell-link" role="button" tabindex="0"'
        f' data-row="{chart.row}" data-col="{chart.column}"'
        f' aria-label="{aria_label}"'
        f' style="--bingo-cell-bg:{cell_bg};{border_css}">'
        f"{line_html}"
        f"{claim_html}"
        '<div class="bingo-cell-top">'
        '<div class="bingo-cell-header">'
        f'<div class="bingo-cell-song">{song}</div>'
        f'<div class="bingo-cell-diff">{difficulty}</div>'
        "</div>"
        "</div>"
        f'<div class="bingo-cell-mid">{_leader_block_html(standing)}</div>'
        f'<div class="bingo-cell-bot">{_trailers_block_html(standing)}</div>'
        "</div>"
    )


_BINGO_CHART_MODAL_SCROLLBAR_CSS = """
    .bingo-chart-modal-panel,
    .bingo-chart-modal-table-wrap {
        scrollbar-width: thin;
        scrollbar-color: rgba(234, 234, 234, 0.28) rgba(16, 22, 45, 0.55);
    }
    .bingo-chart-modal-panel::-webkit-scrollbar,
    .bingo-chart-modal-table-wrap::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    .bingo-chart-modal-panel::-webkit-scrollbar-track,
    .bingo-chart-modal-table-wrap::-webkit-scrollbar-track {
        background: rgba(16, 22, 45, 0.55);
        border-radius: 999px;
    }
    .bingo-chart-modal-panel::-webkit-scrollbar-thumb,
    .bingo-chart-modal-table-wrap::-webkit-scrollbar-thumb {
        background: rgba(234, 234, 234, 0.28);
        border-radius: 999px;
        border: 2px solid rgba(16, 22, 45, 0.55);
    }
    .bingo-chart-modal-panel::-webkit-scrollbar-thumb:hover,
    .bingo-chart-modal-table-wrap::-webkit-scrollbar-thumb:hover {
        background: rgba(234, 234, 234, 0.42);
    }
    .bingo-chart-modal-panel::-webkit-scrollbar-corner,
    .bingo-chart-modal-table-wrap::-webkit-scrollbar-corner {
        background: rgba(16, 22, 45, 0.55);
    }
"""

_BINGO_CHART_MODAL_ANIMATION_CSS = """
    .bingo-chart-modal-overlay {
        display: flex;
        opacity: 0;
        visibility: hidden;
        pointer-events: none;
        transition: opacity 0.22s ease, visibility 0.22s ease;
    }
    .bingo-chart-modal-overlay.is-open {
        opacity: 1;
        visibility: visible;
        pointer-events: auto;
    }
    .bingo-chart-modal-overlay.is-closing {
        pointer-events: none;
    }
    .bingo-chart-modal-panel {
        transform: translateY(12px) scale(0.985);
        transition: transform 0.22s ease;
    }
    .bingo-chart-modal-overlay.is-open .bingo-chart-modal-panel {
        transform: translateY(0) scale(1);
    }
"""


def build_bingo_board_css() -> str:
    return f"""
    <style>
    /* Tighten countdown -> toolbar gap without touching page-level layout. */
    .st-key-bingo_page_header,
    .st-key-bingo-page-header {{
        margin: 0 0 -2.1rem 0 !important;
        padding: 0 !important;
    }}
    .st-key-bingo_page_header [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-bingo-page-header [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-bingo_page_header [data-testid="stVerticalBlock"],
    .st-key-bingo-page-header [data-testid="stVerticalBlock"] {{
        gap: 0 !important;
        padding-bottom: 0 !important;
    }}
    .st-key-bingo_page_header [data-testid="stElementContainer"],
    .st-key-bingo-page-header [data-testid="stElementContainer"] {{
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-bingo_page_header [data-testid="stCustomComponentV1"],
    .st-key-bingo-page-header [data-testid="stCustomComponentV1"] {{
        margin: 0 !important;
        padding: 0 !important;
        height: 86px !important;
    }}
    .st-key-bingo_page_header iframe,
    .st-key-bingo-page-header iframe {{
        height: 86px !important;
        min-height: 0 !important;
        display: block !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-bingo_page_header [data-testid="stElementContainer"]:has(.bingo-header-end-marker),
    .st-key-bingo-page-header [data-testid="stElementContainer"]:has(.bingo-header-end-marker) {{
        min-height: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
    }}
    .st-key-bingo_board_viewport [data-testid="stCustomComponentV1"],
    .st-key-bingo-board-viewport [data-testid="stCustomComponentV1"] {{
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
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
        padding: 0;
    }}
    .bingo-board-controls-toolbar {{
        padding: 0 0 0.8rem 0 !important;
        margin: 0 !important;
        width: auto !important;
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
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell-mid,
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell-bot {{
        overflow: hidden;
        min-height: 0;
        opacity: 0;
        transform: translateY(-0.35rem);
        transition: opacity 0.22s ease, transform 0.22s ease;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell {{
        cursor: pointer;
        grid-template-rows: 1fr 0fr 0fr;
        place-items: stretch;
        transition: grid-template-rows 0.28s ease;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell-top {{
        position: relative;
        min-height: 0;
        height: 100%;
        width: 100%;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell-header {{
        position: absolute;
        left: 0;
        right: 0;
        width: 100%;
        top: 50%;
        transform: translateY(-50%);
        transition: top 0.28s ease, transform 0.28s ease;
        will-change: top, transform;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell-song {{
        font-size: 1.05rem;
        min-height: unset;
        -webkit-line-clamp: unset;
        transition: font-size 0.28s ease;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell-diff {{
        font-size: 0.95rem;
        margin-top: 0.25rem;
        transition: font-size 0.28s ease, margin-top 0.28s ease;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover {{
        z-index: 6;
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-mid,
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-bot {{
        opacity: 1;
        transform: translateY(0);
        transition-delay: 0.05s;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-top {{
        min-height: 3.5rem;
        height: auto;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-header {{
        top: 0;
        transform: translateY(0);
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-song {{
        font-size: 0.95rem;
        -webkit-line-clamp: 2;
    }}
    [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-diff {{
        font-size: 0.88rem;
        margin-top: 0.1rem;
    }}
    .bingo-board-wrap {{
        width: 100%;
        overflow: visible;
        padding-bottom: 2rem;
    }}
    .bingo-board {{
        display: grid;
        gap: 0;
        width: 100%;
        margin: 0;
        box-sizing: border-box;
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
        display: grid;
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
        align-content: stretch;
        box-sizing: border-box;
        border: none;
        overflow: hidden;
    }}
    .bingo-cell:not(.bingo-cell-empty) {{
        cursor: pointer;
    }}
    a.bingo-cell-link:focus-visible {{
        outline: none;
        box-shadow: inset 0 0 0 2px rgba(110, 176, 255, 0.85);
    }}
    .bingo-chart-modal-overlay {{
        position: fixed;
        inset: 0;
        z-index: 1000000;
        align-items: center;
        justify-content: center;
        padding: 1.5rem;
        box-sizing: border-box;
    }}
    {_BINGO_CHART_MODAL_ANIMATION_CSS}
    .bingo-chart-modal-backdrop {{
        position: absolute;
        inset: 0;
        border: none;
        background: rgba(4, 8, 20, 0.72);
        cursor: pointer;
    }}
    .bingo-chart-modal-panel {{
        position: relative;
        z-index: 1;
        width: min(100%, 720px);
        max-height: min(80vh, 760px);
        overflow: auto;
        background: #10162d;
        border: 1px solid rgba(234, 234, 234, 0.18);
        border-radius: 0.85rem;
        box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
        padding: 1.25rem 1.25rem 1.1rem;
        box-sizing: border-box;
    }}
    {_BINGO_CHART_MODAL_SCROLLBAR_CSS}
    .bingo-chart-modal-close {{
        position: absolute;
        top: 0.65rem;
        right: 0.75rem;
        border: none;
        background: transparent;
        color: rgba(234, 234, 234, 0.72);
        font-size: 1.65rem;
        line-height: 1;
        cursor: pointer;
        padding: 0.15rem 0.35rem;
    }}
    .bingo-chart-modal-close:hover {{
        color: #ffffff;
    }}
    .bingo-chart-modal-title {{
        font-size: 1.35rem;
        font-weight: 800;
        color: #f5f5f5;
        margin: 0 2rem 0.2rem 0;
        line-height: 1.25;
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
    }}
    .bingo-chart-modal-diff {{
        font-weight: 400;
        color: rgba(234, 234, 234, 0.82);
    }}
    .bingo-chart-modal-subtitle {{
        font-size: 0.95rem;
        font-weight: 600;
        color: rgba(234, 234, 234, 0.62);
        margin: 0 0 1rem 0;
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
    }}
    .bingo-chart-modal-table-wrap {{
        overflow-x: auto;
    }}
    .bingo-chart-modal-table {{
        width: 100%;
        border-collapse: collapse;
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
        color: #eaeaea;
    }}
    .bingo-chart-modal-table th,
    .bingo-chart-modal-table td {{
        padding: 0.55rem 0.75rem;
        border-bottom: 1px solid rgba(234, 234, 234, 0.14);
        text-align: left;
        vertical-align: middle;
    }}
    .bingo-chart-modal-table th {{
        font-size: 0.82rem;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: rgba(234, 234, 234, 0.58);
    }}
    .bingo-chart-modal-rank {{
        width: 3rem;
        color: rgba(234, 234, 234, 0.72);
        font-variant-numeric: tabular-nums;
    }}
    .bingo-chart-modal-player {{
        font-weight: 700;
    }}
    .bingo-chart-modal-team {{
        width: 5.5rem;
        font-weight: 700;
    }}
    .bingo-chart-modal-score {{
        width: 6rem;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        text-align: right !important;
    }}
    .bingo-chart-modal-empty {{
        padding: 1.25rem 0.5rem;
        color: rgba(234, 234, 234, 0.72);
        font-size: 1rem;
        font-weight: 600;
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
        min-height: 3.5rem;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        align-items: center;
    }}
    .bingo-cell-header {{
        width: 100%;
    }}
    .bingo-cell-bot {{
        position: relative;
        z-index: 4;
        background: transparent;
        min-height: 2.15rem;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
    }}
    .bingo-cell-mid {{
        position: relative;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        align-items: center;
        min-height: 4.25rem;
        padding-top: 0.15rem;
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
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
        overflow: hidden;
    }}
    .bingo-cell-diff {{
        font-size: 0.88rem;
        font-weight: 400;
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
        box-sizing: border-box;
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
            grid-template-rows: minmax(3.1rem, auto) minmax(3.75rem, 1fr) minmax(2rem, auto);
        }}
        .bingo-cell-top {{
            min-height: 3.1rem;
        }}
        .bingo-cell-bot {{
            min-height: 2rem;
        }}
        .bingo-cell-mid {{
            min-height: 3.75rem;
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
        [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell {{
            grid-template-rows: 1fr 0fr 0fr;
        }}
        [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover {{
            grid-template-rows: minmax(3.1rem, auto) minmax(3.75rem, 1fr) minmax(2rem, auto);
        }}
        [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-top {{
            min-height: 3.1rem;
        }}
        [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-song {{
        font-size: 0.8rem;
            -webkit-line-clamp: 2;
        }}
        [data-testid="stAppViewContainer"]:not(:has(.bingo-detailed-toggle:checked)) .bingo-cell:hover .bingo-cell-diff {{
            font-size: 0.74rem;
        }}
    }}
    </style>
    """


def _inject_scoreboard_day_highlight(highlight_day: int | None) -> None:
    """Update scoreboard column highlight via CSS only (table itself stays mounted)."""
    if highlight_day is None:
        rule = ""
    else:
        day = int(highlight_day)
        edge = "rgba(234, 234, 234, 0.5)"
        fill = (
            "linear-gradient(rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.04))"
        )
        rule = f"""
        .bingo-scoreboard thead th[data-day="{day}"] {{
          color: #ffffff !important;
          font-weight: 800 !important;
          background-image: {fill} !important;
          box-shadow:
            inset 2px 0 0 0 {edge},
            inset -2px 0 0 0 {edge},
            inset 0 2px 0 0 {edge} !important;
        }}
        .bingo-scoreboard tbody td[data-day="{day}"] {{
          background-image: {fill} !important;
          box-shadow:
            inset 2px 0 0 0 {edge},
            inset -2px 0 0 0 {edge} !important;
        }}
        .bingo-scoreboard tbody tr:last-child td[data-day="{day}"] {{
          box-shadow:
            inset 2px 0 0 0 {edge},
            inset -2px 0 0 0 {edge},
            inset 0 -2px 0 0 {edge} !important;
        }}
        """
    st.markdown(
        f"""
        <style>
        .bingo-scoreboard [data-day] {{
          box-shadow: none !important;
          background-image: none !important;
        }}
        .bingo-scoreboard thead th[data-day] {{
          color: rgba(234, 234, 234, 0.88) !important;
          font-weight: 700 !important;
        }}
        {rule}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_bingo_scoreboard(
    scoreboard: BingoScoreboard,
    *,
    live_view: bool = True,
) -> None:
    day_headers_html = "".join(
        f'<th class="bingo-sb-day" data-day="{day}" scope="col">{day}</th>'
        for day in range(1, scoreboard.day_count + 1)
    )
    rows_html: list[str] = []
    scoreboard_row_bg = {
        "Eve": "#0c1528",
        "Grace": "#1a1016",
        "Rest": "#0c1814",
    }
    prospective_day = scoreboard.prospective_day if live_view else None
    for team in TEAM_ORDER:
        color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
        row_bg = scoreboard_row_bg.get(team, BINGO_CELL_BG)
        cells = []
        for day_index, value in enumerate(scoreboard.daily_points.get(team, [])):
            day = day_index + 1
            is_prospective = prospective_day is not None and day == prospective_day
            # Hide live provisional scores when browsing a past day.
            if (
                not live_view
                and scoreboard.prospective_day is not None
                and day == scoreboard.prospective_day
            ):
                value = None
            if value is None:
                cells.append(
                    f'<td class="bingo-sb-score bingo-sb-blank" data-day="{day}" '
                    f'style="background:{row_bg};"></td>'
                )
            elif is_prospective:
                cells.append(
                    f'<td class="bingo-sb-score bingo-sb-prospective" data-day="{day}" '
                    f'style="background:{row_bg};">'
                    f"{html.escape(str(value))}</td>"
                )
            else:
                cells.append(
                    f'<td class="bingo-sb-score" data-day="{day}" '
                    f'style="background:{row_bg};">'
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
          .bingo-sb-score.bingo-sb-prospective {{
            color: rgba(155, 162, 175, 0.55) !important;
            font-weight: 700 !important;
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
                {day_headers_html}
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


def _format_bingo_time_ago(value: datetime) -> str:
    now = datetime.now(timezone.utc)
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 45:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"
    hours = minutes // 60
    if hours < 24:
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"
    days = hours // 24
    if days < 7:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} ago"
    return moment.astimezone(BINGO_DISPLAY_TZ).strftime("%b %d, %Y")


def _render_bingo_claim_feed_item(event: BingoSquareClaimEvent) -> str:
    team_color = TEAM_TEXT_COLORS.get(event.team, "#eaeaea")
    tint = TEAM_ACTIVITY_TINTS.get(event.team, "rgba(234, 234, 234, 0.06)")
    player = html.escape(event.player_display_name)
    chart = html.escape(
        f"{event.chart_display_name} "
        f"[{format_difficulty_display_name(event.difficulty).upper()}]"
    )
    time_ago = html.escape(_format_bingo_time_ago(event.created_at))
    if event.prev_team is None:
        action = f'claimed <span class="bingo-activity-chart">{chart}</span>'
    else:
        prev_color = TEAM_TEXT_COLORS.get(event.prev_team, "#eaeaea")
        prev = html.escape(event.prev_team.upper())
        action = (
            f'took <span class="bingo-activity-chart">{chart}</span> from '
            f'<span class="bingo-activity-team" style="color:{prev_color};">{prev}</span>'
        )
    badges: list[str] = []
    if event.formed_bingo:
        badges.append(
            '<span class="bingo-activity-badge bingo-activity-badge--bingo">Bingo!</span>'
        )
    if event.formed_four:
        badges.append(
            '<span class="bingo-activity-badge bingo-activity-badge--four">4-in-a-Row!</span>'
        )
    if event.captured_group:
        badges.append(
            '<span class="bingo-activity-badge bingo-activity-badge--group">Group Captured!</span>'
        )
    badges_html = (
        f'<span class="bingo-activity-badges">{"".join(badges)}</span>'
        if badges
        else ""
    )
    return (
        f'<div class="bingo-activity-item" style="'
        f"border-left-color:{team_color};"
        f"background:linear-gradient(90deg,{tint} 0%,rgba(10,18,36,0.28) 42%,rgba(10,18,36,0.18) 100%);"
        '">'
        f'<span class="bingo-activity-player" style="color:{team_color};" '
        f'title="{html.escape(event.team)}">{player}</span>'
        f'<span class="bingo-activity-action">{action}{badges_html}</span>'
        f'<span class="bingo-activity-time">{time_ago}</span>'
        "</div>"
    )


def _render_bingo_activity_feed(*, settings: BingoSettings) -> None:
    if not bingo_has_started(start_time=settings.start_time):
        return

    st.markdown(
        f"""
        <style>
          .st-key-bingo_activity_feed,
          .st-key-bingo-activity-feed {{
            width: min(100%, 720px) !important;
            max-width: 720px !important;
            margin: 1.25rem auto 0.5rem !important;
          }}
          .bingo-activity-viewport {{
            --bingo-activity-item-gap: 0.55rem;
            --bingo-activity-item-height: 3.25rem;
            --bingo-activity-fade-height: 1.5rem;
            --bingo-activity-visible-items: {BINGO_ACTIVITY_FEED_VISIBLE_COUNT};
            width: 100%;
            position: relative;
          }}
          .bingo-activity-viewport--scrollable {{
            max-height: calc(
              var(--bingo-activity-visible-items) * var(--bingo-activity-item-height)
              + (var(--bingo-activity-visible-items) - 1) * var(--bingo-activity-item-gap)
            );
            overflow-y: auto;
            padding-right: 0.35rem;
            scrollbar-color: rgba(245, 245, 245, 0.28) transparent;
            scrollbar-width: thin;
          }}
          .bingo-activity-viewport--scrollable .bingo-activity-feed {{
            padding-bottom: var(--bingo-activity-fade-height);
          }}
          .bingo-activity-viewport--scrollable::after {{
            content: "";
            position: sticky;
            bottom: 0;
            left: 0;
            right: 0;
            display: block;
            height: var(--bingo-activity-fade-height);
            margin-top: calc(-1 * var(--bingo-activity-fade-height));
            pointer-events: none;
            background: linear-gradient(
              to bottom,
              rgba(12, 14, 41, 0) 0%,
              rgba(12, 14, 41, 0.82) 58%,
              #0c0e29 100%
            );
          }}
          .bingo-activity-feed {{
        display: flex;
            flex-direction: column;
            gap: var(--bingo-activity-item-gap);
            width: 100%;
          }}
          .bingo-activity-item {{
            display: grid;
            grid-template-columns: minmax(5.5rem, 8.5rem) minmax(0, 1fr) auto;
        align-items: center;
            column-gap: 0.4rem;
            min-height: var(--bingo-activity-item-height);
            box-sizing: border-box;
            padding: 0.7rem 0.9rem 0.7rem 0.85rem;
            border-radius: 0.65rem;
            border: 1px solid rgba(120, 190, 255, 0.14);
            border-left: 3px solid #6eb0ff;
          }}
          .bingo-activity-player {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
            font-weight: 800;
            font-size: 0.95rem;
          }}
          .bingo-activity-team {{
            font-weight: 800;
            letter-spacing: 0.03em;
            font-size: 0.95rem;
          }}
          .bingo-activity-action {{
            min-width: 0;
            color: rgba(234, 234, 234, 0.88);
            font-size: 0.95rem;
            line-height: 1.3;
          }}
          .bingo-activity-chart {{
            color: rgba(245, 245, 245, 0.96);
        font-weight: 700;
          }}
          .bingo-activity-badges {{
            display: inline-flex;
            flex-wrap: wrap;
            gap: 0.3rem;
            margin-left: 0.45rem;
            vertical-align: middle;
          }}
          .bingo-activity-badge {{
            display: inline-block;
            padding: 0.12rem 0.4rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.03em;
            line-height: 1.2;
            white-space: nowrap;
            vertical-align: middle;
          }}
          .bingo-activity-badge--bingo {{
            color: #ffe7a3;
            background: rgba(245, 213, 71, 0.18);
            border: 1px solid rgba(245, 213, 71, 0.45);
          }}
          .bingo-activity-badge--four {{
            color: #c9ddff;
            background: rgba(110, 176, 255, 0.16);
            border: 1px solid rgba(110, 176, 255, 0.4);
          }}
          .bingo-activity-badge--group {{
            color: #e2c8ff;
            background: rgba(192, 132, 252, 0.16);
            border: 1px solid rgba(192, 132, 252, 0.42);
          }}
          .bingo-activity-time {{
            color: rgba(245, 245, 245, 0.45);
            font-size: 0.8125rem;
            white-space: nowrap;
            justify-self: end;
          }}
          .bingo-activity-empty {{
            color: rgba(245, 245, 245, 0.55);
            font-size: 0.925rem;
            margin: 0;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="bingo_activity_feed"):
        st.subheader("Activity Feed")
        try:
            assert settings.start_time is not None
            events = load_bingo_square_claim_feed(
                start_time=settings.start_time,
                charts=_cached_bingo_charts(),
                board_width=int(settings.board_width),
                limit=BINGO_ACTIVITY_FEED_LIMIT,
            )
        except Exception as exc:
            st.warning(f"Could not load activity feed: {exc}")
            return

        if not events:
            st.markdown(
                '<p class="bingo-activity-empty">'
                "No activity yet. First team to score on a chart shows up here."
                "</p>",
                unsafe_allow_html=True,
            )
            return

        items_html = "".join(_render_bingo_claim_feed_item(event) for event in events)
        scrollable = len(events) > BINGO_ACTIVITY_FEED_VISIBLE_COUNT
        viewport_class = (
            "bingo-activity-viewport bingo-activity-viewport--scrollable"
            if scrollable
            else "bingo-activity-viewport"
        )
        st.markdown(
            f'<div class="{viewport_class}">'
            f'<div class="bingo-activity-feed">{items_html}</div>'
            "</div>",
            unsafe_allow_html=True,
        )


def _bingo_player_option_label(player: BingoTeamPlayer) -> str:
    return f"{player.display_name} ({player.team})"


def _bingo_chart_option_label(chart: BingoChart) -> str:
    return f"{chart.display_name} {_difficulty_label(chart.difficulty, chart.level)}"


def _auto_select_if_single_match(
    *,
    select_key: str,
    placeholder: str,
    matches: list[str],
) -> None:
    if len(matches) == 1:
        st.session_state[select_key] = matches[0]
    elif len(matches) == 0:
        st.session_state[select_key] = placeholder


def _flatten_bingo_players(
    teams: dict[str, list[BingoTeamPlayer]],
) -> list[BingoTeamPlayer]:
    players: list[BingoTeamPlayer] = []
    for team in TEAM_ORDER:
        players.extend(teams.get(team, []))
    return players


def _find_bingo_player(
    players: list[BingoTeamPlayer],
    *,
    option_label: str,
) -> BingoTeamPlayer | None:
    for player in players:
        if _bingo_player_option_label(player) == option_label:
            return player
    return None


def _find_bingo_chart(
    charts: list[BingoChart],
    *,
    option_label: str,
) -> BingoChart | None:
    for chart in charts:
        if _bingo_chart_option_label(chart) == option_label:
            return chart
    return None


@st.fragment
def _render_bingo_manual_submission(
    *,
    charts: list[BingoChart],
    teams: dict[str, list[BingoTeamPlayer]],
    settings: BingoSettings,
) -> None:
    board_charts = bingo_charts_on_board(charts, settings.board_width)
    players = _flatten_bingo_players(teams)

    st.markdown(
        """
        <style>
          .st-key-bingo_submit_panel,
          .st-key-bingo-submit-panel {
            width: min(100%, 720px) !important;
            max-width: 720px !important;
            margin: 1.75rem auto 0.5rem !important;
          }
          .st-key-bingo_submit_panel [data-testid="stVerticalBlockBorderWrapper"],
          .st-key-bingo-submit-panel [data-testid="stVerticalBlockBorderWrapper"] {
            width: 100% !important;
            box-sizing: border-box !important;
            padding: 1rem 1.15rem 1.15rem !important;
          }
          .bingo-submit-title {
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 1.35rem;
            font-weight: 800;
            color: rgba(234, 234, 234, 0.95);
            margin: 0 0 0.35rem;
          }
          .bingo-submit-note {
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 0.95rem;
            color: rgba(200, 205, 215, 0.82);
            margin: 0 0 0.85rem;
            line-height: 1.4;
          }
          .bingo-submit-current {
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 1.05rem;
            font-weight: 600;
            color: rgba(234, 234, 234, 0.92);
            margin: 0.35rem 0 0.75rem;
            text-align: center;
          }
          .bingo-submit-current span {
            color: #6eb0ff;
            font-weight: 800;
          }
          .st-key-bingo_submit_score_input [data-testid="stNumberInput"] button,
          .st-key-bingo-submit-score-input [data-testid="stNumberInput"] button {
            display: none !important;
          }
          .st-key-bingo-submit-score-button button {
            white-space: nowrap !important;
          }
          .bingo-submit-hint {
            text-align: center;
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 0.875rem;
            color: rgba(200, 205, 215, 0.75);
            margin: 0.15rem 0 0.65rem;
    }
    </style>
        """,
        unsafe_allow_html=True,
    )


    with st.container(border=True, key="bingo_submit_panel"):
        success_message = st.session_state.pop("bingo_submit_success", None)
        if success_message:
            st.success(success_message)

        st.markdown(
            """
            <div class="bingo-submit-title">Submit a Score</div>
            <div class="bingo-submit-note">
              Please take a screenshot of the results screen in case verification is needed.
            </div>
            """,
            unsafe_allow_html=True,
        )

        player_col, chart_col = st.columns(2, gap="medium")

        with player_col:
            player_search = st.text_input(
                "Search players",
                placeholder="Search by player name…",
                key="bingo-submit-player-search",
            ).strip()
            player_needle = player_search.casefold()
            if player_needle:
                player_matches = [
                    player
                    for player in players
                    if player_needle in player.display_name.casefold()
                ]
                if not player_matches:
                    st.caption("No players match your search.")
            else:
                player_matches = list(players)
            player_matches = sorted(
                player_matches,
                key=lambda player: player.display_name.casefold(),
            )
            if player_needle:
                player_matches = player_matches[:BINGO_SEARCH_LIMIT]
            player_options = [BINGO_PLAYER_SELECT_PLACEHOLDER] + [
                _bingo_player_option_label(player) for player in player_matches
            ]

            if player_needle:
                _auto_select_if_single_match(
                    select_key="bingo-submit-player-select",
                    placeholder=BINGO_PLAYER_SELECT_PLACEHOLDER,
                    matches=[
                        _bingo_player_option_label(player) for player in player_matches
                    ],
                )
            selected_player_option = st.selectbox(
                "Player",
                options=player_options,
                key="bingo-submit-player-select",
                disabled=not player_matches,
            )
            selected_player = _find_bingo_player(
                players,
                option_label=selected_player_option,
            )

        with chart_col:
            chart_search = st.text_input(
                "Search charts",
                placeholder="Search by song name…",
                key="bingo-submit-chart-search",
            ).strip()
            chart_needle = chart_search.casefold()
            if chart_needle:
                chart_matches = [
                    chart
                    for chart in board_charts
                    if chart_needle in chart.display_name.casefold()
                    or chart_needle in chart.song.casefold()
                    or chart_needle in chart.difficulty.casefold()
                    or chart_needle
                    in format_difficulty_display_name(chart.difficulty).casefold()
                ]
                if not chart_matches:
                    st.caption("No board charts match your search.")
            else:
                chart_matches = list(board_charts)
            chart_matches = sorted(
                chart_matches,
                key=lambda chart: (
                    chart.display_name.casefold(),
                    chart.difficulty.casefold(),
                ),
            )
            if chart_needle:
                chart_matches = chart_matches[:BINGO_SEARCH_LIMIT]
            chart_options = [BINGO_CHART_SELECT_PLACEHOLDER] + [
                _bingo_chart_option_label(chart) for chart in chart_matches
            ]

            if chart_needle:
                _auto_select_if_single_match(
                    select_key="bingo-submit-chart-select",
                    placeholder=BINGO_CHART_SELECT_PLACEHOLDER,
                    matches=[
                        _bingo_chart_option_label(chart) for chart in chart_matches
                    ],
                )
            selected_chart_option = st.selectbox(
                "Chart",
                options=chart_options,
                key="bingo-submit-chart-select",
                disabled=not chart_matches,
            )
            selected_chart = _find_bingo_chart(
                board_charts,
                option_label=selected_chart_option,
            )

        current_best: int | None = None
        if selected_player is not None and selected_chart is not None:
            try:
                current_best = load_bingo_player_chart_best(
                    player_id=selected_player.player_id,
                    song=selected_chart.song,
                    difficulty=selected_chart.difficulty,
                    start_time=settings.start_time,
                )
            except Exception as exc:
                st.error(f"Could not load current score: {exc}")
                current_best = None

        if selected_player is not None and selected_chart is not None:
            if current_best is None:
                st.markdown(
                    '<div class="bingo-submit-current">Current score: '
                    "<span>None</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="bingo-submit-current">Current score: '
                    f"<span>{html.escape(format_leader_score(current_best))}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )

        chart_max: int | None = None
        if selected_chart is not None:
            chart_max = bingo_chart_max_score(
                selected_chart.song,
                selected_chart.difficulty,
            )

        # Side spacers keep the score field + button as a tight centered pair.
        _left, score_col, btn_col, _right = st.columns(
            [1.4, 2.1, 1.15, 1.4],
            gap="small",
            vertical_alignment="bottom",
        )
        with score_col:
            with st.container(key="bingo_submit_score_input"):
                new_score = st.number_input(
                    "New score",
                    min_value=0,
                    max_value=99_999_999,
                    step=1,
                    format="%d",
                    key="bingo-submit-score-input",
                    disabled=selected_player is None or selected_chart is None,
                )
        score_value = int(new_score)
        score_too_high = chart_max is not None and score_value > chart_max
        score_not_higher = current_best is not None and score_value <= current_best
        score_invalid = score_value <= 0 or score_too_high
        submission_in_progress = bool(
            st.session_state.get("bingo_submission_in_progress", False)
        )
        can_submit = (
            selected_player is not None
            and selected_chart is not None
            and not score_invalid
            and not score_not_higher
            and not submission_in_progress
            and supabase_configured()
        )
        with btn_col:
            submitted = st.button(
                "Submit score",
                type="primary",
                key="bingo-submit-score-button",
                disabled=not can_submit,
            )

        if selected_player is not None and selected_chart is not None:
            if score_too_high:
                st.markdown(
                    '<div class="bingo-submit-hint">Enter a valid score</div>',
                    unsafe_allow_html=True,
                )
            elif score_not_higher:
                st.markdown(
                    '<div class="bingo-submit-hint">'
                    f"Enter a score higher than {html.escape(format_leader_score(current_best))}."
                    "</div>",
                    unsafe_allow_html=True,
                )

        if (
            submitted
            and not submission_in_progress
            and selected_player is not None
            and selected_chart is not None
        ):
            st.session_state.bingo_pending_submission = {
                "player_id": selected_player.player_id,
                "song": selected_chart.song,
                "difficulty": selected_chart.difficulty,
                "score": score_value,
            }
            st.session_state.bingo_submission_in_progress = True
            # One app rerun: spinner covers save + board/scoreboard reload.
            st.rerun(scope="app")

        submit_error = st.session_state.pop("bingo_submit_error", None)
        if submit_error:
            st.error(submit_error)


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

    st.markdown(
        f"""
        <style>
          .bingo-teams-shell {{
            width: min(100%, 1100px);
            margin: 0 auto;
            display: flex;
            justify-content: center;
          }}
          div[data-testid="stMarkdownContainer"]:has(.bingo-teams-shell),
          div[data-testid="stElementContainer"]:has(.bingo-teams-shell) {{
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
            overflow: visible !important;
          }}
          div[data-testid="stMarkdownContainer"]:has(.bingo-teams-shell) p {{
            margin: 0 !important;
            padding: 0 !important;
            min-height: 0 !important;
          }}
          .bingo-teams {{
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1.75rem;
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
          @media (min-width: 900px) {{
            .bingo-teams {{
              display: grid;
              grid-template-columns: 1fr auto 1fr;
              column-gap: 0;
              align-items: stretch;
              gap: 0;
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
          }}
        </style>
        <div class="bingo-teams-shell">
          <div class="bingo-teams">{"".join(columns)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _bingo_view_day_from_label(
    label: str | None,
    *,
    day_count: int,
) -> int | None:
    if label is None or label == "Live":
        return None
    if label == "Final":
        return int(day_count)
    try:
        return int(str(label).removeprefix("Day ").strip())
    except ValueError:
        return None


def _bingo_view_label(
    view_day: int | None,
    *,
    day_count: int,
    completed_days: int,
) -> str:
    if view_day is None:
        return "Live"
    if int(view_day) == int(day_count) and completed_days >= day_count:
        return "Final"
    return f"Day {int(view_day)}"


def _bingo_view_options(*, completed_days: int, day_count: int) -> list[str]:
    """Labels for the board-view selector."""
    if completed_days < 1:
        return []
    game_over = completed_days >= day_count
    day_labels: list[str] = []
    for day in range(1, completed_days + 1):
        if day == day_count:
            day_labels.append("Final")
        else:
            day_labels.append(f"Day {day}")
    if game_over:
        return day_labels
    return ["Live", *day_labels]


def _on_bingo_return_live() -> None:
    """Match tapping Live on the day selector (runs before widgets instantiate)."""
    st.session_state.bingo_view_day = None
    st.session_state.bingo_board_view_control = "Live"
    st.session_state.bingo_board_mode = "live"
    _request_bingo_app_rerun()


def _render_bingo_historical_banner(
    view_day: int,
    *,
    day_count: int,
    show_live_button: bool,
) -> None:
    day_text = (
        "Final"
        if int(view_day) == int(day_count)
        else f"Day {int(view_day)}"
    )
    st.markdown(
        """
        <style>
        .st-key-bingo_live_banner_row,
        .st-key-bingo-live-banner-row {
            width: fit-content !important;
            max-width: min(100%, 1100px) !important;
            margin: 0 auto 0.75rem !important;
        }
        .st-key-bingo_live_banner_row [data-testid="stVerticalBlock"],
        .st-key-bingo-live-banner-row [data-testid="stVerticalBlock"] {
            width: 100% !important;
            gap: 0.9rem !important;
            align-items: center !important;
        }
        .st-key-bingo_live_banner_row [data-testid="stElementContainer"],
        .st-key-bingo-live-banner-row [data-testid="stElementContainer"] {
            margin: 0 auto !important;
            padding: 0 !important;
            width: fit-content !important;
            display: flex !important;
            justify-content: center !important;
        }
        .bingo-historical-banner {
            display: block;
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 1.55rem;
            font-weight: 800;
            color: rgba(234, 234, 234, 0.95);
            line-height: 1.3;
            white-space: nowrap;
            text-align: center;
            margin: 0;
            padding: 0;
        }
        .bingo-historical-banner span {
            color: #6eb0ff;
        }
        .bingo-live-return-marker { display: none; }
        .st-key-bingo_return_live,
        .st-key-bingo-return-live {
            width: fit-content !important;
            flex: 0 0 auto !important;
            margin: 0 auto !important;
        }
        .st-key-bingo_return_live [data-testid="stButton"],
        .st-key-bingo-return-live [data-testid="stButton"] {
            width: auto !important;
        }
        .st-key-bingo_return_live button,
        .st-key-bingo-return-live button {
            background-color: #008f68 !important;
            border-color: #008f68 !important;
            color: #ffffff !important;
            font-weight: 700 !important;
            width: auto !important;
            min-width: 0 !important;
            padding: 0.4rem 0.9rem !important;
            white-space: nowrap !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    banner_html = (
        f'Viewing <span>{html.escape(day_text)}</span> Board'
        if day_text == "Final"
        else f'Viewing board at end of <span>{html.escape(day_text)}</span>'
    )
    with st.container(key="bingo_live_banner_row"):
        st.markdown(
            f'<div class="bingo-historical-banner">{banner_html}</div>'
            '<span class="bingo-live-return-marker"></span>',
            unsafe_allow_html=True,
        )
        if show_live_button:
            st.markdown(
                '<div style="height:0.65rem;" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
            st.button(
                "Back to Live Board",
                key="bingo_return_live",
                type="primary",
                on_click=_on_bingo_return_live,
            )


def _resolve_bingo_view_day(
    completed_days: int,
    *,
    day_count: int,
) -> int | None:
    """Read the current day-view selection from session state (before rendering widgets)."""
    if completed_days < 1:
        st.session_state.bingo_view_day = None
        return None

    options = _bingo_view_options(
        completed_days=completed_days, day_count=day_count
    )
    default_label = options[-1] if completed_days >= day_count else "Live"
    label = st.session_state.get("bingo_board_view_control", default_label)
    if label not in options:
        label = default_label
        st.session_state.bingo_board_view_control = default_label
    view_day = _bingo_view_day_from_label(label, day_count=day_count)
    st.session_state.bingo_view_day = view_day
    return view_day


def _render_bingo_day_view_controls(
    completed_days: int,
    *,
    day_count: int,
) -> int | None:
    """Selector for live / day snapshots. Hidden until at least one day is complete."""
    if completed_days < 1:
        st.session_state.bingo_view_day = None
        return None

    options = _bingo_view_options(
        completed_days=completed_days, day_count=day_count
    )
    current_day = st.session_state.get("bingo_view_day")
    if current_day is not None:
        try:
            current_day = int(current_day)
        except (TypeError, ValueError):
            current_day = None
    if current_day is not None and not (1 <= current_day <= completed_days):
        current_day = None
        st.session_state.bingo_view_day = None

    default_label = _bingo_view_label(
        current_day,
        day_count=day_count,
        completed_days=completed_days,
    )
    if default_label not in options:
        default_label = options[-1] if completed_days >= day_count else "Live"
    if "bingo_board_view_control" not in st.session_state:
        st.session_state.bingo_board_view_control = default_label
    elif st.session_state.bingo_board_view_control not in options:
        st.session_state.bingo_board_view_control = default_label

    st.markdown(
        """
        <style>
        .st-key-bingo_view_controls_row,
        .st-key-bingo-view-controls-row {
            width: min(100%, 1100px) !important;
            margin: 0.75rem auto 0.35rem !important;
            display: flex !important;
            justify-content: center !important;
        }
        .st-key-bingo_view_controls_row [data-testid="stHorizontalBlock"],
        .st-key-bingo-view-controls-row [data-testid="stHorizontalBlock"] {
            width: auto !important;
            max-width: 100% !important;
            justify-content: center !important;
            align-items: center !important;
            gap: 0.55rem !important;
        }
        .bingo-board-view-label {
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 1.28rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            color: rgba(234, 234, 234, 0.88);
            white-space: nowrap;
            line-height: 1.2;
            position: relative;
            z-index: 2;
        }
        .st-key-bingo_board_view_control,
        .st-key-bingo-board-view-control {
            width: fit-content !important;
            margin: 0 3.25rem 0 0 !important;
            display: flex !important;
            justify-content: center !important;
            transform: scale(1.18);
            transform-origin: left center;
            position: relative;
            z-index: 1;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap="small",
        key="bingo_view_controls_row",
    ):
        st.markdown(
            '<div class="bingo-board-view-label">Board View:</div>',
            unsafe_allow_html=True,
        )
        selection = st.segmented_control(
            "Board view",
            options=options,
            key="bingo_board_view_control",
            label_visibility="collapsed",
        )
    view_day = _bingo_view_day_from_label(selection, day_count=day_count)
    st.session_state.bingo_view_day = view_day
    return view_day


def _bingo_board_snapshot_label(
    *,
    view_day: int | None,
    day_count: int,
) -> str:
    if view_day is None:
        return "Live board"
    if view_day >= day_count:
        return "Final Scores"
    return f"Scores at end of Day {view_day}"


def _build_bingo_chart_modal_payload(
    charts: list[BingoChart],
    entries_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    *,
    roster: dict[str, list[BingoTeamPlayer]],
) -> dict[str, dict[str, str]]:
    payload: dict[str, dict[str, str]] = {}
    for chart in charts:
        raw_entries = entries_by_chart.get((chart.song, chart.difficulty), [])
        entries = merge_chart_leaderboard_with_roster(roster, raw_entries)
        difficulty = html.escape(_difficulty_label(chart.difficulty, chart.level))
        key = f"{chart.row},{chart.column}"
        payload[key] = {
            "title_html": (
                f'{html.escape(chart.display_name)} '
                f'<span class="bingo-chart-modal-diff">{difficulty}</span>'
            ),
            "table_html": _render_bingo_chart_leaderboard_table_html(entries),
        }
    return payload


BINGO_CELL_SIZE = "12.75rem"


def _bingo_board_width_expr(*, rows: int) -> str:
    board_height = f"calc({rows} * {BINGO_CELL_SIZE})"
    return f"calc(1.15 * {board_height})"


def _bingo_board_component_css(*, cols: int, rows: int) -> str:
    board_width = _bingo_board_width_expr(rows=rows)
    board_height = f"calc({rows} * {BINGO_CELL_SIZE})"
    return f"""
    html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        overflow: hidden;
        width: 100%;
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
    }}
    body {{
        display: flex;
        justify-content: center;
        align-items: flex-start;
    }}
    .bingo-board-root {{
        width: {board_width};
        max-width: 100%;
        position: relative;
    }}
    .bingo-board-stage {{
        position: relative;
        width: 100%;
    }}
    .bingo-board-wrap {{
        width: 100%;
        overflow: visible;
    }}
    .bingo-board-shell {{
        width: 100%;
        margin: 0;
    }}
    .bingo-board {{
        display: grid;
        gap: 0;
        width: 100%;
        height: {board_height};
        margin: 0;
        box-sizing: border-box;
        border: 1px solid rgba(234, 234, 234, 0.22);
        background: {BINGO_PAGE_BG};
        align-items: stretch;
        grid-template-columns: repeat({cols}, minmax(0, 1fr));
        grid-template-rows: repeat({rows}, minmax(0, 1fr));
    }}
    .bingo-board-root.hide-lines .bingo-line-svg {{
        display: none !important;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell-mid,
    .bingo-board-root:not(.is-detailed) .bingo-cell-bot {{
        overflow: hidden;
        min-height: 0;
        opacity: 0;
        transform: translateY(-0.35rem);
        transition: opacity 0.22s ease, transform 0.22s ease;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell {{
        cursor: pointer;
        grid-template-rows: 1fr 0fr 0fr;
        place-items: stretch;
        transition: grid-template-rows 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell-top {{
        position: relative;
        min-height: 0;
        height: 100%;
        width: 100%;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell-header {{
        position: absolute;
        left: 0;
        right: 0;
        width: 100%;
        top: 50%;
        transform: translateY(-50%);
        transition: top 0.28s ease, transform 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell-song {{
        font-size: 1.05rem;
        -webkit-line-clamp: unset;
        transition: font-size 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell-diff {{
        font-size: 0.95rem;
        margin-top: 0.25rem;
        transition: font-size 0.28s ease, margin-top 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover {{
        z-index: 6;
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover .bingo-cell-mid,
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover .bingo-cell-bot {{
        opacity: 1;
        transform: translateY(0);
        transition-delay: 0.05s;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover .bingo-cell-top {{
        min-height: 3.5rem;
        height: auto;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover .bingo-cell-header {{
        top: 0;
        transform: translateY(0);
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover .bingo-cell-song {{
        font-size: 0.95rem;
        -webkit-line-clamp: 2;
    }}
    .bingo-board-root:not(.is-detailed) .bingo-cell:hover .bingo-cell-diff {{
        font-size: 0.88rem;
        margin-top: 0.1rem;
    }}
    .bingo-board-root.is-detailed .bingo-cell {{
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
        transition: grid-template-rows 0.28s ease;
    }}
    .bingo-board-root.is-detailed .bingo-cell-mid,
    .bingo-board-root.is-detailed .bingo-cell-bot {{
        opacity: 1;
        transform: translateY(0);
        transition: opacity 0.22s ease, transform 0.22s ease;
        transition-delay: 0.05s;
    }}
    .bingo-board-root.is-detailed .bingo-cell-top {{
        min-height: 3.5rem;
        height: auto;
    }}
    .bingo-board-root.is-detailed .bingo-cell-header {{
        position: absolute;
        left: 0;
        right: 0;
        width: 100%;
        top: 0;
        transform: translateY(0);
        transition: top 0.28s ease, transform 0.28s ease;
    }}
    .bingo-board-root.is-detailed .bingo-cell-song {{
        font-size: 0.95rem;
        -webkit-line-clamp: 2;
        transition: font-size 0.28s ease;
    }}
    .bingo-board-root.is-detailed .bingo-cell-diff {{
        font-size: 0.88rem;
        margin-top: 0.1rem;
        transition: font-size 0.28s ease, margin-top 0.28s ease;
    }}
    .bingo-cell {{
        --bingo-cell-bg: {BINGO_CELL_BG};
        position: relative;
        background: var(--bingo-cell-bg);
        color: #eaeaea;
        text-align: center;
        padding: 0.6rem 0.4rem 0.55rem;
        width: 100%;
        height: 100%;
        min-height: 0;
        display: grid;
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
        align-content: stretch;
        box-sizing: border-box;
        border: none;
        overflow: hidden;
        transition: grid-template-rows 0.28s ease;
    }}
    .bingo-cell-link {{
        cursor: pointer;
    }}
    .bingo-cell-link:focus-visible {{
        outline: none;
        box-shadow: inset 0 0 0 2px rgba(110, 176, 255, 0.85);
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
        cursor: default;
    }}
    .bingo-cell-top, .bingo-cell-header, .bingo-cell-bot, .bingo-cell-mid {{
        position: relative;
        z-index: 4;
        background: transparent;
    }}
    .bingo-cell-top {{
        min-height: 3.5rem;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        align-items: center;
    }}
    .bingo-cell-header {{ width: 100%; }}
    .bingo-cell-bot {{
        min-height: 2.15rem;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
    }}
    .bingo-cell-mid {{
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        align-items: center;
        min-height: 4.25rem;
        padding-top: 0.15rem;
        pointer-events: none;
    }}
    .bingo-cell-song {{
        font-size: 0.95rem;
        font-weight: 700;
        line-height: 1.15;
        width: 100%;
        color: #eaeaea;
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
        overflow: hidden;
    }}
    .bingo-cell-diff {{
        font-size: 0.88rem;
        font-weight: 400;
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
        box-sizing: border-box;
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
    .bingo-chart-modal-overlay {{
        position: absolute;
        inset: 0;
        z-index: 1000;
        align-items: center;
        justify-content: center;
        padding: 1.5rem;
        box-sizing: border-box;
    }}
    {_BINGO_CHART_MODAL_ANIMATION_CSS}
    .bingo-chart-modal-backdrop {{
        position: absolute;
        inset: 0;
        border: none;
        background: rgba(4, 8, 20, 0.72);
        cursor: pointer;
    }}
    .bingo-chart-modal-panel {{
        position: relative;
        z-index: 1;
        width: min(100%, 26rem);
        max-height: min(80vh, 760px);
        overflow: auto;
        background: #10162d;
        border: 1px solid rgba(234, 234, 234, 0.18);
        border-radius: 0.85rem;
        box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
        padding: 1.25rem 1.25rem 1.1rem;
        box-sizing: border-box;
    }}
    {_BINGO_CHART_MODAL_SCROLLBAR_CSS}
    .bingo-chart-modal-close {{
        position: absolute;
        top: 0.65rem;
        right: 0.75rem;
        border: none;
        background: transparent;
        color: rgba(234, 234, 234, 0.72);
        font-size: 1.65rem;
        line-height: 1;
        cursor: pointer;
        padding: 0.15rem 0.35rem;
    }}
    .bingo-chart-modal-close:hover {{ color: #ffffff; }}
    .bingo-chart-modal-title {{
        font-size: 1.35rem;
        font-weight: 800;
        color: #f5f5f5;
        margin: 0 2rem 0.2rem 0;
        line-height: 1.25;
    }}
    .bingo-chart-modal-diff {{
        font-weight: 400;
        color: rgba(234, 234, 234, 0.82);
    }}
    .bingo-chart-modal-subtitle {{
        font-size: 0.95rem;
        font-weight: 600;
        color: rgba(234, 234, 234, 0.62);
        margin: 0 0 1rem 0;
    }}
    .bingo-chart-modal-table {{
        width: 100%;
        border-collapse: collapse;
        color: #eaeaea;
    }}
    .bingo-chart-modal-table th,
    .bingo-chart-modal-table td {{
        padding: 0.55rem 0.75rem;
        border-bottom: 1px solid rgba(234, 234, 234, 0.14);
        text-align: left;
        vertical-align: middle;
    }}
    .bingo-chart-modal-table th {{
        font-size: 0.82rem;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: rgba(234, 234, 234, 0.58);
    }}
    .bingo-chart-modal-rank {{
        width: 2.2rem;
        color: rgba(234, 234, 234, 0.72);
        font-variant-numeric: tabular-nums;
    }}
    .bingo-chart-modal-player {{
        font-weight: 700;
        width: 11rem;
        max-width: 11rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}
    .bingo-chart-modal-score {{
        width: 6rem;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        text-align: right !important;
    }}
    .bingo-chart-modal-empty {{
        padding: 1.25rem 0.5rem;
        color: rgba(234, 234, 234, 0.72);
        font-size: 1rem;
        font-weight: 600;
    }}
    """


def _bingo_board_component_height(rows: int, cols: int) -> int:
    cell_px = 204
    _ = cols
    return max(260, rows * cell_px)


def _build_bingo_board_interactive_html(
    *,
    cells_html: list[str],
    cols: int,
    modal_payload: dict[str, dict[str, str]],
    snapshot_label: str,
    updated_ms: int | None,
) -> str:
    payload_json = json.dumps(modal_payload).replace("</", "<\\/")
    snapshot_json = json.dumps(snapshot_label)
    updated_ms_json = "null" if updated_ms is None else str(int(updated_ms))
    return f"""
        <div class="bingo-board-stage">
          <div class="bingo-board-shell">
            <div class="bingo-board-wrap">
              <div class="bingo-board" style="grid-template-columns: repeat({cols}, minmax(0, 1fr));">
                {"".join(cells_html)}
              </div>
            </div>
          </div>
          <div id="bingo-chart-modal" class="bingo-chart-modal-overlay" aria-hidden="true">
            <button type="button" class="bingo-chart-modal-backdrop" aria-label="Close chart leaderboard"></button>
            <div class="bingo-chart-modal-panel" role="dialog" aria-modal="true" aria-labelledby="bingo-chart-modal-title">
              <button type="button" class="bingo-chart-modal-close" aria-label="Close">&times;</button>
              <div id="bingo-chart-modal-title" class="bingo-chart-modal-title"></div>
              <div class="bingo-chart-modal-subtitle"></div>
              <div class="bingo-chart-modal-body"></div>
            </div>
          </div>
        </div>
        <script>
        (function () {{
          const root = document.getElementById("bingo-board-root");
          const modalData = {payload_json};
          const snapshotLabel = {snapshot_json};
          const updatedMs = {updated_ms_json};
          const modal = document.getElementById("bingo-chart-modal");
          const titleEl = modal.querySelector(".bingo-chart-modal-title");
          const subtitleEl = modal.querySelector(".bingo-chart-modal-subtitle");
          const bodyEl = modal.querySelector(".bingo-chart-modal-body");
          const backdropEl = modal.querySelector(".bingo-chart-modal-backdrop");
          const closeEl = modal.querySelector(".bingo-chart-modal-close");
          let lastFocused = null;
          let subtitleTimer = null;
          let closeTimer = null;
          const MODAL_ANIM_MS = 220;

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

          function updateSubtitle() {{
            if (updatedMs !== null) {{
              subtitleEl.textContent = "Scores as of " + formatAgo(updatedMs);
              return;
            }}
            subtitleEl.textContent = snapshotLabel;
          }}

          function syncBoardModes() {{
            let detailed = false;
            let hideLines = false;
            try {{
              const parentDoc = window.parent.document;
              detailed = !!parentDoc.querySelector(".bingo-detailed-toggle:checked");
              hideLines = !!parentDoc.querySelector(".bingo-lines-toggle:checked");
            }} catch (error) {{}}
            root.classList.toggle("is-detailed", detailed);
            root.classList.toggle("hide-lines", hideLines);
          }}

          function finishCloseModal() {{
            modal.classList.remove("is-closing");
            closeTimer = null;
            if (subtitleTimer !== null) {{
              clearInterval(subtitleTimer);
              subtitleTimer = null;
            }}
            bodyEl.innerHTML = "";
            if (lastFocused && typeof lastFocused.focus === "function") {{
              lastFocused.focus();
            }}
          }}

          function closeModal() {{
            if (!modal.classList.contains("is-open") || modal.classList.contains("is-closing")) {{
              return;
            }}
            modal.classList.add("is-closing");
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
            if (closeTimer !== null) {{
              clearTimeout(closeTimer);
            }}
            closeTimer = window.setTimeout(finishCloseModal, MODAL_ANIM_MS + 40);
          }}

          function openModal(row, col) {{
            const data = modalData[row + "," + col];
            if (!data) {{
              return;
            }}
            if (closeTimer !== null) {{
              clearTimeout(closeTimer);
              closeTimer = null;
            }}
            modal.classList.remove("is-closing");
            lastFocused = document.activeElement;
            titleEl.innerHTML = data.title_html || data.title || "";
            updateSubtitle();
            if (updatedMs !== null && subtitleTimer === null) {{
              subtitleTimer = setInterval(updateSubtitle, 1000);
            }}
            bodyEl.innerHTML = data.table_html;
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
            closeEl.focus();
          }}

          root.addEventListener("click", (event) => {{
            const cell = event.target.closest(".bingo-cell-link");
            if (!cell) {{
              return;
            }}
            event.preventDefault();
            event.stopPropagation();
            openModal(cell.dataset.row, cell.dataset.col);
          }});
          root.addEventListener("keydown", (event) => {{
            const cell = event.target.closest(".bingo-cell-link");
            if (!cell) {{
              return;
            }}
            if (event.key !== "Enter" && event.key !== " ") {{
              return;
            }}
            event.preventDefault();
            openModal(cell.dataset.row, cell.dataset.col);
          }});
          backdropEl.addEventListener("click", closeModal);
          closeEl.addEventListener("click", closeModal);
          document.addEventListener("keydown", (event) => {{
            if (event.key === "Escape" && modal.classList.contains("is-open")) {{
              closeModal();
            }}
          }});
          syncBoardModes();
          setInterval(syncBoardModes, 250);
          try {{
            const parentDoc = window.parent.document;
            parentDoc.addEventListener("change", syncBoardModes, true);
            parentDoc.addEventListener("click", syncBoardModes, true);
          }} catch (error) {{}}
        }})();
        </script>
        """


def _render_bingo_board_component(
    *,
    cells_html: list[str],
    cols: int,
    rows: int,
    modal_payload: dict[str, dict[str, str]],
    snapshot_label: str,
    updated_ms: int | None,
) -> None:
    inner_html = _build_bingo_board_interactive_html(
        cells_html=cells_html,
        cols=cols,
        modal_payload=modal_payload,
        snapshot_label=snapshot_label,
        updated_ms=updated_ms,
    )
    component_html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        + _bingo_board_component_css(cols=cols, rows=rows)
        + "</style></head><body>"
        + f'<div class="bingo-board-root" id="bingo-board-root">{inner_html}</div>'
        + "</body></html>"
    )
    components.html(
        component_html,
        height=_bingo_board_component_height(rows, cols),
        scrolling=False,
    )


def _render_bingo_chart_leaderboard_table_html(
    entries: list[BingoChartLeaderboardEntry],
) -> str:
    if not entries:
        return (
            '<div class="bingo-chart-modal-empty">'
            "No players are on the bingo roster yet."
            "</div>"
        )

    rows: list[str] = []
    rank = 0
    for index, entry in enumerate(entries):
        if index == 0 or entry.score != entries[index - 1].score:
            rank = index + 1
        team_color = TEAM_TEXT_COLORS.get(entry.team, "#eaeaea")
        player = html.escape(entry.display_name)
        score = html.escape(format_leader_score(entry.score))
        rows.append(
            "<tr>"
            f'<td class="bingo-chart-modal-rank">{rank}</td>'
            f'<td class="bingo-chart-modal-player" style="color:{team_color};">'
            f"{player}</td>"
            f'<td class="bingo-chart-modal-score">{score}</td>'
            "</tr>"
        )
    return (
        '<div class="bingo-chart-modal-table-wrap">'
        '<table class="bingo-chart-modal-table">'
        "<thead><tr>"
        '<th class="bingo-chart-modal-rank">#</th>'
        '<th class="bingo-chart-modal-player">Player</th>'
        '<th class="bingo-chart-modal-score">Score</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


@st.fragment
def _render_bingo_board_fragment(
    *,
    settings: BingoSettings,
    charts: list,
    completed_days: int,
) -> None:
    """Board body + day selector. Reruns alone when the day view changes."""
    _maybe_rerun_bingo_app()

    day_count = max(1, int(settings.day_count or 1))
    # Track live vs historical across runs. Do not rely on bingo_view_day alone —
    # Back to Live clears it in on_click before this fragment runs.
    prev_mode = st.session_state.get("bingo_board_mode", "live")
    view_day = _resolve_bingo_view_day(completed_days, day_count=day_count)
    mode = "historical" if view_day is not None else "live"
    if mode == "live" and prev_mode == "historical":
        st.session_state.bingo_board_mode = "live"
        _request_bingo_app_rerun()
        _maybe_rerun_bingo_app()
        return
    st.session_state.bingo_board_mode = mode
    show_live = completed_days < day_count

    banner_slot = st.empty()
    if view_day is not None:
        with banner_slot.container():
            _render_bingo_historical_banner(
                view_day,
                day_count=day_count,
                show_live_button=show_live,
            )
    else:
        banner_slot.empty()

    width = max(1, int(settings.board_width))
    end_time = (
        bingo_day_end(settings.start_time, view_day)
        if view_day is not None and settings.start_time is not None
        else None
    )
    standings_data = load_bingo_chart_standings_data(
        start_time=settings.start_time,
        end_time=end_time,
    )
    totals = {key: values[0] for key, values in standings_data.items()}
    player_bests = {key: values[1] for key, values in standings_data.items()}
    try:
        leaderboard_by_chart = load_all_bingo_chart_player_leaderboards(
            start_time=settings.start_time,
            end_time=end_time,
        )
    except Exception as exc:
        st.error(f"Failed to load chart leaderboards: {exc}")
        leaderboard_by_chart = {}

    groups_by_coord = {
        (chart.row, chart.column): chart.group for chart in charts
    }
    claim_owners = _group_claim_owners(charts, totals, player_bests)

    by_coord = {(chart.row, chart.column): chart for chart in charts}
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
                    rows=rows,
                    cols=cols,
                )
            )

    board_width = _bingo_board_width_expr(rows=rows)
    _inject_bingo_board_layout_css(board_width)
    modal_payload = _build_bingo_chart_modal_payload(
        charts,
        leaderboard_by_chart,
        roster=_cached_bingo_teams(),
    )
    updated_ms = (
        int(float(st.session_state.bingo_last_updated) * 1000)
        if view_day is None
        else None
    )
    with st.container(key="bingo_board_viewport"):
        _render_bingo_board_toolbar(show_refresh=view_day is None)
        _render_bingo_board_component(
            cells_html=cells_html,
            cols=cols,
            rows=rows,
            modal_payload=modal_payload,
            snapshot_label=_bingo_board_snapshot_label(
                view_day=view_day,
                day_count=day_count,
            ),
            updated_ms=updated_ms,
        )
    _render_bingo_day_view_controls(completed_days, day_count=day_count)
    highlight_day = view_day
    if highlight_day is None:
        highlight_day = bingo_in_progress_day(
            start_time=settings.start_time,
            day_count=day_count,
        )
    _inject_scoreboard_day_highlight(highlight_day)


def _commit_pending_bingo_submission() -> None:
    """Persist a queued manual score; caller should wrap with a spinner."""
    pending = st.session_state.pop("bingo_pending_submission", None)
    if not pending:
        st.session_state.bingo_submission_in_progress = False
        return
    ok, message = submit_bingo_score(
        player_id=pending["player_id"],
        song=pending["song"],
        difficulty=pending["difficulty"],
        score=int(pending["score"]),
    )
    st.session_state.bingo_submission_in_progress = False
    if ok:
        st.session_state.bingo_submit_success = message
        _touch_bingo_live_updated()
        _cached_bingo_charts.clear()
        _cached_bingo_teams.clear()
        _cached_bingo_claim_feed.clear()
    else:
        st.session_state.bingo_submit_error = message


def render_bingo_board() -> None:
    if not supabase_configured():
        st.warning("Supabase is not configured, so the Bingo board cannot load.")
        return

    _maybe_rerun_bingo_app()
    _consume_bingo_auto_refresh_query()

    live_view = st.session_state.get("bingo_view_day") is None
    if live_view and "bingo_last_updated" not in st.session_state:
        _touch_bingo_live_updated()

    saving = bool(st.session_state.get("bingo_submission_in_progress"))
    spinner = st.spinner("Saving score…") if saving else nullcontext()
    with spinner:
        if saving:
            _commit_pending_bingo_submission()

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

        _render_bingo_header(
            settings,
            live_view=live_view,
            updated_ms=(
                int(float(st.session_state.bingo_last_updated) * 1000)
                if live_view
                else None
            ),
        )

        if not charts:
            st.warning("No Bingo charts are configured yet.")
            return

        completed_days = 0
        if settings.start_time is not None and settings.day_count is not None:
            completed_days = completed_bingo_days(
                start_time=settings.start_time,
                day_count=int(settings.day_count),
            )

        st.markdown(build_bingo_board_css(), unsafe_allow_html=True)

        try:
            scoreboard = compute_bingo_scoreboard(settings=settings, charts=charts)
        except Exception as exc:
            st.error(f"Failed to load Bingo scoreboard: {exc}")
            scoreboard = None

        _render_bingo_board_fragment(
            settings=settings,
            charts=charts,
            completed_days=completed_days,
        )
        if scoreboard is not None:
            _render_bingo_scoreboard(
                scoreboard,
                live_view=st.session_state.get("bingo_view_day") is None,
            )
        _render_bingo_activity_feed(settings=settings)
        game_is_live = (
            bingo_in_progress_day(
                start_time=settings.start_time,
                day_count=settings.day_count,
            )
            is not None
        )
        if game_is_live:
            _render_bingo_manual_submission(
                charts=charts,
                teams=teams,
                settings=settings,
            )
        _render_bingo_teams(teams)
