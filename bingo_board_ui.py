"""Bingo Board UI for Streamlit."""

from __future__ import annotations

import base64
import html
import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

from rating.bingo import (
    BingoCellStanding,
    BingoChart,
    BingoChartLeaderboardEntry,
    BingoFinalStandings,
    BingoScoreboard,
    BingoSettings,
    BingoSquareClaimEvent,
    BingoTeamPlayer,
    TEAM_ORDER,
    bingo_charts_on_board,
    bingo_day_end,
    bingo_day_multiplier,
    bingo_has_started,
    bingo_in_progress_day,
    build_cell_standing,
    completed_bingo_days,
    compute_bingo_scoreboard,
    compute_bingo_final_standings,
    find_bingo_runs,
    format_leader_score,
    format_bingo_points,
    format_score_diff,
    group_claim_owners,
    bingo_chart_max_score,
    load_all_bingo_chart_player_leaderboards,
    load_bingo_chart_player_leaderboard,
    merge_chart_leaderboard_with_roster,
    load_bingo_chart_standings_data,
    load_bingo_charts,
    load_bingo_player_chart_best,
    load_bingo_settings,
    load_bingo_square_claim_feed,
    load_bingo_teams_by_ex_rating,
    clear_bingo_query_cache,
    submit_bingo_score,
)
from rating.bingo_chart_scoring import (
    ChartPlayerPointBreakdown,
    bingo_scoring_version,
    compute_chart_player_point_breakdowns,
)
from rating.bingo_upscore import build_chart_upscore_payload
from rating.calculator import ex_accuracy_percent
from rating.constants import SCORE_SOURCE_IN_GAME
from rating.bingo_proof_storage import prefetch_bingo_proof_signed_urls
from rating.constants import SCORE_SOURCE_IN_GAME, SCORE_SOURCE_SUBMISSION
from rating.formatting import format_difficulty_display_name
from rating.supabase_config import supabase_configured, supabase_storage_configured

# Slightly darker than the app background (#0c0e29).
BINGO_CELL_BG = "#07091a"
BINGO_PAGE_BG = "#0c0e29"
BINGO_DISPLAY_TZ = ZoneInfo("America/Los_Angeles")
BINGO_PLAYER_SELECT_PLACEHOLDER = "— Select a player —"
BINGO_CHART_SELECT_PLACEHOLDER = "— Select a chart —"
BINGO_SEARCH_LIMIT = 50
BINGO_ACTIVITY_FEED_LIMIT = 30
BINGO_ACTIVITY_FEED_VISIBLE_COUNT = 6
# Temporary: show manual submission panel before the game starts (for testing).
BINGO_MANUAL_SUBMISSION_FORCE_VISIBLE = False
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
TEAM_PLAYER_SCORES_ROW_BG = {
    "Eve": "#0c1528",
    "Grace": "#1a1016",
    "Rest": "#0c1814",
}
# bingo_charts."group" → outline color (1=Yellow, 2=Cyan, 3=Purple).
GROUP_BORDER_COLORS = {
    1: "#f5d547",
    2: "#3dd9f0",
    3: "#c084fc",
}
DEFAULT_CELL_BORDER = "1px solid rgba(234, 234, 234, 0.16)"
GROUP_BORDER_WIDTH = "3px"
REST_CLAIMED_WATERMARK_PATH = (
    Path(__file__).resolve().parent / "assets" / "bingo" / "rest-claimed-watermark.png"
)
TEAM_CLAIM_BORDER_WIDTH = "3px"


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bingo_charts():
    return load_bingo_charts()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bingo_teams():
    return load_bingo_teams_by_ex_rating()


BINGO_APP_RERUN_KEY = "bingo_app_rerun_requested"
BINGO_AUTO_REFRESH_STALE_SECONDS = 600


def _bingo_game_is_active(*, settings: BingoSettings) -> bool:
    """True while a competition day is currently in progress."""
    return (
        bingo_in_progress_day(
            start_time=settings.start_time,
            day_count=settings.day_count,
        )
        is not None
    )


def _bingo_game_has_ended(*, settings: BingoSettings) -> bool:
    if settings.start_time is None or settings.day_count is None:
        return False
    return (
        completed_bingo_days(
            start_time=settings.start_time,
            day_count=int(settings.day_count),
        )
        >= int(settings.day_count)
    )


def _bingo_supports_live_refresh(*, settings: BingoSettings) -> bool:
    """True before start or during active days — not after the game ends."""
    if settings.start_time is None or settings.day_count is None:
        return False
    if _bingo_game_is_active(settings=settings):
        return True
    return not bingo_has_started(start_time=settings.start_time)


def _request_bingo_app_rerun(*, touch_live: bool = True) -> None:
    """Queue a full-app rerun (must be consumed outside Streamlit callbacks)."""
    if touch_live:
        _touch_bingo_live_updated()
    _cached_bingo_charts.clear()
    _cached_bingo_teams.clear()
    clear_bingo_query_cache()
    st.session_state[BINGO_APP_RERUN_KEY] = True


def _maybe_rerun_bingo_app() -> None:
    if not st.session_state.pop(BINGO_APP_RERUN_KEY, False):
        return
    st.rerun(scope="app")


def _on_bingo_refresh() -> None:
    _request_bingo_app_rerun()


def _render_bingo_auto_refresh_trigger() -> None:
    """Hidden button clicked by the countdown iframe to match manual refresh."""
    st.markdown(
        """
        <style>
        .st-key-bingo_auto_refresh_trigger,
        .st-key-bingo-auto-refresh-trigger {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            overflow: hidden !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.button(
        "Auto refresh",
        key="bingo_auto_refresh_trigger",
        on_click=_on_bingo_refresh,
    )


def _touch_bingo_live_updated() -> None:
    """Reset the Live toolbar clock whenever live board data is (re)shown."""
    st.session_state.bingo_last_updated = time.time()
    st.session_state.bingo_live_updated_nonce = (
        int(st.session_state.get("bingo_live_updated_nonce", 0)) + 1
    )


def _difficulty_label(difficulty: str, level: int | None) -> str:
    diff = format_difficulty_display_name(difficulty)
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
        <div class="bingo-hidden-style-slot" aria-hidden="true"></div>
        <style>
        [data-testid="stElementContainer"]:has(.bingo-hidden-style-slot),
        .stElementContainer:has(.bingo-hidden-style-slot) {{
            display: none !important;
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            border: 0 !important;
            overflow: hidden !important;
        }}
        .st-key-bingo_board_viewport,
        .st-key-bingo-board-viewport {{
            width: min(100%, {board_width}) !important;
            max-width: 100% !important;
            margin: -0.85rem auto 0 !important;
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


def _player_chart_entry(
    chart: BingoChart,
    *,
    player_id: str,
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
) -> BingoChartLeaderboardEntry | None:
    entries = leaderboard_by_chart.get((chart.song, chart.difficulty), [])
    for entry in entries:
        if entry.player_id == player_id:
            return entry
    return None


def _player_chart_score(
    chart: BingoChart,
    *,
    player_id: str,
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
) -> int:
    entry = _player_chart_entry(
        chart,
        player_id=player_id,
        leaderboard_by_chart=leaderboard_by_chart,
    )
    return int(entry.score) if entry is not None else 0


def _player_crit_disabled_row_html(entry: BingoChartLeaderboardEntry | None) -> str:
    if entry is None or entry.source != SCORE_SOURCE_IN_GAME:
        return ""
    if entry.critical is None or entry.critical != 0:
        return ""
    return (
        '<div class="bingo-cell-crit-row">'
        '<span class="bingo-cell-crit-disabled">CRIT DISABLED</span>'
        "</div>"
    )


def _ordinal_rank(rank: int) -> str:
    if 11 <= (rank % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def _player_chart_placement_rank(
    chart: BingoChart,
    *,
    player_id: str,
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    roster: dict[str, list[BingoTeamPlayer]],
) -> int | None:
    entries = merge_chart_leaderboard_with_roster(
        roster,
        leaderboard_by_chart.get((chart.song, chart.difficulty), []),
    )
    players = {
        entry.player_id: (entry.team, int(entry.score)) for entry in entries
    }
    if player_id not in players:
        return None
    if int(players[player_id][1]) <= 0:
        return None
    breakdowns = compute_chart_player_point_breakdowns(
        song=chart.song,
        difficulty=chart.difficulty,
        players=players,
    )
    return int(breakdowns[player_id].rank)


def _format_player_chart_footer_label(
    chart: BingoChart,
    *,
    score: int,
    rank: int | None,
) -> str:
    max_score = bingo_chart_max_score(chart.song, chart.difficulty)
    if max_score is None or max_score <= 0:
        return "— - — Place"
    pct = ex_accuracy_percent(score, max_score)
    if rank is None or rank <= 0:
        return f"{pct:.2f}% - — Place"
    return f"{pct:.2f}% - {_ordinal_rank(rank)} Place"


def _player_block_html(*, team: str, score: int) -> str:
    if score <= 0:
        return (
            '<div class="bingo-cell-leader bingo-cell-leader--not-played">'
            '<div class="bingo-cell-leader-team bingo-cell-leader-team--spacer" aria-hidden="true">'
            "Personal Best"
            "</div>"
            '<div class="bingo-cell-leader-score">'
            '<span class="bingo-cell-not-played">Not Played</span>'
            "</div>"
            "</div>"
        )
    color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
    score_text = html.escape(format_leader_score(score))
    return (
        '<div class="bingo-cell-leader">'
        f'<div class="bingo-cell-leader-team" style="color:{color};">Personal Best</div>'
        f'<div class="bingo-cell-leader-score bingo-cell-player-score">{score_text}</div>'
        "</div>"
    )


def _player_footer_html(label: str) -> str:
    return (
        f'<div class="bingo-cell-player-footer">{html.escape(label)}</div>'
    )


def _build_bingo_player_board_payload(
    *,
    charts: list[BingoChart],
    teams: dict[str, list[BingoTeamPlayer]],
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
) -> dict[str, dict[str, dict[str, str | bool]]]:
    """Per-player cell overlay data for client-side Player Board updates."""
    payload: dict[str, dict[str, dict[str, str | bool]]] = {}
    for player in _flatten_bingo_players(teams):
        cells: dict[str, dict[str, str | bool]] = {}
        for chart in charts:
            entry = _player_chart_entry(
                chart,
                player_id=player.player_id,
                leaderboard_by_chart=leaderboard_by_chart,
            )
            score = int(entry.score) if entry is not None else 0
            not_played = score <= 0
            rank = _player_chart_placement_rank(
                chart,
                player_id=player.player_id,
                leaderboard_by_chart=leaderboard_by_chart,
                roster=teams,
            )
            footer_label = _format_player_chart_footer_label(
                chart,
                score=score,
                rank=rank,
            )
            cell: dict[str, str | bool] = {
                "mid_html": _player_block_html(team=player.team, score=score),
                "crit_html": _player_crit_disabled_row_html(entry),
                "not_played": not_played,
            }
            if not not_played:
                cell["footer_html"] = _player_footer_html(footer_label)
            cells[f"{chart.row},{chart.column}"] = cell
        payload[player.player_id] = cells
    return payload


def _render_bingo_player_view_controls(
    teams: dict[str, list[BingoTeamPlayer]],
    *,
    board_charts: list[BingoChart] | None = None,
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]]
    | None = None,
    leaders_by_chart: dict[tuple[str, str], str | None] | None = None,
) -> BingoTeamPlayer | None:
    """Search/select a player to enable the Player Board view."""
    players = _flatten_bingo_players(teams)
    st.markdown(
        """
        <div class="bingo-hidden-style-slot" aria-hidden="true"></div>
        <style>
        [data-testid="stElementContainer"]:has(.bingo-hidden-style-slot),
        .stElementContainer:has(.bingo-hidden-style-slot) {
            display: none !important;
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            border: 0 !important;
            overflow: hidden !important;
        }
        .st-key-bingo_player_view_shell {
            width: min(100%, 1100px);
            max-width: 28rem;
            margin: 1.25rem auto 0 !important;
        }
        .st-key-bingo_player_view_shell [data-testid="stHorizontalBlock"] {
            align-items: end !important;
            gap: 0.55rem !important;
        }
        .st-key-bingo_player_view_shell [data-testid="stElementContainer"] {
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_player_view_shell [data-testid="stTextInput"] input {
            font-size: 0.95rem !important;
        }
        .st-key-bingo_player_view_shell [data-testid="stSelectbox"] div[data-baseweb="select"] {
            font-size: 0.95rem !important;
        }
        .st-key-bingo_player_view_shell label[data-testid="stWidgetLabel"] {
            font-size: 0.95rem !important;
            margin-bottom: 0.2rem !important;
        }
        .st-key-bingo_player_view_shell [data-testid="stCustomComponentV1"] {
            margin: 0.35rem auto 0 !important;
            padding: 0 !important;
            width: 100% !important;
            max-width: 100% !important;
        }
        .st-key-bingo_player_view_shell iframe {
            width: 100% !important;
            max-width: 100% !important;
            border: none !important;
        }
        .bingo-view-player-id-marker { display: none; }
        .st-key-bingo_player_view_shell [data-testid="stElementContainer"]:has(.bingo-view-player-id-marker) {
            display: none !important;
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="bingo_player_view_shell"):
        search_col, select_col = st.columns([1, 1.15], gap="small")
        with search_col:
            player_search = st.text_input(
                "Search",
                placeholder="Search player…",
                key="bingo-board-player-search",
            ).strip()
        player_needle = player_search.casefold()
        if player_needle:
            player_matches = [
                player
                for player in players
                if player_needle in player.display_name.casefold()
            ]
        else:
            player_matches = list(players)
        player_matches = sorted(
            player_matches,
            key=lambda player: player.display_name.casefold(),
        )
        if player_needle:
            player_matches = player_matches[:BINGO_SEARCH_LIMIT]
        player_matches = _ensure_view_player_in_select_matches(
            players,
            player_matches,
            search_needle=player_needle,
        )
        player_options = [BINGO_PLAYER_SELECT_PLACEHOLDER] + [
            _bingo_player_option_label(player) for player in player_matches
        ]
        _presync_player_select_from_view_id(teams, player_options=player_options)
        select_key = "bingo-board-player-select"
        forced_search_placeholder = bool(
            player_needle
            and st.session_state.get(select_key) not in (None, BINGO_PLAYER_SELECT_PLACEHOLDER)
            and st.session_state.get(select_key) not in player_options
        )
        if forced_search_placeholder:
            st.session_state[select_key] = BINGO_PLAYER_SELECT_PLACEHOLDER
        with select_col:
            _auto_select_if_single_match(
                select_key="bingo-board-player-select",
                placeholder=BINGO_PLAYER_SELECT_PLACEHOLDER,
                matches=[
                    _bingo_player_option_label(player) for player in player_matches
                ],
                search_needle=player_search,
            )
            selected_option = st.selectbox(
                "Player",
                options=player_options,
                key="bingo-board-player-select",
                disabled=not player_matches,
            )
        selected_player = _find_bingo_player(
            players,
            option_label=selected_option,
        )
        saved_player_id = st.session_state.get("bingo_view_player_id")
        if selected_option == BINGO_PLAYER_SELECT_PLACEHOLDER:
            if forced_search_placeholder:
                selected_player = _resolve_bingo_view_player(teams)
            else:
                st.session_state.pop("bingo_view_player_id", None)
                st.session_state.pop("bingo_auto_enable_player_board", None)
                selected_player = None
        elif selected_player is not None:
            if saved_player_id != selected_player.player_id:
                st.session_state["bingo_auto_enable_player_board"] = True
            st.session_state["bingo_view_player_id"] = selected_player.player_id
        elif saved_player_id:
            selected_player = _resolve_bingo_view_player(teams)
            if selected_player is None:
                st.session_state.pop("bingo_view_player_id", None)
                st.session_state.pop("bingo_auto_enable_player_board", None)
        if (
            selected_player is not None
            and board_charts
            and leaderboard_by_chart is not None
            and leaders_by_chart is not None
        ):
            _render_bingo_player_scores_launch(
                player=selected_player,
                board_charts=board_charts,
                teams=teams,
                leaderboard_by_chart=leaderboard_by_chart,
                leaders_by_chart=leaders_by_chart,
            )
        auto_enable_player_board = bool(
            st.session_state.pop("bingo_auto_enable_player_board", False)
        )
        marker_player_id = ""
        marker_player_team = ""
        if selected_player is not None:
            marker_player_id = html.escape(selected_player.player_id, quote=True)
            marker_player_team = html.escape(selected_player.team, quote=True)
        auto_attr = "1" if auto_enable_player_board else "0"
        st.markdown(
            f'<span class="bingo-view-player-id-marker" '
            f'data-player-id="{marker_player_id}" '
            f'data-player-team="{marker_player_team}" '
            f'data-auto-player-board="{auto_attr}" hidden></span>',
            unsafe_allow_html=True,
        )
        _inject_scoreboard_player_row_highlight(
            selected_player.team if selected_player is not None else None
        )
        return selected_player


_BINGO_BOARD_TOGGLE_JS = """
(function () {
  const parentWin = window.parent;
  const doc = parentWin.document;
  const KEYS = {
    hideColors: "bingo_hide_colors",
    hideLines: "bingo_hide_lines",
    detailed: "bingo_detailed_board",
    playerBoard: "bingo_player_board",
  };

  function toggles() {
    return {
      hideColors: doc.querySelector(".bingo-colors-toggle"),
      hideLines: doc.querySelector(".bingo-lines-toggle"),
      detailed: doc.querySelector(".bingo-detailed-toggle"),
      playerBoard: doc.querySelector(".bingo-player-board-toggle"),
      container: doc.querySelector(".bingo-board-controls-toolbar"),
      viewPlayerMarker: doc.querySelector(".bingo-view-player-id-marker"),
    };
  }

  function syncViewPlayer() {
    const { playerBoard, detailed, viewPlayerMarker } = toggles();
    if (!playerBoard) {
      return;
    }
    const playerId = viewPlayerMarker?.dataset.playerId || "";
    const hasPlayer = !!playerId;
    const label = playerBoard.closest(".bingo-board-toggle-label");
    playerBoard.disabled = !hasPlayer;
    if (label) {
      label.classList.toggle("is-disabled", !hasPlayer);
    }
    if (!hasPlayer) {
      playerBoard.checked = false;
      sessionStorage.setItem(KEYS.playerBoard, "0");
      return;
    }
    if (viewPlayerMarker?.dataset.autoPlayerBoard === "1") {
      viewPlayerMarker.dataset.autoPlayerBoard = "0";
      playerBoard.checked = true;
      if (detailed) {
        detailed.checked = false;
      }
      sessionStorage.setItem(KEYS.playerBoard, "1");
    }
  }

  function saveState() {
    const { hideColors, hideLines, detailed, playerBoard } = toggles();
    if (hideColors) {
      sessionStorage.setItem(KEYS.hideColors, hideColors.checked ? "1" : "0");
    }
    if (hideLines) {
      sessionStorage.setItem(KEYS.hideLines, hideLines.checked ? "1" : "0");
    }
    if (detailed) {
      sessionStorage.setItem(KEYS.detailed, detailed.checked ? "1" : "0");
    }
    if (playerBoard && !playerBoard.disabled) {
      sessionStorage.setItem(KEYS.playerBoard, playerBoard.checked ? "1" : "0");
    }
  }

  function enforceExclusive() {
    const { detailed, playerBoard } = toggles();
    if (!detailed || !playerBoard || playerBoard.disabled) {
      return;
    }
    if (detailed.checked && playerBoard.checked) {
      playerBoard.checked = false;
    }
  }

  function restoreState(container) {
    const { hideColors, hideLines, detailed, playerBoard } = toggles();
    if (!hideColors || !hideLines || !detailed || !playerBoard) {
      return;
    }
    syncViewPlayer();
    if (sessionStorage.getItem(KEYS.hideColors) !== null) {
      hideColors.checked = sessionStorage.getItem(KEYS.hideColors) === "1";
    }
    if (sessionStorage.getItem(KEYS.hideLines) !== null) {
      hideLines.checked = sessionStorage.getItem(KEYS.hideLines) === "1";
    }
    if (sessionStorage.getItem(KEYS.detailed) !== null) {
      detailed.checked = sessionStorage.getItem(KEYS.detailed) === "1";
    }
    if (!playerBoard.disabled && sessionStorage.getItem(KEYS.playerBoard) !== null) {
      playerBoard.checked = sessionStorage.getItem(KEYS.playerBoard) === "1";
    }
    if (container && container.dataset.autoPlayerBoard === "1") {
      if (!playerBoard.disabled) {
        playerBoard.checked = true;
        detailed.checked = false;
      }
      container.dataset.autoPlayerBoard = "0";
    }
    enforceExclusive();
    saveState();
  }

  function onToggleChange(event) {
    const target = event.target;
    const { detailed, playerBoard } = toggles();
    if (target.matches(".bingo-detailed-toggle")) {
      if (target.checked && playerBoard && !playerBoard.disabled) {
        playerBoard.checked = false;
      }
    } else if (target.matches(".bingo-player-board-toggle")) {
      if (target.checked && detailed) {
        detailed.checked = false;
      }
    }
    enforceExclusive();
    saveState();
  }

  function boot() {
    const { container } = toggles();
    if (!container || container.dataset.togglesReady === "1") {
      return;
    }
    container.dataset.togglesReady = "1";
    restoreState(container);
  }

  if (!parentWin.__bingoBoardToggleListeners) {
    parentWin.__bingoBoardToggleListeners = true;
    doc.addEventListener("change", onToggleChange, true);
  }
  if (!parentWin.__bingoBoardToggleBooted) {
    parentWin.__bingoBoardToggleBooted = true;
    boot();
    setInterval(boot, 400);
    setInterval(() => {
      syncViewPlayer();
      enforceExclusive();
      saveState();
    }, 250);
  } else {
    boot();
  }
})();
"""


def _render_bingo_board_toggle_script(*, embed_in_last_updated: bool = False) -> str:
    """Return toggle boot JS; optionally as a second script block for iframe embedding."""
    if embed_in_last_updated:
        return f"<script>{_BINGO_BOARD_TOGGLE_JS}</script>"
    return _BINGO_BOARD_TOGGLE_JS


def _mount_bingo_board_toggle_script() -> None:
    """Zero-height iframe in the toolbar row (never below it — that adds vertical gap)."""
    components.html(
        f"<script>{_BINGO_BOARD_TOGGLE_JS}</script>",
        height=0,
        scrolling=False,
    )


def _render_bingo_board_toolbar(
    *,
    show_refresh: bool = True,
) -> None:
    if show_refresh:
        if "bingo_last_updated" not in st.session_state:
            _touch_bingo_live_updated()
        updated_ms = int(float(st.session_state.bingo_last_updated) * 1000)
        updated_nonce = int(st.session_state.get("bingo_live_updated_nonce", 0))
    else:
        updated_ms = 0
        updated_nonce = 0

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
        .st-key-bingo_refresh_row .st-key-bingo_toggle_boot,
        .st-key-bingo-refresh-row .st-key-bingo_toggle_boot,
        .st-key-bingo_refresh_row .st-key-bingo-toggle-boot,
        .st-key-bingo-refresh-row .st-key-bingo-toggle-boot {
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
            flex: 0 0 0 !important;
        }
        .st-key-bingo_refresh_row .st-key-bingo_toggle_boot iframe,
        .st-key-bingo-refresh-row .st-key-bingo_toggle_boot iframe,
        .st-key-bingo_refresh_row .st-key-bingo-toggle-boot iframe,
        .st-key-bingo-refresh-row .st-key-bingo-toggle-boot iframe {
            width: 0 !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            border: none !important;
            display: block !important;
        }
        .bingo-board-controls-toolbar {
            padding-bottom: 0.8rem !important;
            margin: 0 !important;
            width: auto !important;
            min-height: 1.7rem;
            flex-wrap: nowrap !important;
            gap: 1.15rem !important;
        }
        .bingo-board-controls-toolbar .bingo-board-toggle-label {
            white-space: nowrap;
            flex-shrink: 0;
            font-size: 1.05rem;
            gap: 0.45rem;
        }
        .bingo-board-controls-toolbar .bingo-board-toggle-label span {
            white-space: nowrap;
        }
        .bingo-board-toggle-label.is-disabled {
            opacity: 0.42;
            cursor: not-allowed;
        }
        .bingo-board-toggle-label.is-disabled span {
            color: rgba(234, 234, 234, 0.45);
        }
        .bingo-board-toggle:disabled {
            cursor: not-allowed;
            opacity: 0.55;
        }
        .bingo-toolbar-marker { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([0.85, 1.15], gap="small")
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
                        {_render_bingo_board_toggle_script(embed_in_last_updated=True)}
                        """,
                        height=28,
                        width=360,
                    )
            else:
                with st.container(key="bingo_toggle_boot"):
                    _mount_bingo_board_toggle_script()
    with right:
        st.markdown(
            """
            <div class="bingo-board-controls bingo-board-controls-toolbar">
              <label class="bingo-board-toggle-label">
                <input type="checkbox" class="bingo-board-toggle bingo-colors-toggle" />
                <span>Hide Colors</span>
              </label>
              <label class="bingo-board-toggle-label">
                <input type="checkbox" class="bingo-board-toggle bingo-lines-toggle" />
                <span>Hide Bingo Lines</span>
              </label>
              <label class="bingo-board-toggle-label">
                <input type="checkbox" class="bingo-board-toggle bingo-detailed-toggle" />
                <span>Detailed Board</span>
              </label>
              <label class="bingo-board-toggle-label is-disabled">
                <input type="checkbox"
                  class="bingo-board-toggle bingo-player-board-toggle"
                  disabled />
                <span>Player Board</span>
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


def _bingo_podium_html(standings: BingoFinalStandings) -> str:
    lines: list[str] = []
    for place, team in ((2, standings.second), (3, standings.third)):
        if not team:
            continue
        label = "2nd." if place == 2 else "3rd."
        color = html.escape(TEAM_TEXT_COLORS.get(team, "#eaeaea"))
        team_name = html.escape(team)
        lines.append(
            f'<div class="bingo-countdown-podium-line">'
            f'<span class="bingo-countdown-podium-rank">{label} </span>'
            f'<span class="bingo-countdown-podium-team" style="color:{color};">'
            f"Team {team_name}</span></div>"
        )
    return "".join(lines)


def _render_bingo_countdown(
    settings: BingoSettings,
    *,
    live_view: bool,
    updated_ms: int | None = None,
    final_standings: BingoFinalStandings | None = None,
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
    winner_team = final_standings.first if final_standings else None
    winner_color = (
        TEAM_TEXT_COLORS.get(final_standings.first, "#eaeaea")
        if final_standings
        else None
    )
    winner_team_json = json.dumps(winner_team)
    winner_color_json = json.dumps(winner_color)
    day_multipliers_json = json.dumps(
        [bingo_day_multiplier(day, day_count) for day in range(1, day_count + 1)]
    )

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
          const winnerTeam = {winner_team_json};
          const winnerColor = {winner_color_json};
          const dayMultipliers = {day_multipliers_json};
          const labelEl = document.getElementById("bingo-countdown-label");
          const timerEl = document.getElementById("bingo-countdown-timer");

          function pad(n) {{
            return String(n).padStart(2, "0");
          }}

          function isGracePeriodDay(dayIndex) {{
            const multiplier = dayMultipliers[dayIndex - 1];
            return multiplier === 0;
          }}

          function dayEndsLabel(dayIndex) {{
            if (dayIndex >= dayCount) {{
              return "Final Day Ends:";
            }}
            if (isGracePeriodDay(dayIndex)) {{
              return "Day " + dayIndex + " / " + dayCount + " (Grace Period) Ends:";
            }}
            return "Day " + dayIndex + " / " + dayCount + " Ends:";
          }}

          function formatRemaining(ms) {{
            const totalSeconds = Math.max(0, Math.floor(ms / 1000));
            const days = Math.floor(totalSeconds / 86400);
            const hours = Math.floor((totalSeconds % 86400) / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = totalSeconds % 60;
            return days + "d " + pad(hours) + "h " + pad(minutes) + "m " + pad(seconds) + "s";
          }}

          function findAutoRefreshButton(doc) {{
            const selectors = [
              ".st-key-bingo_auto_refresh_trigger button",
              ".st-key-bingo-auto-refresh-trigger button",
            ];
            for (const selector of selectors) {{
              const button = doc.querySelector(selector);
              if (button) {{
                return button;
              }}
            }}
            return null;
          }}

          function clickAutoRefreshButton() {{
            try {{
              const button = findAutoRefreshButton(window.parent.document);
              if (button) {{
                button.click();
                return true;
              }}
            }} catch (error) {{}}
            return false;
          }}

          function triggerAutoRefresh(storageKey, reason) {{
            try {{
              if (sessionStorage.getItem(storageKey) === "1") {{
                return;
              }}
              sessionStorage.setItem(storageKey, "1");
            }} catch (error) {{}}

            if (clickAutoRefreshButton()) {{
              return;
            }}

            let attempts = 0;
            const retry = setInterval(() => {{
              attempts += 1;
              if (clickAutoRefreshButton() || attempts >= 50) {{
                clearInterval(retry);
              }}
            }}, 200);
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

          function showWinnerMessage() {{
            if (winnerTeam) {{
              timerEl.textContent = "Team " + winnerTeam + " Wins!";
              timerEl.style.color = winnerColor || "#eaeaea";
              timerEl.style.fontVariantNumeric = "normal";
              return;
            }}
            timerEl.textContent = "0d 00h 00m 00s";
            timerEl.style.color = "#eaeaea";
            timerEl.style.fontVariantNumeric = "tabular-nums";
          }}

          function showCountdownRemaining(ms) {{
            timerEl.textContent = formatRemaining(ms);
            timerEl.style.color = "#eaeaea";
            timerEl.style.fontVariantNumeric = "tabular-nums";
          }}

          function tick() {{
            const now = Date.now();
            const gameEndMs = startMs + dayCount * dayMs;

            if (now < startMs) {{
              labelEl.textContent = "Game Starts:";
              showCountdownRemaining(startMs - now);
              return;
            }}

            if (now >= gameEndMs) {{
              labelEl.textContent = "Game Ended";
              showWinnerMessage();
              return;
            }}

            const dayIndex = Math.floor((now - startMs) / dayMs) + 1;
            const dayEndMs = startMs + dayIndex * dayMs;
            labelEl.textContent = dayEndsLabel(dayIndex);
            showCountdownRemaining(dayEndMs - now);
          }}

          tick();
          setInterval(tick, 1000);
          scheduleAutoRefresh();
        </script>
        """,
        height=86,
    )


def _render_bingo_final_podium(standings: BingoFinalStandings) -> None:
    if not standings.second and not standings.third:
        return
    podium_html = _bingo_podium_html(standings)
    st.markdown(
        f"""
        <style>
        .bingo-header-podium {{
            display: flex;
            justify-content: center;
            align-items: baseline;
            gap: 2.25rem;
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            margin-top: 0.35rem;
            margin-bottom: 2.00rem;
        }}
        .bingo-countdown-podium-line {{
            font-size: 1.35rem;
            font-weight: 800;
            line-height: 1.25;
            letter-spacing: 0.02em;
            white-space: nowrap;
        }}
        .bingo-countdown-podium-rank {{
            color: #ffffff;
        }}
        </style>
        <div class="bingo-header-podium">{podium_html}</div>
        """,
        unsafe_allow_html=True,
    )


def _render_bingo_header(
    settings: BingoSettings,
    *,
    live_view: bool,
    updated_ms: int | None = None,
    final_standings: BingoFinalStandings | None = None,
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
            final_standings=final_standings,
        )
        if final_standings is not None:
            _render_bingo_final_podium(final_standings)
        st.markdown(
            '<span class="bingo-header-end-marker" style="display:none;"></span>',
            unsafe_allow_html=True,
        )


def _cell_background(standing: BingoCellStanding) -> str:
    if standing.leader is None:
        return BINGO_CELL_BG
    return TEAM_CELL_BACKGROUNDS.get(standing.leader, BINGO_CELL_BG)


@lru_cache(maxsize=1)
def _rest_claimed_watermark_data_url() -> str:
    encoded = base64.b64encode(REST_CLAIMED_WATERMARK_PATH.read_bytes()).decode("ascii")
    return f"url(data:image/png;base64,{encoded})"


def _bingo_rest_claimed_watermark_css() -> str:
    image = _rest_claimed_watermark_data_url()
    return f"""
    .bingo-cell--team-rest::before {{
        content: "";
        position: absolute;
        inset: 0;
        z-index: 1;
        pointer-events: none;
        background: {image} center / contain no-repeat;
        opacity: 0.02;
    }}
    .bingo-board-root.hide-colors .bingo-cell--team-rest::before {{
        opacity: 0;
    }}
    """


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
    if bingo_scoring_version() == "v2":
        score_text = html.escape(format_bingo_points(standing.leader_score))
    else:
        score_text = html.escape(format_leader_score(int(standing.leader_score)))
    return (
        '<div class="bingo-cell-leader">'
        f'<div class="bingo-cell-leader-team" style="color:{color};">{team_text}</div>'
        f'<div class="bingo-cell-leader-score">{score_text}</div>'
        "</div>"
    )


def _trailers_block_html(standing: BingoCellStanding) -> str:
    if standing.leader is None and standing.leader_score <= 0:
        trailers: list[tuple[str, float]] = []
    else:
        trailers = list(standing.trailers[:2])

    while len(trailers) < 2:
        trailers.append(("", 0.0))

    use_v2_points = bingo_scoring_version() == "v2"
    parts: list[str] = []
    for index, (team, diff) in enumerate(trailers):
        split_class = " bingo-cell-trailer-split" if index else ""
        if team:
            team_color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
            if use_v2_points:
                label = html.escape(format_bingo_points(-float(diff)))
            else:
                label = html.escape(format_score_diff(int(diff)))
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
    view_player: BingoTeamPlayer | None = None,
    player_score: int | None = None,
    player_max_score_label: str | None = None,
    player_crit_row_html: str = "",
    player_board_ready: bool = False,
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
    if player_board_ready or view_player is not None:
        if view_player is not None:
            player_score_val = int(player_score or 0)
            not_played = player_score_val <= 0
            player_view_class = "bingo-cell-view bingo-cell-player-view"
            if not_played:
                player_view_class += " bingo-cell-player-view--not-played"
            player_bot_html = ""
            if not not_played:
                player_bot_html = (
                    f'<div class="bingo-cell-bot">'
                    f"{_player_footer_html(player_max_score_label or '— - — Place')}"
                    "</div>"
                )
            body_class = "bingo-cell-body"
            if not_played:
                body_class += " bingo-cell-body--player-not-played"
            player_inner = (
                f'<div class="bingo-cell-mid">{_player_block_html(team=view_player.team, score=player_score_val)}</div>'
                f"{player_crit_row_html}"
                f"{player_bot_html}"
            )
        else:
            body_class = "bingo-cell-body"
            player_view_class = "bingo-cell-view bingo-cell-player-view"
            player_inner = ""
        body_html = (
            f'<div class="{body_class}">'
            '<div class="bingo-cell-view bingo-cell-team-view">'
            f'<div class="bingo-cell-mid">{_leader_block_html(standing)}</div>'
            f'<div class="bingo-cell-bot">{_trailers_block_html(standing)}</div>'
            "</div>"
            f'<div class="{player_view_class}">{player_inner}</div>'
            "</div>"
        )
    else:
        body_html = (
            f'<div class="bingo-cell-mid">{_leader_block_html(standing)}</div>'
            f'<div class="bingo-cell-bot">{_trailers_block_html(standing)}</div>'
        )
    cell_classes = "bingo-cell bingo-cell-link"
    if standing.leader == "Rest":
        cell_classes += " bingo-cell--team-rest"
    return (
        f'<div class="{cell_classes}" role="button" tabindex="0"'
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
        f"{body_html}"
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

_BINGO_CHART_MODAL_TABLE_LAYOUT_CSS = """
    .bingo-chart-modal-table-wrap {
        overflow-x: auto;
        max-width: 100%;
    }
    .bingo-chart-modal-table {
        width: max-content;
        max-width: 100%;
        border-collapse: collapse;
    }
    .bingo-chart-modal-table th.bingo-chart-modal-points {
        overflow: visible;
    }
"""

_BINGO_CHART_JUDGEMENT_EXPAND_CSS = """
    .bingo-chart-modal-data-row.bingo-chart-modal-row--expandable {
        cursor: pointer;
        transition: background-color 0.14s ease;
    }
    .bingo-chart-modal-data-row.bingo-chart-modal-row--expandable:hover td {
        background: rgba(255, 255, 255, 0.045);
    }
    .bingo-chart-modal-data-row.bingo-chart-modal-row--expandable.is-expanded td {
        background: rgba(255, 255, 255, 0.06);
        border-bottom-color: transparent;
    }
    .bingo-chart-modal-data-row.bingo-chart-modal-row--expandable .bingo-chart-modal-player {
        position: relative;
        padding-right: 1.15rem;
    }
    .bingo-chart-modal-data-row.bingo-chart-modal-row--expandable .bingo-chart-modal-player::after {
        content: "";
        position: absolute;
        right: 0.15rem;
        top: 50%;
        width: 0.42rem;
        height: 0.42rem;
        border-right: 2px solid rgba(234, 234, 234, 0.45);
        border-bottom: 2px solid rgba(234, 234, 234, 0.45);
        transform: translateY(-65%) rotate(45deg);
        transition: transform 0.22s ease, border-color 0.14s ease;
    }
    .bingo-chart-modal-data-row.bingo-chart-modal-row--expandable.is-expanded .bingo-chart-modal-player::after {
        transform: translateY(-35%) rotate(225deg);
        border-color: rgba(110, 176, 255, 0.85);
    }
    .bingo-chart-modal-detail-row td {
        padding: 0 !important;
        border-bottom: 1px solid rgba(234, 234, 234, 0.14);
        background: rgba(8, 12, 28, 0.55);
    }
    .bingo-chart-modal-detail-row.is-open td {
        border-bottom-color: rgba(234, 234, 234, 0.14);
    }
    .bingo-chart-modal-detail-panel {
        overflow: hidden;
        max-height: 0;
        opacity: 0;
        transform: translateY(-0.35rem);
        transition:
            max-height 0.28s ease,
            opacity 0.22s ease,
            transform 0.28s ease,
            padding 0.28s ease;
        padding: 0 0.85rem;
        box-sizing: border-box;
    }
    .bingo-chart-modal-detail-row.is-open .bingo-chart-modal-detail-panel {
        max-height: 5.5rem;
        opacity: 1;
        transform: translateY(0);
        padding: 0.4rem 0.65rem 0.55rem;
    }
    .bingo-judgement-stats {
        display: flex;
        flex-wrap: nowrap;
        justify-content: space-between;
        align-items: stretch;
        gap: 0.25rem;
    }
    .bingo-judgement-stat {
        display: flex;
        flex-direction: column;
        gap: 0.05rem;
        min-width: 0;
        flex: 1 1 0;
        text-align: center;
    }
    .bingo-judgement-stat-label {
        font-size: 0.6rem;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        line-height: 1.05;
    }
    .bingo-judgement-stat-value {
        font-size: 0.9rem;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        line-height: 1.1;
    }
    .bingo-judgement-empty {
        font-size: 0.88rem;
        font-weight: 600;
        color: rgba(234, 234, 234, 0.58);
        padding: 0.15rem 0;
    }
    .bingo-judgement-submitted {
        margin-top: 0.4rem;
        text-align: center;
        font-size: 0.72rem;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.82);
        line-height: 1.2;
    }
"""

_BINGO_CHART_MODAL_SUBTITLE_CSS = """
    .bingo-chart-modal-subtitle-row {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        margin: 0 0 1rem 0;
        min-height: 1.25rem;
    }
    .bingo-chart-modal-subtitle-row .bingo-chart-modal-subtitle {
        margin: 0;
        flex: 1 1 auto;
        min-width: 0;
    }
    .bingo-chart-modal-refresh-btn {
        flex: 0 0 auto;
        width: 1.2rem;
        height: 1.2rem;
        padding: 0;
        margin: 0;
        border: none;
        border-radius: 999px;
        background: #008f68;
        color: #ffffff;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: background-color 0.14s ease, opacity 0.14s ease;
    }
    .bingo-chart-modal-refresh-btn:hover:not(:disabled) {
        background: #007a58;
    }
    .bingo-chart-modal-refresh-btn:disabled {
        opacity: 0.55;
        cursor: wait;
    }
    .bingo-chart-modal-refresh-btn svg {
        width: 0.78rem;
        height: 0.78rem;
        display: block;
    }
    .bingo-chart-modal-refresh-btn.is-spinning svg {
        animation: bingo-chart-modal-refresh-spin 0.75s linear infinite;
    }
    @keyframes bingo-chart-modal-refresh-spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
"""

_BINGO_PLAYER_SCORES_TABLE_CSS = """
    .bingo-player-scores-modal .bingo-chart-modal-panel {
        width: min(100%, 40rem);
    }
    .bingo-player-scores-table {
        table-layout: fixed;
        width: 100%;
        max-width: 100%;
    }
    .bingo-player-scores-table .bingo-player-scores-col-chart {
        width: auto;
    }
    .bingo-player-scores-table .bingo-player-scores-col-score {
        width: 8.75rem;
    }
    .bingo-player-scores-table .bingo-player-scores-col-pct {
        width: 5.25rem;
    }
    .bingo-player-scores-table .bingo-player-scores-col-placement {
        width: 7.25rem;
    }
    .bingo-player-scores-table .bingo-player-scores-chart {
        overflow: hidden;
        max-width: 0;
    }
    .bingo-player-scores-chart-name {
        font-weight: 700;
        color: #eaeaea;
        line-height: 1.2;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .bingo-player-scores-chart-diff {
        margin-top: 0.12rem;
        font-size: 0.82rem;
        font-weight: 600;
        color: rgba(234, 234, 234, 0.62);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .bingo-player-scores-table .bingo-chart-modal-score {
        text-align: right;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .bingo-player-scores-table th.bingo-player-scores-pct,
    .bingo-player-scores-table th.bingo-player-scores-placement {
        text-align: center !important;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        padding-left: 0.35rem;
        padding-right: 0.35rem;
        letter-spacing: 0.02em;
    }
    .bingo-player-scores-table td.bingo-player-scores-pct,
    .bingo-player-scores-table td.bingo-player-scores-placement {
        text-align: center !important;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        padding-left: 0.35rem;
        padding-right: 0.35rem;
    }
    .bingo-player-scores-table th.bingo-chart-modal-score {
        text-align: right;
    }
"""

_BINGO_CHART_MODAL_POINTS_COLUMN_CSS = """
    .bingo-chart-modal-accuracy {
        width: 5.75rem;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        text-align: center !important;
        white-space: nowrap;
        color: rgba(234, 234, 234, 0.82);
    }
    .bingo-chart-modal-table th.bingo-chart-modal-accuracy {
        text-align: center !important;
    }
    .bingo-chart-modal-points {
        width: 7.25rem;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        text-align: center !important;
        white-space: nowrap;
        border-left: 1px solid rgba(234, 234, 234, 0.22);
        padding-left: 0.65rem !important;
        padding-right: 0.35rem !important;
    }
    .bingo-chart-modal-table th.bingo-chart-modal-points {
        border-left: 1px solid rgba(234, 234, 234, 0.22);
        padding-left: 0.65rem !important;
        padding-right: 0.35rem !important;
        text-align: center !important;
        text-transform: none;
        letter-spacing: normal;
        overflow: visible;
    }
    .bingo-chart-modal-points-head {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.35rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .bingo-chart-modal-help-wrap {
        position: relative;
        display: inline-flex;
        align-items: center;
        text-transform: none;
        letter-spacing: normal;
    }
    .bingo-chart-modal-help-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1rem;
        height: 1rem;
        padding: 0;
        border: 1px solid rgba(234, 234, 234, 0.28);
        border-radius: 999px;
        background: rgba(234, 234, 234, 0.08);
        color: rgba(234, 234, 234, 0.58);
        font-size: 0.68rem;
        font-weight: 800;
        line-height: 1;
        cursor: help;
        text-transform: none;
    }
    .bingo-chart-modal-help-btn:hover,
    .bingo-chart-modal-help-btn:focus-visible {
        color: rgba(234, 234, 234, 0.95);
        border-color: rgba(234, 234, 234, 0.45);
        outline: none;
    }
    .bingo-chart-modal-help-tip {
        display: none;
        position: absolute;
        top: calc(100% + 0.4rem);
        right: 0;
        left: auto;
        transform: none;
        width: max-content;
        max-width: 12rem;
        padding: 0.45rem 0.6rem;
        border-radius: 0.45rem;
        border: 1px solid rgba(234, 234, 234, 0.18);
        background: #182038;
        color: rgba(234, 234, 234, 0.92);
        font-size: 0.72rem;
        font-weight: 600;
        line-height: 1.35;
        text-transform: none;
        letter-spacing: normal;
        white-space: normal;
        text-align: left;
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
        z-index: 5;
    }
    .bingo-chart-modal-help-wrap.is-open .bingo-chart-modal-help-tip {
        display: block;
    }
    .bingo-chart-modal-points-bonus {
        font-weight: 600;
        color: rgba(234, 234, 234, 0.45);
    }
"""

_BINGO_CHART_UPSCORE_CSS = """
    .bingo-chart-modal-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 0.75rem;
        margin: 0 2.2rem 0.2rem 0;
    }
    .bingo-chart-modal-title {
        margin: 0 !important;
        flex: 1 1 auto;
        min-width: 0;
    }
    .bingo-chart-modal-upscore-btn {
        flex: 0 0 auto;
        border: 1px solid rgba(110, 176, 255, 0.42);
        background: rgba(110, 176, 255, 0.12);
        color: #9ec8ff;
        border-radius: 999px;
        padding: 0.35rem 0.8rem;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        line-height: 1.2;
        cursor: pointer;
        white-space: nowrap;
    }
    .bingo-chart-modal-upscore-btn:hover,
    .bingo-chart-modal-upscore-btn.is-active {
        background: rgba(110, 176, 255, 0.22);
        color: #d7eaff;
        border-color: rgba(110, 176, 255, 0.62);
    }
    .bingo-chart-modal-upscore-panel {
        overflow: hidden;
        max-height: 0;
        opacity: 0;
        margin-bottom: 0;
        transition: max-height 0.28s ease, opacity 0.22s ease, margin-bottom 0.28s ease;
    }
    .bingo-chart-modal-upscore-panel.is-open {
        max-height: 48rem;
        opacity: 1;
        margin-bottom: 1rem;
        overflow: visible;
    }
    .bingo-chart-modal-upscore-inner {
        border: 1px solid rgba(234, 234, 234, 0.14);
        border-radius: 0.65rem;
        background: rgba(255, 255, 255, 0.03);
        padding: 0.85rem 0.95rem 1.1rem;
    }
    .bingo-upscore-player-picker {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.55rem;
        margin-bottom: 0.85rem;
    }
    .bingo-upscore-player-picker input,
    .bingo-upscore-player-picker select {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid rgba(234, 234, 234, 0.18);
        border-radius: 0.45rem;
        background: rgba(8, 12, 28, 0.85);
        color: #eaeaea;
        padding: 0.45rem 0.6rem;
        font-size: 0.88rem;
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
    }
    .bingo-upscore-player-name {
        font-size: 0.95rem;
        font-weight: 700;
        margin-bottom: 0.65rem;
    }
    .bingo-upscore-metrics {
        display: flex;
        justify-content: center;
        align-items: flex-start;
        gap: 3.75rem;
        margin-bottom: 0.85rem;
        font-size: 1.08rem;
    }
    .bingo-upscore-metrics > div {
        text-align: center;
    }
    .bingo-upscore-metrics dt {
        margin: 0;
        color: rgba(234, 234, 234, 0.58);
        font-weight: 700;
        font-size: 1.08rem;
    }
    .bingo-upscore-metrics dd {
        margin: 0.15rem 0 0;
        font-size: 1.08rem;
        font-weight: 800;
        color: #f5f5f5;
        font-variant-numeric: tabular-nums;
    }
    .bingo-upscore-slider-label {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 0.75rem;
        font-size: 1.08rem;
        font-weight: 700;
        color: rgba(234, 234, 234, 0.72);
        margin-bottom: 0.35rem;
    }
    .bingo-upscore-slider-label span:last-child {
        color: #f5f5f5;
        font-variant-numeric: tabular-nums;
    }
    .bingo-upscore-slider-wrap {
        position: relative;
        width: 100%;
        margin: 0 0 0.85rem;
        box-sizing: border-box;
    }
    .bingo-upscore-slider {
        width: 100%;
        margin: 0;
        accent-color: #6eb0ff;
        display: block;
        position: relative;
        z-index: 2;
    }
    .bingo-upscore-slider-marker {
        position: absolute;
        top: 50%;
        transform: translate(-50%, -50%);
        width: 0;
        height: 1.45rem;
        border-left: 2px dashed rgba(234, 234, 234, 0.62);
        pointer-events: none;
        z-index: 1;
    }
    .bingo-upscore-results {
        border-top: 1px solid rgba(234, 234, 234, 0.12);
        padding-top: 0.75rem;
        font-size: 1.08rem;
    }
    .bingo-upscore-required-row {
        display: flex;
        justify-content: center;
        align-items: flex-start;
        gap: 3.75rem;
        margin-bottom: 0.75rem;
    }
    .bingo-upscore-required-item {
        margin: 0;
        text-align: center;
    }
    .bingo-upscore-required-item dt {
        margin: 0;
        color: rgba(234, 234, 234, 0.58);
        font-weight: 700;
        font-size: 1.08rem;
    }
    .bingo-upscore-changes-title {
        margin: 0;
        color: rgba(234, 234, 234, 0.58);
        font-weight: 700;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        font-size: 1.08rem;
    }
    .bingo-upscore-required-item dd {
        margin: 0.2rem 0 0;
        font-size: 1.08rem;
        font-weight: 800;
        color: #f5f5f5;
        font-variant-numeric: tabular-nums;
    }
    .bingo-upscore-placement-climb {
        font-size: 1.08rem;
        font-weight: 700;
        color: #5ee09a;
        margin-left: 0.35rem;
    }
    .bingo-upscore-required-points-diff {
        font-size: 1.08rem;
        font-weight: 800;
        color: #5ee09a;
        margin-left: 0.2rem;
    }
    .bingo-upscore-required-points-diff.is-negative {
        color: #ff7a84;
    }
    .bingo-upscore-required-points-diff.is-neutral {
        color: rgba(234, 234, 234, 0.72);
    }
    .bingo-upscore-changes-title {
        margin: 1.45rem 0 0.5rem;
        text-align: center;
    }
    .bingo-upscore-changes {
        display: flex;
        justify-content: center;
    }
    .bingo-upscore-changes-table {
        width: auto;
        border-collapse: separate;
        border-spacing: 0 0.4rem;
        table-layout: fixed;
        font-size: 1.08rem;
    }
    .bingo-upscore-changes-table col.bingo-upscore-col-team {
        width: 4.25rem;
    }
    .bingo-upscore-changes-table col.bingo-upscore-col-delta {
        width: 3.1rem;
    }
    .bingo-upscore-changes-table col.bingo-upscore-col-arrow {
        width: 1.65rem;
    }
    .bingo-upscore-changes-table col.bingo-upscore-col-total {
        width: 3.35rem;
    }
    .bingo-upscore-changes-table td {
        padding: 0.5rem 0.35rem;
        font-variant-numeric: tabular-nums;
        vertical-align: middle;
        white-space: nowrap;
    }
    .bingo-upscore-changes-table td:first-child {
        border-radius: 0.4rem 0 0 0.4rem;
        font-weight: 700;
        text-align: left;
    }
    .bingo-upscore-changes-table td:last-child {
        border-radius: 0 0.4rem 0.4rem 0;
        text-align: right;
    }
    .bingo-upscore-change-delta {
        text-align: right;
        font-weight: 800;
    }
    .bingo-upscore-change-arrow {
        text-align: center;
        font-size: 1.35rem;
        line-height: 1;
        font-weight: 900;
        color: rgba(234, 234, 234, 0.82);
    }
    .bingo-upscore-change-total {
        display: inline-block;
        text-align: right;
        font-weight: 800;
    }
    .bingo-upscore-change-total.is-leader {
        font-weight: 900;
        text-shadow: 0 0 10px currentColor;
        box-shadow: inset 0 0 0 1px color-mix(in srgb, currentColor 55%, transparent);
        border-radius: 0.35rem;
        padding: 0.06rem 0.28rem;
        background: color-mix(in srgb, currentColor 14%, transparent);
    }
    .bingo-upscore-change-delta.is-positive {
        color: #5ee09a;
    }
    .bingo-upscore-change-delta.is-negative {
        color: #ff7a84;
    }
    .bingo-upscore-change-delta.is-neutral {
        color: #f5f5f5;
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
        flex-wrap: nowrap;
        gap: 1.15rem;
        margin: 0;
        padding: 0;
    }}
    .bingo-board-controls-toolbar {{
        padding: 0 0 0.8rem 0 !important;
        margin: 0 !important;
        width: auto !important;
        min-height: 1.7rem;
        flex-wrap: nowrap !important;
        gap: 1.15rem !important;
    }}
    .bingo-board-toggle-label {{
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        cursor: pointer;
        user-select: none;
        font-size: 1.05rem;
        font-weight: 700;
        color: rgba(234, 234, 234, 0.95);
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
        line-height: 1.15;
        white-space: nowrap;
        flex-shrink: 0;
    }}
    .bingo-board-toggle-label span {{
        white-space: nowrap;
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
        opacity: 0 !important;
        visibility: hidden !important;
        transition: opacity 0.14s ease, visibility 0s linear 0.14s !important;
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
        width: fit-content;
        max-width: min(calc(100vw - 3rem), 40rem);
        max-height: min(80vh, 760px);
        overflow-x: auto;
        overflow-y: auto;
        background: #10162d;
        border: 1px solid rgba(234, 234, 234, 0.18);
        border-radius: 0.85rem;
        box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
        padding: 1.25rem 1.25rem 1.1rem;
        box-sizing: border-box;
    }}
    .bingo-chart-completions-modal .bingo-chart-modal-panel {{
        width: min(100%, 960px);
    }}
    .bingo-point-counts-modal .bingo-chart-modal-panel {{
        width: min(100%, 960px);
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
    {_BINGO_CHART_MODAL_SUBTITLE_CSS}
    .bingo-chart-modal-subtitle {{
        font-size: 0.95rem;
        font-weight: 600;
        color: rgba(234, 234, 234, 0.62);
        font-family: "Source Sans Pro", "Segoe UI", sans-serif;
    }}
    {_BINGO_CHART_MODAL_TABLE_LAYOUT_CSS}
    {_BINGO_CHART_JUDGEMENT_EXPAND_CSS}
    .bingo-chart-modal-table {{
        width: max-content;
        max-width: 100%;
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
        width: 11rem;
        max-width: 11rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
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
    {_BINGO_CHART_MODAL_POINTS_COLUMN_CSS}
    {_BINGO_CHART_UPSCORE_CSS}
    .bingo-chart-modal-proof-col {{
        width: 2rem;
        min-width: 2rem;
        text-align: center !important;
        padding-left: 0.2rem !important;
        padding-right: 0.35rem !important;
    }}
    .bingo-chart-modal-table th.bingo-chart-modal-proof-col {{
        color: transparent;
        font-size: 0;
        user-select: none;
    }}
    .bingo-chart-modal-table tbody tr.bingo-chart-modal-row--highlighted td {{
        background: rgba(255, 255, 255, 0.085);
    }}
    .bingo-chart-modal-proof-badge,
    .bingo-chart-modal-proof-btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.15rem;
        height: 1.15rem;
        flex: 0 0 auto;
        border-radius: 999px;
        box-sizing: border-box;
    }}
    .bingo-chart-modal-proof-badge {{
        font-size: 0.72rem;
        font-weight: 800;
        line-height: 1;
    }}
    .bingo-chart-modal-proof-badge--ingame {{
        background: rgba(94, 224, 154, 0.22);
        color: #5ee09a;
        border: 1px solid rgba(94, 224, 154, 0.55);
    }}
    .bingo-chart-modal-proof-badge--missing {{
        background: rgba(245, 213, 71, 0.14);
        color: rgba(245, 213, 71, 0.92);
        border: 1px solid rgba(245, 213, 71, 0.38);
    }}
    .bingo-chart-modal-proof-btn {{
        padding: 0;
        border: 1px solid rgba(110, 176, 255, 0.42);
        background: rgba(110, 176, 255, 0.14);
        color: #9ec8ff;
        cursor: pointer;
    }}
    .bingo-chart-modal-proof-btn:hover {{
        background: rgba(110, 176, 255, 0.24);
        color: #d7eaff;
    }}
    .bingo-chart-modal-proof-btn svg {{
        width: 0.78rem;
        height: 0.78rem;
        display: block;
    }}
    .bingo-proof-modal-overlay {{
        position: fixed;
        inset: 0;
        z-index: 1000001;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        pointer-events: none;
        transition: opacity 180ms ease;
    }}
    .bingo-proof-modal-overlay.is-open {{
        opacity: 1;
        pointer-events: auto;
    }}
    .bingo-proof-modal-backdrop {{
        position: absolute;
        inset: 0;
        border: 0;
        background: rgba(4, 8, 18, 0.82);
        cursor: pointer;
        z-index: 0;
    }}
    .bingo-proof-modal-panel {{
        position: relative;
        z-index: 2;
        max-width: min(92vw, 960px);
        max-height: min(88vh, 920px);
        padding: 0.75rem;
        border-radius: 0.75rem;
        border: 1px solid rgba(120, 190, 255, 0.24);
        background: rgba(12, 18, 36, 0.96);
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
    }}
    .bingo-proof-modal-close {{
        position: absolute;
        top: 0.35rem;
        right: 0.45rem;
        border: 0;
        background: transparent;
        color: rgba(245, 245, 245, 0.72);
        font-size: 1.5rem;
        line-height: 1;
        cursor: pointer;
    }}
    .bingo-proof-modal-close:hover {{
        color: #ffffff;
    }}
    .bingo-proof-modal-image {{
        display: block;
        max-width: min(88vw, 920px);
        max-height: min(82vh, 860px);
        width: auto;
        height: auto;
        margin: 0 auto;
        border-radius: 0.35rem;
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
        opacity: 1;
        visibility: visible;
        transition: opacity 0.14s ease, visibility 0s linear 0s;
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


def _inject_scoreboard_day_highlight(
    highlight_day: int | None,
    *,
    day_count: int,
) -> None:
    """Update scoreboard column highlight via CSS only (table itself stays mounted)."""
    if highlight_day is None:
        rule = ""
    else:
        day = int(highlight_day)
        edge = "rgba(234, 234, 234, 0.5)"
        fill = (
            "linear-gradient(rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.04))"
        )
        multiplier_golden = _bingo_scoreboard_multiplier_highlight_days(
            day,
            day_count=day_count,
        )
        multiplier_golden_css = ""
        if multiplier_golden:
            selectors = ",\n        ".join(
                ".bingo-scoreboard thead .bingo-sb-multiplier[data-day="
                f'"{golden_day}"]'
                for golden_day in sorted(multiplier_golden)
            )
            multiplier_golden_css = f"""
        {selectors} {{
          color: rgba(245, 213, 71, 0.96) !important;
          font-weight: 800 !important;
        }}
        """
        rule = f"""
        .bingo-scoreboard thead tr:not(.bingo-sb-multiplier-row) th[data-day="{day}"] {{
          color: #ffffff !important;
          font-weight: 800 !important;
          background-image: {fill} !important;
          box-shadow:
            inset 2px 0 0 0 {edge},
            inset -2px 0 0 0 {edge},
            inset 0 2px 0 0 {edge} !important;
        }}
        {multiplier_golden_css}
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
        .bingo-scoreboard thead tr:not(.bingo-sb-multiplier-row) th[data-day] {{
          color: rgba(234, 234, 234, 0.88) !important;
          font-weight: 700 !important;
        }}
        {rule}
        </style>
        """,
        unsafe_allow_html=True,
    )


_SCOREBOARD_PLAYER_ROW_BG = {
    "Eve": "#152842",
    "Grace": "#2a1a22",
    "Rest": "#152a20",
}


def _inject_scoreboard_player_row_highlight(highlight_team: str | None) -> None:
    """Highlight the selected player's team row on the daily scoreboard."""
    if highlight_team is None or highlight_team not in _SCOREBOARD_PLAYER_ROW_BG:
        rule = ""
    else:
        team = html.escape(highlight_team)
        row_bg = _SCOREBOARD_PLAYER_ROW_BG[highlight_team]
        rule = f"""
        .bingo-scoreboard tbody tr[data-team="{team}"] th,
        .bingo-scoreboard tbody tr[data-team="{team}"] td {{
          background-color: {row_bg} !important;
        }}
        """
    # Style-only slot: hide the Streamlit element so it doesn't add vertical gap
    # between player controls and the board.
    st.markdown(
        f"""
        <div class="bingo-hidden-style-slot" aria-hidden="true"></div>
        <style>
        [data-testid="stElementContainer"]:has(.bingo-hidden-style-slot),
        .stElementContainer:has(.bingo-hidden-style-slot) {{
          display: none !important;
          height: 0 !important;
          min-height: 0 !important;
          margin: 0 !important;
          padding: 0 !important;
          border: 0 !important;
          overflow: hidden !important;
        }}
        {rule}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _bingo_scoreboard_multiplier_label(day: int, *, day_count: int) -> str:
    multiplier = bingo_day_multiplier(day, day_count)
    if day > 1:
        previous = bingo_day_multiplier(day - 1, day_count)
        if multiplier == previous:
            return "→"
    return f"×{multiplier}"


def _bingo_scoreboard_multiplier_highlight_days(
    highlight_day: int,
    *,
    day_count: int,
) -> set[int]:
    """Days in the multiplier row to show golden for the selected column."""
    day = int(highlight_day)
    multiplier = bingo_day_multiplier(day, day_count)
    if multiplier <= 1:
        if _bingo_scoreboard_multiplier_label(day, day_count=day_count):
            return {day}
        return set()
    start = day
    while start > 1 and bingo_day_multiplier(start - 1, day_count) == multiplier:
        start -= 1
    golden: set[int] = set()
    for candidate in range(start, day + 1):
        if _bingo_scoreboard_multiplier_label(candidate, day_count=day_count):
            golden.add(candidate)
    return golden


def _bingo_scoreboard_multiplier_headers_html(*, day_count: int) -> str:
    cells: list[str] = []
    for day in range(1, day_count + 1):
        label = _bingo_scoreboard_multiplier_label(day, day_count=day_count)
        if not label:
            cells.append(
                f'<th class="bingo-sb-multiplier bingo-sb-multiplier--empty" '
                f'data-day="{day}" scope="col"></th>'
            )
        elif label == "→":
            cells.append(
                f'<th class="bingo-sb-multiplier bingo-sb-multiplier--repeat" '
                f'data-day="{day}" scope="col" '
                'aria-label="Same multiplier as previous day">→</th>'
            )
        else:
            cells.append(
                f'<th class="bingo-sb-multiplier bingo-sb-multiplier--value" '
                f'data-day="{day}" scope="col">{html.escape(label)}</th>'
            )
    return (
        '<tr class="bingo-sb-multiplier-row">'
        '<th class="bingo-sb-team bingo-sb-multiplier-label" scope="col"></th>'
        f'{"".join(cells)}'
        '<th class="bingo-sb-runs bingo-sb-multiplier-label" scope="col"></th>'
        "</tr>"
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
    multiplier_headers_html = _bingo_scoreboard_multiplier_headers_html(
        day_count=scoreboard.day_count
    )
    rows_html: list[str] = []
    scoreboard_row_bg = {
        "Eve": "#0c1528",
        "Grace": "#1a1016",
        "Rest": "#0c1814",
    }
    prospective_day = scoreboard.prospective_day if live_view else None
    totals_are_prospective = live_view and prospective_day is not None
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
        if totals_are_prospective and prospective_day is not None:
            prospective_value = scoreboard.daily_points.get(team, [])[
                prospective_day - 1
            ]
            if prospective_value is not None:
                total += int(prospective_value)
        total_class = "bingo-sb-total"
        if totals_are_prospective:
            total_class += " bingo-sb-prospective"
        rows_html.append(
            f'<tr data-team="{html.escape(team)}">'
            f'<th class="bingo-sb-team" scope="row" style="color:{color};background:{row_bg};">'
            f"{html.escape(team.upper())}</th>"
            f'{"".join(cells)}'
            f'<td class="{total_class}" style="background:{row_bg};">'
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
          .bingo-scoreboard thead tr.bingo-sb-multiplier-row th {{
            box-shadow: none !important;
            border-top: none !important;
            border-left: none !important;
            border-right: none !important;
            border-bottom: 1px solid rgba(234, 234, 234, 0.14) !important;
            color: rgba(234, 234, 234, 0.52);
            vertical-align: middle !important;
            padding-top: 0.35rem !important;
            padding-bottom: 0.35rem !important;
          }}
          .bingo-scoreboard thead tr.bingo-sb-multiplier-row .bingo-sb-runs {{
            border-left: none !important;
          }}
          .bingo-sb-multiplier {{
            width: 4.15rem;
            min-width: 4.15rem;
            max-width: 4.15rem;
            box-sizing: border-box;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            line-height: 1;
          }}
          .bingo-sb-multiplier--value,
          .bingo-sb-multiplier--repeat {{
            color: rgba(234, 234, 234, 0.36);
          }}
          .bingo-sb-multiplier--repeat {{
            font-size: 0.82rem;
            font-weight: 600;
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
          .bingo-sb-score.bingo-sb-prospective,
          .bingo-sb-total.bingo-sb-prospective {{
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
                {multiplier_headers_html}
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


def _bingo_activity_timestamp_ms(value: datetime) -> int:
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return int(moment.astimezone(timezone.utc).timestamp() * 1000)


def _bingo_activity_time_html(created_at: datetime) -> str:
    moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
    moment_utc = moment.astimezone(timezone.utc)
    event_ms = _bingo_activity_timestamp_ms(created_at)
    time_ago = _format_bingo_time_ago(created_at)
    seconds = max(0, int((datetime.now(timezone.utc) - moment_utc).total_seconds()))
    date_attr = ""
    if seconds >= 7 * 24 * 3600:
        date_label = moment.astimezone(BINGO_DISPLAY_TZ).strftime("%b %d, %Y")
        date_attr = f' data-date-label="{html.escape(date_label)}"'
    return (
        f'<span class="bingo-activity-time" data-ts="{event_ms}"{date_attr}>'
        f"{html.escape(time_ago)}</span>"
    )


_BINGO_ACTIVITY_TIME_TICKER_JS = """
(function () {
  function formatBingoActivityTimeAgo(ms, dateLabel) {
    if (dateLabel) {
      return dateLabel;
    }
    const seconds = Math.max(0, Math.floor((Date.now() - ms) / 1000));
    if (seconds < 45) {
      return "just now";
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
      return minutes === 1 ? "1 minute ago" : minutes + " minutes ago";
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
      return hours === 1 ? "1 hour ago" : hours + " hours ago";
    }
    const days = Math.floor(hours / 24);
    if (days < 7) {
      return days === 1 ? "1 day ago" : days + " days ago";
    }
    return dateLabel || "";
  }

  function tickActivityTimes() {
    let doc;
    try {
      doc = window.parent.document;
    } catch (error) {
      return;
    }
    doc.querySelectorAll(".bingo-activity-time[data-ts]").forEach(function (el) {
      const ms = Number(el.getAttribute("data-ts"));
      if (!Number.isFinite(ms)) {
        return;
      }
      const dateLabel = el.getAttribute("data-date-label") || "";
      el.textContent = formatBingoActivityTimeAgo(ms, dateLabel);
    });
  }

  tickActivityTimes();
  const parentWindow = window.parent;
  if (parentWindow.__bingoActivityTimeTicker) {
    clearInterval(parentWindow.__bingoActivityTimeTicker);
  }
  parentWindow.__bingoActivityTimeTicker = setInterval(tickActivityTimes, 1000);
})();
"""


def _mount_bingo_activity_time_ticker() -> None:
    components.html(
        f"<script>{_BINGO_ACTIVITY_TIME_TICKER_JS}</script>",
        height=0,
        scrolling=False,
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


def _render_bingo_impact_cell(team: str, delta: int, *, variant: str) -> str:
    team_color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
    label = f"+{delta}" if delta > 0 else str(delta)
    return (
        f'<div class="bingo-activity-impact bingo-activity-impact--{variant}" '
        f'style="color:{team_color};" title="{html.escape(team)}">'
        f"{html.escape(label)}</div>"
    )


def _render_bingo_point_impacts_html(
    point_impacts: tuple[tuple[str, int], ...],
) -> str:
    if not point_impacts:
        return '<div class="bingo-activity-impacts"></div>'

    gainers = [(team, delta) for team, delta in point_impacts if delta > 0]
    losers = [(team, delta) for team, delta in point_impacts if delta < 0]

    rows: list[str] = []
    for team, delta in gainers:
        rows.append(
            '<div class="bingo-activity-impact-row bingo-activity-impact-row--gain">'
            f"{_render_bingo_impact_cell(team, delta, variant='gain')}"
            "</div>"
        )
    if len(losers) == 1:
        team, delta = losers[0]
        rows.append(
            '<div class="bingo-activity-impact-row bingo-activity-impact-row--loss">'
            f"{_render_bingo_impact_cell(team, delta, variant='loss')}"
            "</div>"
        )
    elif len(losers) >= 2:
        loss_cells = "".join(
            _render_bingo_impact_cell(team, delta, variant="loss")
            for team, delta in losers
        )
        rows.append(
            '<div class="bingo-activity-impact-row bingo-activity-impact-row--loss">'
            f"{loss_cells}"
            "</div>"
        )

    layout_class = (
        "bingo-activity-impacts--split"
        if len(losers) >= 2
        else "bingo-activity-impacts--single"
    )
    return (
        f'<div class="bingo-activity-impacts {layout_class}">{"".join(rows)}</div>'
    )


def _render_bingo_claim_feed_item(event: BingoSquareClaimEvent) -> str:
    receiving_team = event.team
    player_team = getattr(event, "player_team", None) or receiving_team
    name_color = TEAM_TEXT_COLORS.get(player_team, "#eaeaea")
    row_color = TEAM_TEXT_COLORS.get(receiving_team, "#eaeaea")
    tint = TEAM_ACTIVITY_TINTS.get(receiving_team, "rgba(234, 234, 234, 0.06)")
    player = html.escape(event.player_display_name)
    chart = html.escape(
        f"{event.chart_display_name} "
        f"[{format_difficulty_display_name(event.difficulty)}]"
    )
    time_html = _bingo_activity_time_html(event.created_at)
    if event.prev_team is None:
        action = f'claimed <span class="bingo-activity-chart">{chart}</span>'
    elif player_team != receiving_team:
        prev_color = TEAM_TEXT_COLORS.get(event.prev_team, "#eaeaea")
        prev = html.escape(event.prev_team.upper())
        to_color = TEAM_TEXT_COLORS.get(receiving_team, "#eaeaea")
        to_team = html.escape(receiving_team.upper())
        action = (
            f'flipped <span class="bingo-activity-chart">{chart}</span> from '
            f'<span class="bingo-activity-team" style="color:{prev_color};">{prev}</span>'
            f' to '
            f'<span class="bingo-activity-team" style="color:{to_color};">{to_team}</span>'
        )
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
        f"border-left-color:{row_color};"
        f"background:linear-gradient(90deg,{tint} 0%,rgba(10,18,36,0.28) 42%,rgba(10,18,36,0.18) 100%);"
        '">'
        f'<span class="bingo-activity-player" style="color:{name_color};" '
        f'title="{html.escape(player_team)}">{player}</span>'
        f'<span class="bingo-activity-action">{action}{badges_html}</span>'
        f"{_render_bingo_point_impacts_html(event.point_impacts)}"
        f"{time_html}"
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
            --bingo-activity-impacts-width-single: 2.1rem;
            --bingo-activity-impacts-width-split: 2.9rem;
            --bingo-activity-time-width: 5.5rem;
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
            grid-template-columns:
              minmax(5.5rem, 8.5rem)
              minmax(0, 1fr)
              auto
              var(--bingo-activity-time-width);
            align-items: stretch;
            column-gap: 0.4rem;
            min-height: var(--bingo-activity-item-height);
            box-sizing: border-box;
            padding: 0.7rem 0.9rem 0.7rem 0.85rem;
            border-radius: 0.65rem;
            border: 1px solid rgba(120, 190, 255, 0.14);
            border-left: 3px solid #6eb0ff;
          }}
          .bingo-activity-player {{
            align-self: center;
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
            align-self: center;
            min-width: 0;
            color: rgba(234, 234, 234, 0.88);
            font-size: 0.95rem;
            line-height: 1.3;
          }}
          .bingo-activity-impacts {{
            display: flex;
            flex-direction: column;
            min-height: 2.5rem;
            align-self: stretch;
            justify-content: stretch;
            border-radius: 0.35rem;
            overflow: hidden;
            box-sizing: border-box;
          }}
          .bingo-activity-impacts--single {{
            width: var(--bingo-activity-impacts-width-single);
            min-width: var(--bingo-activity-impacts-width-single);
            max-width: var(--bingo-activity-impacts-width-single);
          }}
          .bingo-activity-impacts--split {{
            width: var(--bingo-activity-impacts-width-split);
            min-width: var(--bingo-activity-impacts-width-split);
            max-width: var(--bingo-activity-impacts-width-split);
          }}
          .bingo-activity-impact-row {{
            flex: 1 1 0;
            display: flex;
            flex-direction: row;
            align-items: stretch;
            min-height: 1.35rem;
            min-width: 0;
          }}
          .bingo-activity-impact-row--gain {{
            background: rgba(94, 224, 154, 0.28);
          }}
          .bingo-activity-impact-row--loss {{
            background: rgba(255, 122, 132, 0.28);
          }}
          .bingo-activity-impact-row--loss .bingo-activity-impact + .bingo-activity-impact {{
            border-left: 1px solid rgba(255, 255, 255, 0.14);
          }}
          .bingo-activity-impact {{
            flex: 1 1 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-width: 0;
            min-height: 1.35rem;
            font-weight: 800;
            font-size: 0.8125rem;
            line-height: 1;
            letter-spacing: 0.01em;
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
            align-self: center;
            width: var(--bingo-activity-time-width);
            min-width: var(--bingo-activity-time-width);
            max-width: var(--bingo-activity-time-width);
            color: rgba(245, 245, 245, 0.45);
            font-size: 0.8125rem;
            white-space: nowrap;
            text-align: right;
            justify-self: end;
            overflow: hidden;
            text-overflow: ellipsis;
          }}
          .bingo-activity-empty {{
            color: rgba(245, 245, 245, 0.55);
            font-size: 0.925rem;
            margin: 0;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_shell,
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-shell {{
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
            width: 100% !important;
            max-width: 720px !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_shell [data-testid="stVerticalBlock"],
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-shell [data-testid="stVerticalBlock"] {{
            gap: 0 !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_shell [data-testid="stElementContainer"],
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-shell [data-testid="stElementContainer"] {{
            margin: 0 !important;
            padding: 0 !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_row > [data-testid="stElementContainer"]:last-child,
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-row > [data-testid="stElementContainer"]:last-child,
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_shell .st-key-bingo_activity_refresh,
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-shell .st-key-bingo-activity-refresh {{
            margin: 0 1.0rem 0 0 !important;
          }}
          .st-key-bingo_activity_feed [data-testid="stVerticalBlock"]:has(.st-key-bingo_activity_header_shell),
          .st-key-bingo-activity-feed [data-testid="stVerticalBlock"]:has(.st-key-bingo-activity-header-shell) {{
            gap: 0.25rem !important;
          }}
          .st-key-bingo_activity_feed [data-testid="stMarkdownContainer"]:has(.bingo-activity-viewport),
          .st-key-bingo-activity-feed [data-testid="stMarkdownContainer"]:has(.bingo-activity-viewport) {{
            margin-top: 0 !important;
            padding-top: 0 !important;
          }}
          .st-key-bingo_activity_feed [data-testid="stElementContainer"]:has(.bingo-activity-viewport),
          .st-key-bingo-activity-feed [data-testid="stElementContainer"]:has(.bingo-activity-viewport) {{
            margin-top: 0 !important;
            padding-top: 0 !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_row,
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-row {{
            width: 100% !important;
            max-width: 720px !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_row [data-testid="stHorizontalBlock"],
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-row [data-testid="stHorizontalBlock"] {{
            width: 100% !important;
            align-items: flex-end !important;
            justify-content: space-between !important;
            gap: 0.75rem !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_row [data-testid="stHorizontalBlock"] > div:first-child,
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-row [data-testid="stHorizontalBlock"] > div:first-child {{
            flex: 1 1 auto !important;
            min-width: 0 !important;
            width: auto !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_shell [data-testid="stCustomComponentV1"],
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-shell [data-testid="stCustomComponentV1"] {{
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
          }}
          .st-key-bingo_activity_feed .st-key-bingo_activity_header_shell [data-testid="stCustomComponentV1"] iframe,
          .st-key-bingo-activity-feed .st-key-bingo-activity-header-shell [data-testid="stCustomComponentV1"] iframe {{
            width: 100% !important;
            height: 2rem !important;
            min-height: 0 !important;
            display: block;
          }}
          .st-key-bingo_activity_refresh,
          .st-key-bingo-activity-refresh {{
            width: fit-content !important;
            min-width: 0 !important;
            flex: 0 0 auto !important;
            padding: 0 !important;
          }}
          .st-key-bingo_activity_refresh [data-testid="stButton"],
          .st-key-bingo-activity-refresh [data-testid="stButton"] {{
            width: auto !important;
            margin: 0 !important;
            padding: 0 !important;
          }}
          .st-key-bingo_activity_refresh button,
          .st-key-bingo-activity-refresh button {{
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
          }}
          .st-key-bingo_activity_refresh button:hover,
          .st-key-bingo-activity-refresh button:hover {{
            background-color: #007a58 !important;
            border-color: #007a58 !important;
          }}
          .st-key-bingo_activity_refresh button [data-testid="stIconMaterial"],
          .st-key-bingo-activity-refresh button [data-testid="stIconMaterial"],
          .st-key-bingo_activity_refresh button span,
          .st-key-bingo-activity-refresh button span {{
            font-size: 1.15rem !important;
            line-height: 1 !important;
            margin: 0 !important;
            padding: 0 !important;
          }}
          .st-key-bingo_activity_refresh button svg,
          .st-key-bingo-activity-refresh button svg {{
            width: 1.15rem !important;
            height: 1.15rem !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="bingo_activity_feed"):
        _render_bingo_activity_feed_header(settings=settings)
        with st.spinner("Loading activity feed…", width="stretch"):
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
            _mount_bingo_activity_time_ticker()


def _bingo_player_option_label(player: BingoTeamPlayer) -> str:
    return f"{player.display_name} ({player.team})"


def _bingo_chart_option_label(chart: BingoChart) -> str:
    return f"{chart.display_name} {_difficulty_label(chart.difficulty, chart.level)}"


def _auto_select_if_single_match(
    *,
    select_key: str,
    placeholder: str,
    matches: list[str],
    search_needle: str,
) -> None:
    """Auto-pick only when the search filter changes, not on every rerun."""
    cache_key = f"{select_key}_last_search_needle"
    normalized = search_needle.strip().casefold()
    if st.session_state.get(cache_key) == normalized:
        return
    st.session_state[cache_key] = normalized

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


def _ensure_view_player_in_select_matches(
    players: list[BingoTeamPlayer],
    player_matches: list[BingoTeamPlayer],
    *,
    search_needle: str = "",
) -> list[BingoTeamPlayer]:
    """Keep the active view player in options when not filtering (e.g. after refresh)."""
    if search_needle.strip():
        return player_matches
    player_id = st.session_state.get("bingo_view_player_id")
    if not player_id:
        return player_matches
    if any(player.player_id == player_id for player in player_matches):
        return player_matches
    for player in players:
        if player.player_id == player_id:
            merged = list(player_matches)
            merged.append(player)
            merged.sort(key=lambda entry: entry.display_name.casefold())
            return merged
    return player_matches


def _presync_player_select_from_view_id(
    teams: dict[str, list[BingoTeamPlayer]],
    *,
    player_options: list[str],
) -> None:
    """Restore selectbox only when widget state is missing or stale (not user changes)."""
    saved_player = _resolve_bingo_view_player(teams)
    if saved_player is None:
        return
    label = _bingo_player_option_label(saved_player)
    if label not in player_options:
        return
    select_key = "bingo-board-player-select"
    current = st.session_state.get(select_key)
    if current is None or current not in player_options:
        st.session_state[select_key] = label


def _resolve_bingo_view_player(
    teams: dict[str, list[BingoTeamPlayer]] | None = None,
) -> BingoTeamPlayer | None:
    player_id = st.session_state.get("bingo_view_player_id")
    if not player_id:
        return None
    roster = teams if teams is not None else _cached_bingo_teams()
    for player in _flatten_bingo_players(roster):
        if player.player_id == player_id:
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
        if "bingo_proof_upload_reset_id" not in st.session_state:
            st.session_state.bingo_proof_upload_reset_id = 0

        success_message = st.session_state.pop("bingo_submit_success", None)
        if success_message:
            st.success(success_message)
            st.session_state.bingo_proof_upload_reset_id += 1

        st.markdown(
            """
            <div class="bingo-submit-title">Submit a Score</div>
            <div class="bingo-submit-note">
              Upload a screenshot of the results screen as proof. PNG, JPEG, or WebP up to 50 MB.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not supabase_storage_configured():
            st.warning(
                "Proof uploads require `supabase.url` and `supabase.service_role_key` "
                "in secrets (or `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the environment)."
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

            _auto_select_if_single_match(
                select_key="bingo-submit-player-select",
                placeholder=BINGO_PLAYER_SELECT_PLACEHOLDER,
                matches=[
                    _bingo_player_option_label(player) for player in player_matches
                ],
                search_needle=player_search,
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

            _auto_select_if_single_match(
                select_key="bingo-submit-chart-select",
                placeholder=BINGO_CHART_SELECT_PLACEHOLDER,
                matches=[
                    _bingo_chart_option_label(chart) for chart in chart_matches
                ],
                search_needle=chart_search,
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

        proof_file = st.file_uploader(
            "Proof screenshot",
            type=["png", "jpg", "jpeg", "webp"],
            max_upload_size=50,
            key=f"bingo-submit-proof-{st.session_state.bingo_proof_upload_reset_id}",
            disabled=selected_player is None or selected_chart is None,
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
            and (proof_file is None or supabase_storage_configured())
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
            pending: dict[str, object] = {
                "player_id": selected_player.player_id,
                "song": selected_chart.song,
                "difficulty": selected_chart.difficulty,
                "score": score_value,
            }
            if proof_file is not None:
                pending["proof_bytes"] = proof_file.getvalue()
                pending["proof_filename"] = proof_file.name
            st.session_state.bingo_pending_submission = pending
            st.session_state.bingo_submission_in_progress = True
            # One app rerun: spinner covers save + board/scoreboard reload.
            st.rerun(scope="app")

        submit_error = st.session_state.pop("bingo_submit_error", None)
        if submit_error:
            st.error(submit_error)


def _bingo_player_chart_completion_counts(
    *,
    board_charts: list[BingoChart],
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    teams: dict[str, list[BingoTeamPlayer]],
) -> dict[str, int]:
    """Return {player_id: completed chart count} for roster players (score > 0)."""
    completed_by_player: dict[str, int] = {
        player.player_id: 0 for player in _flatten_bingo_players(teams)
    }
    for chart in board_charts:
        key = (chart.song, chart.difficulty)
        for entry in leaderboard_by_chart.get(key, []):
            if entry.score > 0:
                completed_by_player[entry.player_id] = (
                    completed_by_player.get(entry.player_id, 0) + 1
                )
    return completed_by_player


def _bingo_chart_completions_count_html(completed: int, *, total_charts: int) -> str:
    suffix = html.escape(f" / {total_charts}")
    if completed >= total_charts:
        return f"{html.escape(str(completed))}{suffix}"
    if completed == 0:
        return (
            '<span class="bingo-completions-count bingo-completions-count--zero">0</span>'
            f"{suffix}"
        )
    return (
        f'<span class="bingo-completions-count bingo-completions-count--incomplete">'
        f"{html.escape(str(completed))}</span>{suffix}"
    )


def _render_bingo_chart_completions_table_html(
    teams: dict[str, list[BingoTeamPlayer]],
    *,
    completed_by_player: dict[str, int],
    total_charts: int,
    highlight_player_id: str | None = None,
) -> str:
    if not any(teams.get(team) for team in TEAM_ORDER):
        return (
            '<div class="bingo-chart-modal-empty">'
            "No players are on the bingo roster yet."
            "</div>"
        )

    team_blocks: list[str] = []
    for team in TEAM_ORDER:
        players = list(teams.get(team, []))
        if not players:
            continue
        players.sort(
            key=lambda player: (
                -completed_by_player.get(player.player_id, 0),
                player.display_name.casefold(),
            )
        )
        team_color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
        rows: list[str] = []
        for player in players:
            completed = completed_by_player.get(player.player_id, 0)
            row_classes: list[str] = []
            if completed == 0:
                row_classes.append("bingo-completions-row--zero")
            if (
                highlight_player_id is not None
                and player.player_id == highlight_player_id
            ):
                row_classes.append("bingo-chart-modal-row--highlighted")
            row_class = " ".join(row_classes)
            row_attr = f' class="{html.escape(row_class)}"' if row_class else ""
            rows.append(
                f"<tr{row_attr}>"
                f'<td class="bingo-chart-modal-player" style="color:{team_color};">'
                f"{html.escape(player.display_name)}</td>"
                f'<td class="bingo-chart-modal-score">'
                f"{_bingo_chart_completions_count_html(completed, total_charts=total_charts)}"
                "</td>"
                "</tr>"
            )
        team_blocks.append(
            '<div class="bingo-completions-team-block">'
            f'<div class="bingo-completions-team-heading" style="color:{team_color};">'
            f"Team {html.escape(_team_label(team))}</div>"
            '<div class="bingo-chart-modal-table-wrap">'
            '<table class="bingo-chart-modal-table bingo-completions-team-table">'
            "<thead><tr>"
            '<th class="bingo-chart-modal-player">Player</th>'
            '<th class="bingo-chart-modal-score">Completed</th>'
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</div>"
            "</div>"
        )

    return (
        '<style>'
        ".bingo-completions-teams {"
        "display: grid;"
        "grid-template-columns: repeat(3, minmax(0, 1fr));"
        "gap: 1rem;"
        "align-items: start;"
        "}"
        ".bingo-completions-team-heading {"
        "font-size: 1.05rem;"
        "font-weight: 800;"
        "letter-spacing: 0.03em;"
        "text-decoration: underline;"
        "text-underline-offset: 0.14em;"
        "margin: 0.85rem 0 0.55rem 0;"
        "text-align: center;"
        "}"
        ".bingo-completions-team-table .bingo-chart-modal-player {"
        "width: auto;"
        "max-width: none;"
        "}"
        ".bingo-completions-count--incomplete {"
        "color: #ff7a84;"
        "font-weight: 800;"
        "}"
        ".bingo-completions-count--zero {"
        "color: #b83240;"
        "font-weight: 800;"
        "}"
        ".bingo-completions-row--zero td {"
        "background: rgba(184, 50, 64, 0.16);"
        "}"
        ".bingo-completions-row--zero.bingo-chart-modal-row--highlighted td {"
        "background: rgba(184, 50, 64, 0.24);"
        "}"
        "@media (max-width: 820px) {"
        ".bingo-completions-teams { grid-template-columns: 1fr; }"
        "}"
        "</style>"
        '<div class="bingo-completions-teams">'
        f"{''.join(team_blocks)}"
        "</div>"
    )


def _render_bingo_player_scores_table_html(
    *,
    player: BingoTeamPlayer,
    board_charts: list[BingoChart],
    teams: dict[str, list[BingoTeamPlayer]],
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    leaders_by_chart: dict[tuple[str, str], str | None],
) -> str:
    if not board_charts:
        return (
            '<div class="bingo-chart-modal-empty">'
            "No charts are on the board yet."
            "</div>"
        )

    sortable_rows: list[
        tuple[tuple[int, str], BingoChart, int, str, str, str, str | None]
    ] = []
    for chart in board_charts:
        chart_key = (chart.song, chart.difficulty)
        score = _player_chart_score(
            chart,
            player_id=player.player_id,
            leaderboard_by_chart=leaderboard_by_chart,
        )
        rank = _player_chart_placement_rank(
            chart,
            player_id=player.player_id,
            leaderboard_by_chart=leaderboard_by_chart,
            roster=teams,
        )
        owner_team = leaders_by_chart.get(chart_key)
        if score > 0:
            max_score = bingo_chart_max_score(chart.song, chart.difficulty)
            if max_score is not None and max_score > 0:
                score_pct = f"{ex_accuracy_percent(score, max_score):.2f}%"
            else:
                score_pct = "—"
            score_text = format_leader_score(score)
            placement_text = f"{_ordinal_rank(rank)} Place" if rank is not None else "—"
            sort_rank = rank if rank is not None else 9999
        else:
            score_pct = "—"
            score_text = "Not Played"
            placement_text = "Not Played"
            sort_rank = 9999
        sortable_rows.append(
            (
                (sort_rank, chart.display_name.casefold()),
                chart,
                score,
                score_text,
                score_pct,
                placement_text,
                owner_team,
            )
        )

    sortable_rows.sort(key=lambda item: item[0])
    rows: list[str] = []
    for _sort_key, chart, _score, score_text, score_pct, placement_text, owner_team in (
        sortable_rows
    ):
        row_bg = TEAM_PLAYER_SCORES_ROW_BG.get(owner_team or "", "")
        row_style = f' style="background:{html.escape(row_bg)};"' if row_bg else ""
        rows.append(
            f"<tr{row_style}>"
            f'<td class="bingo-player-scores-chart">'
            f'<div class="bingo-player-scores-chart-name">'
            f"{html.escape(chart.display_name)}</div>"
            f'<div class="bingo-player-scores-chart-diff">'
            f"{html.escape(_difficulty_label(chart.difficulty, chart.level))}"
            f"</div></td>"
            f'<td class="bingo-chart-modal-score">'
            f"{html.escape(score_text)}</td>"
            f'<td class="bingo-player-scores-pct">{html.escape(score_pct)}</td>'
            f'<td class="bingo-player-scores-placement">'
            f"{html.escape(placement_text)}</td>"
            "</tr>"
        )

    return (
        '<div class="bingo-chart-modal-table-wrap">'
        '<table class="bingo-chart-modal-table bingo-player-scores-table">'
        "<colgroup>"
        '<col class="bingo-player-scores-col-chart">'
        '<col class="bingo-player-scores-col-score">'
        '<col class="bingo-player-scores-col-pct">'
        '<col class="bingo-player-scores-col-placement">'
        "</colgroup>"
        "<thead><tr>"
        '<th class="bingo-player-scores-chart">Chart</th>'
        '<th class="bingo-chart-modal-score">Score</th>'
        '<th class="bingo-player-scores-pct">Score %</th>'
        '<th class="bingo-player-scores-placement">Placement</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def _build_bingo_player_scores_overlay_document(
    *,
    player: BingoTeamPlayer,
    table_html: str,
) -> str:
    player_name = html.escape(player.display_name)
    team_color = html.escape(TEAM_TEXT_COLORS.get(player.team, "#eaeaea"))
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
    margin: 0;
    padding: 0;
    height: 100%;
    background: transparent;
    font-family: "Source Sans Pro", "Segoe UI", sans-serif;
}}
{_BINGO_CHART_MODAL_ANIMATION_CSS}
{_BINGO_CHART_MODAL_SCROLLBAR_CSS}
{_BINGO_PLAYER_SCORES_TABLE_CSS}
.bingo-chart-modal-overlay {{
    position: fixed;
    inset: 0;
    z-index: 1;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    box-sizing: border-box;
}}
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
    width: min(100%, 960px);
    max-height: min(80vh, 760px);
    overflow: auto;
    background: #10162d;
    border: 1px solid rgba(234, 234, 234, 0.18);
    border-radius: 0.85rem;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
    padding: 1.25rem 1.25rem 1.1rem;
    box-sizing: border-box;
}}
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
}}
.bingo-chart-modal-subtitle {{
    font-size: 0.95rem;
    font-weight: 700;
    margin: 0 0 0.85rem;
}}
.bingo-chart-modal-table-wrap {{
    overflow-x: auto;
}}
.bingo-chart-modal-table {{
    width: 100%;
    border-collapse: collapse;
    color: #eaeaea;
}}
.bingo-chart-modal-table th,
.bingo-chart-modal-table td {{
    padding: 0.55rem 0.75rem;
    border-bottom: 1px solid rgba(234, 234, 234, 0.1);
    text-align: left;
    vertical-align: middle;
}}
.bingo-chart-modal-table th {{
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: rgba(234, 234, 234, 0.62);
}}
.bingo-chart-modal-score {{
    text-align: right;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}}
.bingo-chart-modal-empty {{
    color: rgba(234, 234, 234, 0.72);
    font-size: 0.95rem;
    padding: 0.5rem 0;
}}
</style>
</head>
<body>
<div id="bingo-player-scores-modal" class="bingo-chart-modal-overlay bingo-player-scores-modal is-open" aria-hidden="false">
  <button type="button" class="bingo-chart-modal-backdrop" aria-label="Close player scores"></button>
  <div class="bingo-chart-modal-panel" role="dialog" aria-modal="true" aria-labelledby="bingo-player-scores-title">
    <button type="button" class="bingo-chart-modal-close" aria-label="Close">&times;</button>
    <div id="bingo-player-scores-title" class="bingo-chart-modal-title">Player Scores</div>
    <div class="bingo-chart-modal-subtitle" style="color:{team_color};">{player_name}</div>
    <div class="bingo-chart-modal-body">{table_html}</div>
  </div>
</div>
<script>
(function () {{
  function requestClose() {{
    try {{
      const host = window.parent;
      if (host && typeof host.__bingoClosePlayerScoresOverlay === "function") {{
        host.__bingoClosePlayerScoresOverlay();
        return;
      }}
    }} catch (error) {{}}
    window.parent.postMessage("bingo-player-scores-close", "*");
  }}
  document.querySelector(".bingo-chart-modal-backdrop").addEventListener("click", requestClose);
  document.querySelector(".bingo-chart-modal-close").addEventListener("click", requestClose);
  document.addEventListener("keydown", function (event) {{
    if (event.key === "Escape") {{
      requestClose();
    }}
  }});
  document.querySelector(".bingo-chart-modal-close").focus();
}})();
</script>
</body>
</html>"""


def _render_bingo_player_scores_launch(
    *,
    player: BingoTeamPlayer,
    board_charts: list[BingoChart],
    teams: dict[str, list[BingoTeamPlayer]],
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    leaders_by_chart: dict[tuple[str, str], str | None],
) -> None:
    table_html = _render_bingo_player_scores_table_html(
        player=player,
        board_charts=board_charts,
        teams=teams,
        leaderboard_by_chart=leaderboard_by_chart,
        leaders_by_chart=leaders_by_chart,
    )
    overlay_doc = _build_bingo_player_scores_overlay_document(
        player=player,
        table_html=table_html,
    )
    overlay_doc_json = json.dumps(overlay_doc).replace("</", "<\\/")

    components.html(
        f"""
        <button type="button" class="bingo-player-scores-open-btn" id="bingo-player-scores-open">
          View Scores
        </button>
        <style>
          html, body {{
            margin: 0;
            padding: 0;
            background: transparent !important;
            overflow: hidden;
          }}
          .bingo-player-scores-open-btn {{
            display: block;
            margin: 0 auto;
            padding: 0.55rem 1.15rem;
            border-radius: 0.55rem;
            border: 1px solid rgba(234, 234, 234, 0.22);
            background: rgba(16, 22, 45, 0.92);
            color: rgba(245, 245, 245, 0.96);
            font-family: "Source Sans Pro", "Segoe UI", sans-serif;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            line-height: 1.2;
          }}
          .bingo-player-scores-open-btn:hover {{
            background: rgba(24, 32, 58, 0.98);
            border-color: rgba(234, 234, 234, 0.32);
          }}
        </style>
        <script>
        (function () {{
          const parentWin = window.parent;
          const parentDoc = parentWin.document;
          const overlayDoc = {overlay_doc_json};

          parentWin.__bingoClosePlayerScoresOverlay = function () {{
            const frame = parentDoc.getElementById("bingo-player-scores-overlay-frame");
            if (frame) {{
              frame.style.display = "none";
              frame.setAttribute("aria-hidden", "true");
            }}
            if (parentWin.__bingoPlayerScoresIframeObserver) {{
              parentWin.__bingoPlayerScoresIframeObserver.disconnect();
              parentWin.__bingoPlayerScoresIframeObserver = null;
            }}
            parentDoc.querySelectorAll("iframe").forEach(function (node) {{
              if (node.id === "bingo-player-scores-overlay-frame") {{
                return;
              }}
              if (node.dataset.bingoPlayerScoresPointerBlocked === "1") {{
                node.style.pointerEvents = node.dataset.bingoPlayerScoresPrevPointerEvents || "";
                delete node.dataset.bingoPlayerScoresPointerBlocked;
                delete node.dataset.bingoPlayerScoresPrevPointerEvents;
              }}
            }});
            if (parentWin.__bingoPlayerScoresEscapeListener) {{
              parentDoc.removeEventListener(
                "keydown",
                parentWin.__bingoPlayerScoresEscapeListener,
                true
              );
              parentWin.__bingoPlayerScoresEscapeListener = null;
            }}
          }};

          parentWin.__bingoBlockPlayerScoresOverlayInterference = function () {{
            if (parentWin.__bingoPlayerScoresOverlayBusy) {{
              return;
            }}
            parentWin.__bingoPlayerScoresOverlayBusy = true;
            try {{
              parentDoc.querySelectorAll("iframe").forEach(function (node) {{
                if (node.id === "bingo-player-scores-overlay-frame") {{
                  return;
                }}
                if (node.dataset.bingoPlayerScoresPointerBlocked === "1") {{
                  return;
                }}
                node.dataset.bingoPlayerScoresPointerBlocked = "1";
                node.dataset.bingoPlayerScoresPrevPointerEvents = node.style.pointerEvents || "";
                node.style.pointerEvents = "none";
              }});
              const frame = parentDoc.getElementById("bingo-player-scores-overlay-frame");
              if (frame && parentDoc.body.lastElementChild !== frame) {{
                parentDoc.body.appendChild(frame);
              }}
              if (frame) {{
                frame.style.display = "block";
                frame.style.pointerEvents = "auto";
                frame.style.zIndex = "2147483647";
              }}
            }} finally {{
              parentWin.__bingoPlayerScoresOverlayBusy = false;
            }}
          }};

          parentWin.__bingoOpenPlayerScoresOverlay = function (nextOverlayDoc) {{
            const staleModal = parentDoc.getElementById("bingo-player-scores-modal");
            if (staleModal) {{
              staleModal.remove();
            }}
            let frame = parentDoc.getElementById("bingo-player-scores-overlay-frame");
            if (!frame) {{
              frame = parentDoc.createElement("iframe");
              frame.id = "bingo-player-scores-overlay-frame";
              frame.setAttribute("title", "Player Scores");
              frame.setAttribute("aria-hidden", "true");
              frame.style.cssText =
                "position:fixed;inset:0;width:100%;height:100%;border:none;z-index:2147483647;background:transparent;display:none;pointer-events:auto;";
            }}
            parentDoc.body.appendChild(frame);
            frame.srcdoc = nextOverlayDoc;
            frame.style.display = "block";
            frame.style.pointerEvents = "auto";
            frame.setAttribute("aria-hidden", "false");
            parentWin.__bingoBlockPlayerScoresOverlayInterference();
            if (parentWin.__bingoPlayerScoresIframeObserver) {{
              parentWin.__bingoPlayerScoresIframeObserver.disconnect();
            }}
            parentWin.__bingoPlayerScoresIframeObserver = new MutationObserver(function () {{
              parentWin.__bingoBlockPlayerScoresOverlayInterference();
            }});
            parentWin.__bingoPlayerScoresIframeObserver.observe(parentDoc.body, {{
              childList: true,
              subtree: true,
            }});
            if (parentWin.__bingoPlayerScoresEscapeListener) {{
              parentDoc.removeEventListener(
                "keydown",
                parentWin.__bingoPlayerScoresEscapeListener,
                true
              );
            }}
            parentWin.__bingoPlayerScoresEscapeListener = function (event) {{
              if (event.key !== "Escape") {{
                return;
              }}
              const activeFrame = parentDoc.getElementById("bingo-player-scores-overlay-frame");
              if (!activeFrame || activeFrame.style.display === "none") {{
                return;
              }}
              parentWin.__bingoClosePlayerScoresOverlay();
            }};
            parentDoc.addEventListener(
              "keydown",
              parentWin.__bingoPlayerScoresEscapeListener,
              true
            );
          }};

          if (parentWin.__bingoPlayerScoresMessageListener) {{
            parentWin.removeEventListener("message", parentWin.__bingoPlayerScoresMessageListener);
          }}
          parentWin.__bingoPlayerScoresMessageListener = function (event) {{
            if (event.data !== "bingo-player-scores-close") {{
              return;
            }}
            const frame = parentDoc.getElementById("bingo-player-scores-overlay-frame");
            if (!frame || frame.style.display === "none") {{
              return;
            }}
            if (event.source && frame.contentWindow && event.source !== frame.contentWindow) {{
              return;
            }}
            parentWin.__bingoClosePlayerScoresOverlay();
          }};
          parentWin.addEventListener("message", parentWin.__bingoPlayerScoresMessageListener);

          const openBtn = document.getElementById("bingo-player-scores-open");
          if (openBtn) {{
            openBtn.onclick = function () {{
              parentWin.__bingoOpenPlayerScoresOverlay(overlayDoc);
            }};
          }}
        }})();
        </script>
        """,
        height=52,
        scrolling=False,
    )


def _build_bingo_completions_overlay_document(*, table_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
    margin: 0;
    padding: 0;
    height: 100%;
    background: transparent;
    font-family: "Source Sans Pro", "Segoe UI", sans-serif;
}}
{_BINGO_CHART_MODAL_ANIMATION_CSS}
{_BINGO_CHART_MODAL_SCROLLBAR_CSS}
.bingo-chart-modal-overlay {{
    position: fixed;
    inset: 0;
    z-index: 1;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    box-sizing: border-box;
}}
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
    width: min(100%, 960px);
    max-height: min(80vh, 760px);
    overflow: auto;
    background: #10162d;
    border: 1px solid rgba(234, 234, 234, 0.18);
    border-radius: 0.85rem;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
    padding: 1.25rem 1.25rem 1.1rem;
    box-sizing: border-box;
}}
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
}}
.bingo-chart-modal-table-wrap {{
    overflow-x: auto;
}}
.bingo-chart-modal-table {{
    width: 100%;
    border-collapse: collapse;
    color: #eaeaea;
}}
.bingo-chart-modal-table th,
.bingo-chart-modal-table td {{
    padding: 0.55rem 0.75rem;
    border-bottom: 1px solid rgba(234, 234, 234, 0.1);
    text-align: left;
    vertical-align: middle;
}}
.bingo-chart-modal-table th {{
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: rgba(234, 234, 234, 0.62);
}}
.bingo-chart-modal-player {{
    font-weight: 700;
}}
.bingo-chart-modal-score {{
    text-align: right;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}}
.bingo-chart-modal-table tbody tr.bingo-chart-modal-row--highlighted td {{
    background: rgba(110, 176, 255, 0.12);
}}
.bingo-chart-modal-empty {{
    color: rgba(234, 234, 234, 0.72);
    font-size: 0.95rem;
    padding: 0.5rem 0;
}}
</style>
</head>
<body>
<div id="bingo-chart-completions-modal" class="bingo-chart-modal-overlay bingo-chart-completions-modal is-open" aria-hidden="false">
  <button type="button" class="bingo-chart-modal-backdrop" aria-label="Close chart completions"></button>
  <div class="bingo-chart-modal-panel" role="dialog" aria-modal="true" aria-labelledby="bingo-chart-completions-title">
    <button type="button" class="bingo-chart-modal-close" aria-label="Close">&times;</button>
    <div id="bingo-chart-completions-title" class="bingo-chart-modal-title">Chart Completions</div>
    <div class="bingo-chart-modal-body">{table_html}</div>
  </div>
</div>
<script>
(function () {{
  function requestClose() {{
    try {{
      const host = window.parent;
      if (host && typeof host.__bingoCloseCompletionsOverlay === "function") {{
        host.__bingoCloseCompletionsOverlay();
        return;
      }}
    }} catch (error) {{}}
    window.parent.postMessage("bingo-completions-close", "*");
  }}
  document.querySelector(".bingo-chart-modal-backdrop").addEventListener("click", requestClose);
  document.querySelector(".bingo-chart-modal-close").addEventListener("click", requestClose);
  document.addEventListener("keydown", function (event) {{
    if (event.key === "Escape") {{
      requestClose();
    }}
  }});
  document.querySelector(".bingo-chart-modal-close").focus();
}})();
</script>
</body>
</html>"""


def _render_bingo_chart_completions(
    *,
    charts: list[BingoChart],
    teams: dict[str, list[BingoTeamPlayer]],
    settings: BingoSettings,
    highlight_player_id: str | None = None,
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]]
    | None = None,
) -> None:
    if settings.start_time is None:
        return

    board_charts = bingo_charts_on_board(charts, int(settings.board_width or 5))
    total_charts = len(board_charts)
    if total_charts <= 0:
        return

    try:
        if leaderboard_by_chart is None:
            leaderboard_by_chart = load_all_bingo_chart_player_leaderboards(
                start_time=settings.start_time,
            )
    except Exception as exc:
        st.error(f"Failed to load chart completions: {exc}")
        return

    completed_by_player = _bingo_player_chart_completion_counts(
        board_charts=board_charts,
        leaderboard_by_chart=leaderboard_by_chart,
        teams=teams,
    )
    table_html = _render_bingo_chart_completions_table_html(
        teams,
        completed_by_player=completed_by_player,
        total_charts=total_charts,
        highlight_player_id=highlight_player_id,
    )
    overlay_doc = _build_bingo_completions_overlay_document(table_html=table_html)
    overlay_doc_json = json.dumps(overlay_doc).replace("</", "<\\/")

    st.markdown(
        """
        <style>
        .st-key-bingo_chart_completions_launch {
            width: 100%;
            max-width: 100%;
            margin: 0;
        }
        .st-key-bingo_chart_completions_launch [data-testid="stElementContainer"] {
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_chart_completions_launch [data-testid="stCustomComponentV1"] {
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_chart_completions_launch iframe {
            width: 100% !important;
            max-width: 100% !important;
            border: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="bingo_chart_completions_launch"):
        components.html(
            f"""
            <button type="button" class="bingo-completions-open-btn" id="bingo-completions-open">
              Chart Completions
            </button>
            <style>
              html, body {{
                margin: 0;
                padding: 0;
                background: transparent !important;
                overflow: hidden;
              }}
              .bingo-completions-open-btn {{
                display: block;
                margin: 0 auto;
                padding: 0.55rem 1.15rem;
                border-radius: 0.55rem;
                border: 1px solid rgba(234, 234, 234, 0.22);
                background: rgba(16, 22, 45, 0.92);
                color: rgba(245, 245, 245, 0.96);
                font-family: "Source Sans Pro", "Segoe UI", sans-serif;
                font-size: 1rem;
                font-weight: 700;
                cursor: pointer;
                line-height: 1.2;
              }}
              .bingo-completions-open-btn:hover {{
                background: rgba(24, 32, 58, 0.98);
                border-color: rgba(234, 234, 234, 0.32);
              }}
            </style>
            <script>
            (function () {{
              const parentWin = window.parent;
              const parentDoc = parentWin.document;
              const overlayDoc = {overlay_doc_json};

              parentWin.__bingoCloseCompletionsOverlay = function () {{
                const frame = parentDoc.getElementById("bingo-completions-overlay-frame");
                if (frame) {{
                  frame.style.display = "none";
                  frame.setAttribute("aria-hidden", "true");
                }}
                if (parentWin.__bingoCompletionsIframeObserver) {{
                  parentWin.__bingoCompletionsIframeObserver.disconnect();
                  parentWin.__bingoCompletionsIframeObserver = null;
                }}
                parentDoc.querySelectorAll("iframe").forEach(function (node) {{
                  if (node.id === "bingo-completions-overlay-frame") {{
                    return;
                  }}
                  if (node.dataset.bingoCompletionsPointerBlocked === "1") {{
                    node.style.pointerEvents = node.dataset.bingoCompletionsPrevPointerEvents || "";
                    delete node.dataset.bingoCompletionsPointerBlocked;
                    delete node.dataset.bingoCompletionsPrevPointerEvents;
                  }}
                }});
                if (parentWin.__bingoCompletionsEscapeListener) {{
                  parentDoc.removeEventListener(
                    "keydown",
                    parentWin.__bingoCompletionsEscapeListener,
                    true
                  );
                  parentWin.__bingoCompletionsEscapeListener = null;
                }}
              }};

              parentWin.__bingoBlockCompletionsOverlayInterference = function () {{
                if (parentWin.__bingoCompletionsOverlayBusy) {{
                  return;
                }}
                parentWin.__bingoCompletionsOverlayBusy = true;
                try {{
                  parentDoc.querySelectorAll("iframe").forEach(function (node) {{
                    if (node.id === "bingo-completions-overlay-frame") {{
                      return;
                    }}
                    if (node.dataset.bingoCompletionsPointerBlocked === "1") {{
                      return;
                    }}
                    node.dataset.bingoCompletionsPointerBlocked = "1";
                    node.dataset.bingoCompletionsPrevPointerEvents = node.style.pointerEvents || "";
                    node.style.pointerEvents = "none";
                  }});
                  const frame = parentDoc.getElementById("bingo-completions-overlay-frame");
                  if (frame && parentDoc.body.lastElementChild !== frame) {{
                    parentDoc.body.appendChild(frame);
                  }}
                  if (frame) {{
                    frame.style.display = "block";
                    frame.style.pointerEvents = "auto";
                    frame.style.zIndex = "2147483647";
                  }}
                }} finally {{
                  parentWin.__bingoCompletionsOverlayBusy = false;
                }}
              }};

              parentWin.__bingoOpenCompletionsOverlay = function (nextOverlayDoc) {{
                const staleModal = parentDoc.getElementById("bingo-chart-completions-modal");
                if (staleModal) {{
                  staleModal.remove();
                }}
                let frame = parentDoc.getElementById("bingo-completions-overlay-frame");
                if (!frame) {{
                  frame = parentDoc.createElement("iframe");
                  frame.id = "bingo-completions-overlay-frame";
                  frame.setAttribute("title", "Chart Completions");
                  frame.setAttribute("aria-hidden", "true");
                  frame.style.cssText =
                    "position:fixed;inset:0;width:100%;height:100%;border:none;z-index:2147483647;background:transparent;display:none;pointer-events:auto;";
                }}
                parentDoc.body.appendChild(frame);
                frame.srcdoc = nextOverlayDoc;
                frame.style.display = "block";
                frame.style.pointerEvents = "auto";
                frame.setAttribute("aria-hidden", "false");
                parentWin.__bingoBlockCompletionsOverlayInterference();
                if (parentWin.__bingoCompletionsIframeObserver) {{
                  parentWin.__bingoCompletionsIframeObserver.disconnect();
                }}
                parentWin.__bingoCompletionsIframeObserver = new MutationObserver(function () {{
                  parentWin.__bingoBlockCompletionsOverlayInterference();
                }});
                parentWin.__bingoCompletionsIframeObserver.observe(parentDoc.body, {{
                  childList: true,
                  subtree: true,
                }});
                if (parentWin.__bingoCompletionsEscapeListener) {{
                  parentDoc.removeEventListener(
                    "keydown",
                    parentWin.__bingoCompletionsEscapeListener,
                    true
                  );
                }}
                parentWin.__bingoCompletionsEscapeListener = function (event) {{
                  if (event.key !== "Escape") {{
                    return;
                  }}
                  const activeFrame = parentDoc.getElementById("bingo-completions-overlay-frame");
                  if (!activeFrame || activeFrame.style.display === "none") {{
                    return;
                  }}
                  parentWin.__bingoCloseCompletionsOverlay();
                }};
                parentDoc.addEventListener(
                  "keydown",
                  parentWin.__bingoCompletionsEscapeListener,
                  true
                );
              }};

              if (parentWin.__bingoCompletionsMessageListener) {{
                parentWin.removeEventListener("message", parentWin.__bingoCompletionsMessageListener);
              }}
              parentWin.__bingoCompletionsMessageListener = function (event) {{
                if (event.data !== "bingo-completions-close") {{
                  return;
                }}
                const frame = parentDoc.getElementById("bingo-completions-overlay-frame");
                if (!frame || frame.style.display === "none") {{
                  return;
                }}
                if (event.source && frame.contentWindow && event.source !== frame.contentWindow) {{
                  return;
                }}
                parentWin.__bingoCloseCompletionsOverlay();
              }};
              parentWin.addEventListener("message", parentWin.__bingoCompletionsMessageListener);

              const openBtn = document.getElementById("bingo-completions-open");
              if (openBtn) {{
                openBtn.onclick = function () {{
                  parentWin.__bingoOpenCompletionsOverlay(overlayDoc);
                }};
              }}
            }})();
            </script>
            """,
            height=52,
            scrolling=False,
        )


def _bingo_player_point_totals(
    *,
    board_charts: list[BingoChart],
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    teams: dict[str, list[BingoTeamPlayer]],
) -> dict[str, float]:
    """Return {player_id: total claim points} summed across all board squares."""
    totals: dict[str, float] = {
        player.player_id: 0.0 for player in _flatten_bingo_players(teams)
    }
    use_v2 = bingo_scoring_version() == "v2"
    for chart in board_charts:
        entries = merge_chart_leaderboard_with_roster(
            teams,
            leaderboard_by_chart.get((chart.song, chart.difficulty), []),
        )
        players = {
            entry.player_id: (entry.team, int(entry.score)) for entry in entries
        }
        if not players:
            continue
        if use_v2:
            breakdowns = compute_chart_player_point_breakdowns(
                song=chart.song,
                difficulty=chart.difficulty,
                players=players,
            )
            for player_id, breakdown in breakdowns.items():
                if player_id not in totals:
                    continue
                totals[player_id] += float(breakdown.accuracy_points) + float(
                    breakdown.placement_bonus
                )
        else:
            for player_id, (_team, score) in players.items():
                if player_id not in totals:
                    continue
                totals[player_id] += float(int(score))
    return totals


def _bingo_competition_ranks_by_points(
    players: list[BingoTeamPlayer],
    *,
    points_by_player: dict[str, float],
) -> dict[str, int]:
    ordered = sorted(
        players,
        key=lambda player: (
            -points_by_player.get(player.player_id, 0.0),
            player.display_name.casefold(),
        ),
    )
    ranks: dict[str, int] = {}
    index = 0
    while index < len(ordered):
        points = points_by_player.get(ordered[index].player_id, 0.0)
        next_index = index + 1
        while (
            next_index < len(ordered)
            and points_by_player.get(ordered[next_index].player_id, 0.0) == points
        ):
            next_index += 1
        rank = index + 1
        for player in ordered[index:next_index]:
            ranks[player.player_id] = rank
        index = next_index
    return ranks


def _bingo_point_counts_shared_table_css() -> str:
    return (
        ".bingo-point-counts-teams {"
        "display: grid;"
        "grid-template-columns: repeat(3, minmax(0, 1fr));"
        "gap: 1rem;"
        "align-items: start;"
        "}"
        ".bingo-point-counts-team-heading {"
        "font-size: 1.05rem;"
        "font-weight: 800;"
        "letter-spacing: 0.03em;"
        "text-decoration: underline;"
        "text-underline-offset: 0.14em;"
        "margin: 0.85rem 0 0.55rem 0;"
        "text-align: center;"
        "}"
        ".bingo-point-counts-overall-table,"
        ".bingo-point-counts-team-table {"
        "table-layout: fixed;"
        "width: 100%;"
        "}"
        ".bingo-point-counts-overall-table .bingo-chart-modal-rank,"
        ".bingo-point-counts-team-table .bingo-chart-modal-rank {"
        "width: 2.5rem;"
        "}"
        ".bingo-point-counts-overall-table .bingo-chart-modal-score,"
        ".bingo-point-counts-team-table .bingo-chart-modal-score {"
        "width: 4.5rem;"
        "}"
        ".bingo-point-counts-overall-table .bingo-chart-modal-player,"
        ".bingo-point-counts-team-table .bingo-chart-modal-player {"
        "overflow: hidden;"
        "text-overflow: ellipsis;"
        "white-space: nowrap;"
        "}"
        ".bingo-point-counts-overall-table td,"
        ".bingo-point-counts-team-table td {"
        "white-space: nowrap;"
        "}"
        ".bingo-point-counts-team-table tfoot td {"
        "border-bottom: none;"
        "border-top: 1px solid rgba(234, 234, 234, 0.22);"
        "font-weight: 800;"
        "padding-top: 0.7rem;"
        "}"
        ".bingo-point-counts-toggle {"
        "display: flex;"
        "justify-content: center;"
        "gap: 0.45rem;"
        "margin: 0.15rem 0 0.85rem;"
        "}"
        ".bingo-point-counts-toggle-btn {"
        "border: 1px solid rgba(234, 234, 234, 0.22);"
        "background: rgba(8, 12, 28, 0.72);"
        "color: rgba(234, 234, 234, 0.78);"
        "border-radius: 999px;"
        "padding: 0.28rem 0.85rem;"
        "font-size: 0.86rem;"
        "font-weight: 700;"
        "cursor: pointer;"
        "font-family: inherit;"
        "}"
        ".bingo-point-counts-toggle-btn.is-active {"
        "background: rgba(110, 176, 255, 0.18);"
        "border-color: rgba(110, 176, 255, 0.46);"
        "color: #f5f5f5;"
        "}"
        ".bingo-point-counts-view[hidden] { display: none !important; }"
        "@media (max-width: 820px) {"
        ".bingo-point-counts-teams { grid-template-columns: 1fr; }"
        "}"
    )


def _render_bingo_point_counts_overall_table_html(
    teams: dict[str, list[BingoTeamPlayer]],
    *,
    points_by_player: dict[str, float],
    highlight_player_id: str | None = None,
) -> str:
    players = _flatten_bingo_players(teams)
    if not players:
        return (
            '<div class="bingo-chart-modal-empty">'
            "No players are on the bingo roster yet."
            "</div>"
        )
    ranks = _bingo_competition_ranks_by_points(
        players, points_by_player=points_by_player
    )
    ordered = sorted(
        players,
        key=lambda player: (
            ranks.get(player.player_id, 9999),
            player.display_name.casefold(),
        ),
    )
    rows: list[str] = []
    for player in ordered:
        points = points_by_player.get(player.player_id, 0.0)
        team_color = TEAM_TEXT_COLORS.get(player.team, "#eaeaea")
        row_attr = ""
        if (
            highlight_player_id is not None
            and player.player_id == highlight_player_id
        ):
            row_attr = ' class="bingo-chart-modal-row--highlighted"'
        rows.append(
            f"<tr{row_attr}>"
            f'<td class="bingo-chart-modal-rank">{ranks.get(player.player_id, "—")}</td>'
            f'<td class="bingo-chart-modal-player" style="color:{team_color};" '
            f'title="{html.escape(player.display_name, quote=True)}">'
            f"{html.escape(player.display_name)}</td>"
            f'<td class="bingo-chart-modal-score">'
            f"{html.escape(format_bingo_points(points))}</td>"
            "</tr>"
        )
    return (
        '<div class="bingo-chart-modal-table-wrap">'
        '<table class="bingo-chart-modal-table bingo-point-counts-overall-table">'
        "<thead><tr>"
        '<th class="bingo-chart-modal-rank">#</th>'
        '<th class="bingo-chart-modal-player">Player</th>'
        '<th class="bingo-chart-modal-score">Points</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def _render_bingo_point_counts_teams_table_html(
    teams: dict[str, list[BingoTeamPlayer]],
    *,
    points_by_player: dict[str, float],
    highlight_player_id: str | None = None,
) -> str:
    if not any(teams.get(team) for team in TEAM_ORDER):
        return (
            '<div class="bingo-chart-modal-empty">'
            "No players are on the bingo roster yet."
            "</div>"
        )

    team_blocks: list[str] = []
    for team in TEAM_ORDER:
        players = list(teams.get(team, []))
        if not players:
            continue
        ranks = _bingo_competition_ranks_by_points(
            players, points_by_player=points_by_player
        )
        players.sort(
            key=lambda player: (
                ranks.get(player.player_id, 9999),
                player.display_name.casefold(),
            )
        )
        team_color = TEAM_TEXT_COLORS.get(team, "#eaeaea")
        team_total = sum(
            points_by_player.get(player.player_id, 0.0) for player in players
        )
        total_text = html.escape(format_bingo_points(team_total))
        rows: list[str] = []
        for player in players:
            points = points_by_player.get(player.player_id, 0.0)
            row_attr = ""
            if (
                highlight_player_id is not None
                and player.player_id == highlight_player_id
            ):
                row_attr = ' class="bingo-chart-modal-row--highlighted"'
            rows.append(
                f"<tr{row_attr}>"
                f'<td class="bingo-chart-modal-rank">{ranks.get(player.player_id, "—")}</td>'
                f'<td class="bingo-chart-modal-player" style="color:{team_color};" '
                f'title="{html.escape(player.display_name, quote=True)}">'
                f"{html.escape(player.display_name)}</td>"
                f'<td class="bingo-chart-modal-score">'
                f"{html.escape(format_bingo_points(points))}</td>"
                "</tr>"
            )
        team_blocks.append(
            '<div class="bingo-point-counts-team-block">'
            f'<div class="bingo-point-counts-team-heading" style="color:{team_color};">'
            f"Team {html.escape(_team_label(team))}</div>"
            '<div class="bingo-chart-modal-table-wrap">'
            '<table class="bingo-chart-modal-table bingo-point-counts-team-table">'
            "<thead><tr>"
            '<th class="bingo-chart-modal-rank">#</th>'
            '<th class="bingo-chart-modal-player">Player</th>'
            '<th class="bingo-chart-modal-score">Points</th>'
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "<tfoot><tr>"
            '<td class="bingo-chart-modal-rank"></td>'
            '<td class="bingo-chart-modal-player">Total</td>'
            f'<td class="bingo-chart-modal-score" style="color:{team_color};">'
            f"{total_text}</td>"
            "</tr></tfoot>"
            "</table>"
            "</div>"
            "</div>"
        )

    return (
        '<div class="bingo-point-counts-teams">'
        f"{''.join(team_blocks)}"
        "</div>"
    )


def _render_bingo_point_counts_panel_html(
    teams: dict[str, list[BingoTeamPlayer]],
    *,
    points_by_player: dict[str, float],
    highlight_player_id: str | None = None,
) -> str:
    overall_html = _render_bingo_point_counts_overall_table_html(
        teams,
        points_by_player=points_by_player,
        highlight_player_id=highlight_player_id,
    )
    teams_html = _render_bingo_point_counts_teams_table_html(
        teams,
        points_by_player=points_by_player,
        highlight_player_id=highlight_player_id,
    )
    return (
        f"<style>{_bingo_point_counts_shared_table_css()}</style>"
        '<div class="bingo-point-counts-toggle" role="tablist" aria-label="Point counts view">'
        '<button type="button" class="bingo-point-counts-toggle-btn is-active" '
        'data-point-counts-view="overall" role="tab" aria-selected="true">Overall</button>'
        '<button type="button" class="bingo-point-counts-toggle-btn" '
        'data-point-counts-view="teams" role="tab" aria-selected="false">By Team</button>'
        "</div>"
        '<div class="bingo-point-counts-view" data-point-counts-panel="overall">'
        f"{overall_html}"
        "</div>"
        '<div class="bingo-point-counts-view" data-point-counts-panel="teams" hidden>'
        f"{teams_html}"
        "</div>"
    )


def _build_bingo_point_counts_overlay_document(*, table_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
    margin: 0;
    padding: 0;
    height: 100%;
    background: transparent;
    font-family: "Source Sans Pro", "Segoe UI", sans-serif;
}}
{_BINGO_CHART_MODAL_ANIMATION_CSS}
{_BINGO_CHART_MODAL_SCROLLBAR_CSS}
.bingo-chart-modal-overlay {{
    position: fixed;
    inset: 0;
    z-index: 1;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    box-sizing: border-box;
}}
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
    width: min(100%, 960px);
    max-height: min(80vh, 760px);
    overflow: auto;
    background: #10162d;
    border: 1px solid rgba(234, 234, 234, 0.18);
    border-radius: 0.85rem;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
    padding: 1.25rem 1.25rem 1.1rem;
    box-sizing: border-box;
}}
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
}}
.bingo-chart-modal-table-wrap {{
    overflow-x: auto;
}}
.bingo-chart-modal-table {{
    width: 100%;
    border-collapse: collapse;
    color: #eaeaea;
}}
.bingo-chart-modal-table th,
.bingo-chart-modal-table td {{
    padding: 0.55rem 0.75rem;
    border-bottom: 1px solid rgba(234, 234, 234, 0.1);
    text-align: left;
    vertical-align: middle;
}}
.bingo-chart-modal-table th {{
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: rgba(234, 234, 234, 0.62);
}}
.bingo-chart-modal-rank {{
    width: 3rem;
    color: rgba(234, 234, 234, 0.72);
    font-variant-numeric: tabular-nums;
}}
.bingo-chart-modal-player {{
    font-weight: 700;
}}
.bingo-chart-modal-score {{
    text-align: right;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}}
.bingo-chart-modal-table tbody tr.bingo-chart-modal-row--highlighted td {{
    background: rgba(110, 176, 255, 0.12);
}}
.bingo-chart-modal-empty {{
    color: rgba(234, 234, 234, 0.72);
    font-size: 0.95rem;
    padding: 0.5rem 0;
}}
</style>
</head>
<body>
<div id="bingo-point-counts-modal" class="bingo-chart-modal-overlay bingo-point-counts-modal is-open" aria-hidden="false">
  <button type="button" class="bingo-chart-modal-backdrop" aria-label="Close point counts"></button>
  <div class="bingo-chart-modal-panel" role="dialog" aria-modal="true" aria-labelledby="bingo-point-counts-title">
    <button type="button" class="bingo-chart-modal-close" aria-label="Close">&times;</button>
    <div id="bingo-point-counts-title" class="bingo-chart-modal-title">Point Counts</div>
    <div class="bingo-chart-modal-body">{table_html}</div>
  </div>
</div>
<script>
(function () {{
  function requestClose() {{
    try {{
      const host = window.parent;
      if (host && typeof host.__bingoClosePointCountsOverlay === "function") {{
        host.__bingoClosePointCountsOverlay();
        return;
      }}
    }} catch (error) {{}}
    window.parent.postMessage("bingo-point-counts-close", "*");
  }}
  document.querySelector(".bingo-chart-modal-backdrop").addEventListener("click", requestClose);
  document.querySelector(".bingo-chart-modal-close").addEventListener("click", requestClose);
  document.addEventListener("keydown", function (event) {{
    if (event.key === "Escape") {{
      requestClose();
    }}
  }});
  const toggleRoot = document.querySelector(".bingo-point-counts-toggle");
  if (toggleRoot) {{
    const buttons = Array.from(
      toggleRoot.querySelectorAll("[data-point-counts-view]")
    );
    const panels = Array.from(
      document.querySelectorAll("[data-point-counts-panel]")
    );
    buttons.forEach(function (button) {{
      button.addEventListener("click", function () {{
        const view = button.getAttribute("data-point-counts-view");
        buttons.forEach(function (other) {{
          const active = other === button;
          other.classList.toggle("is-active", active);
          other.setAttribute("aria-selected", active ? "true" : "false");
        }});
        panels.forEach(function (panel) {{
          panel.hidden = panel.getAttribute("data-point-counts-panel") !== view;
        }});
      }});
    }});
  }}
  document.querySelector(".bingo-chart-modal-close").focus();
}})();
</script>
</body>
</html>"""


def _render_bingo_point_counts(
    *,
    charts: list[BingoChart],
    teams: dict[str, list[BingoTeamPlayer]],
    settings: BingoSettings,
    highlight_player_id: str | None = None,
    leaderboard_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]]
    | None = None,
) -> None:
    if settings.start_time is None:
        return

    board_charts = bingo_charts_on_board(charts, int(settings.board_width or 5))
    if not board_charts:
        return

    try:
        if leaderboard_by_chart is None:
            leaderboard_by_chart = load_all_bingo_chart_player_leaderboards(
                start_time=settings.start_time,
            )
    except Exception as exc:
        st.error(f"Failed to load point counts: {exc}")
        return

    points_by_player = _bingo_player_point_totals(
        board_charts=board_charts,
        leaderboard_by_chart=leaderboard_by_chart,
        teams=teams,
    )
    table_html = _render_bingo_point_counts_panel_html(
        teams,
        points_by_player=points_by_player,
        highlight_player_id=highlight_player_id,
    )
    overlay_doc = _build_bingo_point_counts_overlay_document(table_html=table_html)
    overlay_doc_json = json.dumps(overlay_doc).replace("</", "<\\/")

    st.markdown(
        """
        <style>
        .st-key-bingo_point_counts_launch {
            width: 100%;
            max-width: 100%;
            margin: 0;
        }
        .st-key-bingo_point_counts_launch [data-testid="stElementContainer"] {
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_point_counts_launch [data-testid="stCustomComponentV1"] {
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .st-key-bingo_point_counts_launch iframe {
            width: 100% !important;
            max-width: 100% !important;
            border: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="bingo_point_counts_launch"):
        components.html(
            f"""
            <button type="button" class="bingo-point-counts-open-btn" id="bingo-point-counts-open">
              Point Counts
            </button>
            <style>
              html, body {{
                margin: 0;
                padding: 0;
                background: transparent !important;
                overflow: hidden;
              }}
              .bingo-point-counts-open-btn {{
                display: block;
                margin: 0 auto;
                padding: 0.55rem 1.15rem;
                border-radius: 0.55rem;
                border: 1px solid rgba(234, 234, 234, 0.22);
                background: rgba(16, 22, 45, 0.92);
                color: rgba(245, 245, 245, 0.96);
                font-family: "Source Sans Pro", "Segoe UI", sans-serif;
                font-size: 1rem;
                font-weight: 700;
                cursor: pointer;
                line-height: 1.2;
                white-space: nowrap;
              }}
              .bingo-point-counts-open-btn:hover {{
                background: rgba(24, 32, 58, 0.98);
                border-color: rgba(234, 234, 234, 0.32);
              }}
            </style>
            <script>
            (function () {{
              const parentWin = window.parent;
              const parentDoc = parentWin.document;
              const overlayDoc = {overlay_doc_json};

              parentWin.__bingoClosePointCountsOverlay = function () {{
                const frame = parentDoc.getElementById("bingo-point-counts-overlay-frame");
                if (frame) {{
                  frame.style.display = "none";
                  frame.setAttribute("aria-hidden", "true");
                }}
                if (parentWin.__bingoPointCountsIframeObserver) {{
                  parentWin.__bingoPointCountsIframeObserver.disconnect();
                  parentWin.__bingoPointCountsIframeObserver = null;
                }}
                parentDoc.querySelectorAll("iframe").forEach(function (node) {{
                  if (node.id === "bingo-point-counts-overlay-frame") {{
                    return;
                  }}
                  if (node.dataset.bingoPointCountsPointerBlocked === "1") {{
                    node.style.pointerEvents = node.dataset.bingoPointCountsPrevPointerEvents || "";
                    delete node.dataset.bingoPointCountsPointerBlocked;
                    delete node.dataset.bingoPointCountsPrevPointerEvents;
                  }}
                }});
                if (parentWin.__bingoPointCountsEscapeListener) {{
                  parentDoc.removeEventListener(
                    "keydown",
                    parentWin.__bingoPointCountsEscapeListener,
                    true
                  );
                  parentWin.__bingoPointCountsEscapeListener = null;
                }}
              }};

              parentWin.__bingoBlockPointCountsOverlayInterference = function () {{
                if (parentWin.__bingoPointCountsOverlayBusy) {{
                  return;
                }}
                parentWin.__bingoPointCountsOverlayBusy = true;
                try {{
                  parentDoc.querySelectorAll("iframe").forEach(function (node) {{
                    if (node.id === "bingo-point-counts-overlay-frame") {{
                      return;
                    }}
                    if (node.dataset.bingoPointCountsPointerBlocked === "1") {{
                      return;
                    }}
                    node.dataset.bingoPointCountsPointerBlocked = "1";
                    node.dataset.bingoPointCountsPrevPointerEvents = node.style.pointerEvents || "";
                    node.style.pointerEvents = "none";
                  }});
                  const frame = parentDoc.getElementById("bingo-point-counts-overlay-frame");
                  if (frame && parentDoc.body.lastElementChild !== frame) {{
                    parentDoc.body.appendChild(frame);
                  }}
                  if (frame) {{
                    frame.style.display = "block";
                    frame.style.pointerEvents = "auto";
                    frame.style.zIndex = "2147483647";
                  }}
                }} finally {{
                  parentWin.__bingoPointCountsOverlayBusy = false;
                }}
              }};

              parentWin.__bingoOpenPointCountsOverlay = function (nextOverlayDoc) {{
                const staleModal = parentDoc.getElementById("bingo-point-counts-modal");
                if (staleModal) {{
                  staleModal.remove();
                }}
                let frame = parentDoc.getElementById("bingo-point-counts-overlay-frame");
                if (!frame) {{
                  frame = parentDoc.createElement("iframe");
                  frame.id = "bingo-point-counts-overlay-frame";
                  frame.setAttribute("title", "Point Counts");
                  frame.setAttribute("aria-hidden", "true");
                  frame.style.cssText =
                    "position:fixed;inset:0;width:100%;height:100%;border:none;z-index:2147483647;background:transparent;display:none;pointer-events:auto;";
                }}
                parentDoc.body.appendChild(frame);
                frame.srcdoc = nextOverlayDoc;
                frame.style.display = "block";
                frame.style.pointerEvents = "auto";
                frame.setAttribute("aria-hidden", "false");
                parentWin.__bingoBlockPointCountsOverlayInterference();
                if (parentWin.__bingoPointCountsIframeObserver) {{
                  parentWin.__bingoPointCountsIframeObserver.disconnect();
                }}
                parentWin.__bingoPointCountsIframeObserver = new MutationObserver(function () {{
                  parentWin.__bingoBlockPointCountsOverlayInterference();
                }});
                parentWin.__bingoPointCountsIframeObserver.observe(parentDoc.body, {{
                  childList: true,
                  subtree: true,
                }});
                if (parentWin.__bingoPointCountsEscapeListener) {{
                  parentDoc.removeEventListener(
                    "keydown",
                    parentWin.__bingoPointCountsEscapeListener,
                    true
                  );
                }}
                parentWin.__bingoPointCountsEscapeListener = function (event) {{
                  if (event.key !== "Escape") {{
                    return;
                  }}
                  const activeFrame = parentDoc.getElementById("bingo-point-counts-overlay-frame");
                  if (!activeFrame || activeFrame.style.display === "none") {{
                    return;
                  }}
                  parentWin.__bingoClosePointCountsOverlay();
                }};
                parentDoc.addEventListener(
                  "keydown",
                  parentWin.__bingoPointCountsEscapeListener,
                  true
                );
              }};

              if (parentWin.__bingoPointCountsMessageListener) {{
                parentWin.removeEventListener("message", parentWin.__bingoPointCountsMessageListener);
              }}
              parentWin.__bingoPointCountsMessageListener = function (event) {{
                if (event.data !== "bingo-point-counts-close") {{
                  return;
                }}
                const frame = parentDoc.getElementById("bingo-point-counts-overlay-frame");
                if (!frame || frame.style.display === "none") {{
                  return;
                }}
                if (event.source && frame.contentWindow && event.source !== frame.contentWindow) {{
                  return;
                }}
                parentWin.__bingoClosePointCountsOverlay();
              }};
              parentWin.addEventListener("message", parentWin.__bingoPointCountsMessageListener);

              const openBtn = document.getElementById("bingo-point-counts-open");
              if (openBtn) {{
                openBtn.onclick = function () {{
                  parentWin.__bingoOpenPointCountsOverlay(overlayDoc);
                }};
              }}
            }})();
            </script>
            """,
            height=52,
            scrolling=False,
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
    return f"at end of Day {view_day}"


def _render_bingo_activity_feed_header(*, settings: BingoSettings) -> None:
    game_ended = _bingo_game_has_ended(settings=settings)
    show_as_of = not game_ended
    updated_ms = 0
    updated_nonce = 0
    if show_as_of:
        if "bingo_last_updated" not in st.session_state:
            _touch_bingo_live_updated()
        updated_ms = int(float(st.session_state.bingo_last_updated) * 1000)
        updated_nonce = int(st.session_state.get("bingo_live_updated_nonce", 0))

    as_of_html = (
        f'<span class="bingo-activity-as-of" id="bingo-activity-as-of-{updated_nonce}-{updated_ms}"></span>'
        if show_as_of
        else ""
    )
    as_of_script = (
        f"""
        <script>
          const updatedMs = {updated_ms};
          const labelEl = document.getElementById("bingo-activity-as-of-{updated_nonce}-{updated_ms}");
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
            labelEl.textContent = "as of " + formatAgo(updatedMs);
          }}
          tick();
          setInterval(tick, 1000);
        </script>
        """
        if show_as_of
        else ""
    )

    header_html = f"""
            <div class="bingo-activity-header">
              <span class="bingo-activity-title">Activity Feed</span>
              {as_of_html}
            </div>
            <style>
              html, body {{
                margin: 0;
                padding: 0;
                background: transparent !important;
                overflow: visible;
              }}
              .bingo-activity-header {{
                display: inline-flex;
                align-items: baseline;
                gap: 0.55rem;
                width: fit-content;
                font-family: "Source Sans Pro", "Segoe UI", sans-serif;
              }}
              .bingo-activity-title {{
                font-size: 1.625rem;
                font-weight: 600;
                color: rgb(250, 250, 250);
                line-height: 1.2;
              }}
              .bingo-activity-as-of {{
                font-size: 0.85rem;
                font-weight: 600;
                color: rgba(200, 205, 215, 0.88);
                white-space: nowrap;
              }}
            </style>
            {as_of_script}
            """

    with st.container(key="bingo_activity_header_shell"):
        if show_as_of:
            with st.container(
                horizontal=True,
                gap="small",
                vertical_alignment="bottom",
                key="bingo_activity_header_row",
            ):
                components.html(
                    header_html,
                    height=32,
                )
                st.button(
                    "",
                    key="bingo_activity_refresh",
                    type="primary",
                    icon=":material/refresh:",
                    help="Refresh board",
                    on_click=_on_bingo_refresh,
                )
        else:
            components.html(
                header_html,
                height=32,
            )


def _collect_submission_proof_paths(
    entries: list[BingoChartLeaderboardEntry],
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.source != SCORE_SOURCE_SUBMISSION:
            continue
        path = str(entry.proof_path or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _build_bingo_chart_modal_payload(
    charts: list[BingoChart],
    entries_by_chart: dict[tuple[str, str], list[BingoChartLeaderboardEntry]],
    *,
    roster: dict[str, list[BingoTeamPlayer]],
    highlight_player_id: str | None = None,
    sign_proofs: bool = False,
) -> dict[str, dict[str, str]]:
    """Build chart modal HTML.

    ``sign_proofs=False`` (default) skips Supabase signed-URL calls so the board
    can paint quickly. Proof buttons keep ``data-proof-path``; signed URLs are
    filled in when a chart scoreboard is refreshed.
    """
    payload: dict[str, dict[str, str]] = {}
    merged_by_key: dict[str, list[BingoChartLeaderboardEntry]] = {}
    proof_urls: dict[str, str] = {}
    if sign_proofs:
        all_paths: list[str] = []
        for chart in charts:
            raw_entries = entries_by_chart.get((chart.song, chart.difficulty), [])
            entries = merge_chart_leaderboard_with_roster(roster, raw_entries)
            key = f"{chart.row},{chart.column}"
            merged_by_key[key] = entries
            all_paths.extend(_collect_submission_proof_paths(entries))
        proof_urls = prefetch_bingo_proof_signed_urls(all_paths)

    for chart in charts:
        key = f"{chart.row},{chart.column}"
        if key in merged_by_key:
            entries = merged_by_key[key]
        else:
            raw_entries = entries_by_chart.get((chart.song, chart.difficulty), [])
            entries = merge_chart_leaderboard_with_roster(roster, raw_entries)
        entries_by_id = {entry.player_id: entry for entry in entries}
        difficulty = html.escape(_difficulty_label(chart.difficulty, chart.level))
        chart_payload: dict[str, str] = {
            "title_html": (
                f'{html.escape(chart.display_name)} '
                f'<span class="bingo-chart-modal-diff">{difficulty}</span>'
            ),
            "table_html": _render_bingo_chart_leaderboard_table_html(
                entries,
                song=chart.song,
                difficulty=chart.difficulty,
                highlight_player_id=highlight_player_id,
                proof_urls=proof_urls,
            ),
        }
        upscore_entries = {
            player_id: (entry.team, entry.display_name, int(entry.score))
            for player_id, entry in entries_by_id.items()
        }
        upscore = build_chart_upscore_payload(
            song=chart.song,
            difficulty=chart.difficulty,
            roster=roster,
            entries_by_id=upscore_entries,
            default_player_id=highlight_player_id,
            max_score=bingo_chart_max_score(chart.song, chart.difficulty),
        )
        if upscore is not None:
            chart_payload["upscore_json"] = json.dumps(upscore)
        payload[key] = chart_payload
    return payload


def _emit_bingo_chart_refresh_payload(
    *,
    settings: BingoSettings,
    charts: list[BingoChart],
    completed_days: int,
    row: int,
    col: int,
) -> None:
    """Load one chart leaderboard from DB and queue a postMessage emit."""
    by_coord = {(chart.row, chart.column): chart for chart in charts}
    chart = by_coord.get((int(row), int(col)))
    if chart is None:
        return

    day_count = max(1, int(settings.day_count or 1))
    view_day = _resolve_bingo_view_day(completed_days, day_count=day_count)
    end_time = (
        bingo_day_end(settings.start_time, view_day)
        if view_day is not None and settings.start_time is not None
        else None
    )
    entries = load_bingo_chart_player_leaderboard(
        song=chart.song,
        difficulty=chart.difficulty,
        start_time=settings.start_time,
        end_time=end_time,
    )
    teams = load_bingo_teams_by_ex_rating()
    merged = merge_chart_leaderboard_with_roster(teams, entries)
    highlight_id = st.session_state.get("bingo_view_player_id")
    proof_urls = prefetch_bingo_proof_signed_urls(
        _collect_submission_proof_paths(merged)
    )
    table_html = _render_bingo_chart_leaderboard_table_html(
        merged,
        song=chart.song,
        difficulty=chart.difficulty,
        highlight_player_id=highlight_id,
        proof_urls=proof_urls,
    )
    entries_by_id = {entry.player_id: entry for entry in merged}
    upscore_entries = {
        player_id: (entry.team, entry.display_name, int(entry.score))
        for player_id, entry in entries_by_id.items()
    }
    upscore = build_chart_upscore_payload(
        song=chart.song,
        difficulty=chart.difficulty,
        roster=teams,
        entries_by_id=upscore_entries,
        default_player_id=highlight_id,
        max_score=bingo_chart_max_score(chart.song, chart.difficulty),
    )
    payload: dict[str, str | int] = {
        "row": int(row),
        "col": int(col),
        "table_html": table_html,
        "updated_ms": int(time.time() * 1000),
    }
    if upscore is not None:
        payload["upscore_json"] = json.dumps(upscore)
    st.session_state["bingo_chart_refresh_emit"] = payload


@st.fragment
def _render_bingo_chart_refresh_bridge(
    *,
    settings: BingoSettings,
    charts: list[BingoChart],
    completed_days: int,
) -> None:
    """Hidden per-chart refresh buttons; reruns alone to reload one scoreboard."""
    board_charts = bingo_charts_on_board(charts, max(1, int(settings.board_width)))

    def make_handler(chart_row: int, chart_col: int):
        def handler() -> None:
            _emit_bingo_chart_refresh_payload(
                settings=settings,
                charts=charts,
                completed_days=completed_days,
                row=chart_row,
                col=chart_col,
            )

        return handler

    # Keep styles + buttons inside the zero-height shell so this fragment
    # does not add vertical gap between player controls and the board.
    with st.container(key="bingo_chart_refresh_shell"):
        st.markdown(
            """
            <style>
            .st-key-bingo_chart_refresh_shell,
            .st-key-bingo-chart-refresh-shell,
            .stElementContainer:has(.st-key-bingo_chart_refresh_shell),
            .stElementContainer:has(.st-key-bingo-chart-refresh-shell),
            [data-testid="stElementContainer"]:has(.st-key-bingo_chart_refresh_shell),
            [data-testid="stElementContainer"]:has(.st-key-bingo-chart-refresh-shell) {
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
                min-height: 0 !important;
                max-height: 0 !important;
                overflow: hidden !important;
                margin: 0 !important;
                padding: 0 !important;
                border: 0 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        for chart in board_charts:
            st.button(
                f"Refresh chart {chart.row},{chart.column}",
                key=f"bingo_chart_refresh_{chart.row}_{chart.column}",
                on_click=make_handler(chart.row, chart.column),
            )

    emit_payload = st.session_state.pop("bingo_chart_refresh_emit", None)
    if emit_payload is not None:
        payload_json = json.dumps(emit_payload).replace("</", "<\\/")
        components.html(
            f"""
            <script>
            (function () {{
              const payload = {payload_json};
              try {{
                const iframes = window.parent.document.querySelectorAll("iframe");
                for (const iframe of iframes) {{
                  try {{
                    iframe.contentWindow.postMessage({{
                      type: "bingo-chart-leaderboard-refresh",
                      payload: payload,
                    }}, "*");
                  }} catch (error) {{}}
                }}
              }} catch (error) {{}}
            }})();
            </script>
            """,
            height=0,
            scrolling=False,
        )


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
    .bingo-board-root.hide-lines .bingo-line-svg,
    .bingo-board-root.hide-colors .bingo-line-svg {{
        opacity: 0;
        visibility: hidden;
        transition: opacity 0.14s ease, visibility 0s linear 0.14s;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell-mid,
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell-bot {{
        overflow: hidden;
        min-height: 0;
        opacity: 0;
        transform: translateY(-0.35rem);
        transition: opacity 0.22s ease, transform 0.22s ease;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell {{
        cursor: pointer;
        grid-template-rows: 1fr 0fr 0fr;
        place-items: stretch;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell-top {{
        position: relative;
        min-height: 0;
        height: 100%;
        width: 100%;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell-header {{
        position: absolute;
        left: 0;
        right: 0;
        width: 100%;
        top: 50%;
        transform: translateY(-50%);
        transition: top 0.28s ease, transform 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell-song {{
        font-size: 1.05rem;
        -webkit-line-clamp: unset;
        transition: font-size 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell-diff {{
        font-size: 0.95rem;
        margin-top: 0.25rem;
        transition: font-size 0.28s ease, margin-top 0.28s ease;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover {{
        z-index: 6;
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-mid,
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-bot {{
        opacity: 1;
        transform: translateY(0);
        transition-delay: 0.05s;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-top {{
        min-height: 3.5rem;
        height: auto;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-header {{
        top: 0;
        transform: translateY(0);
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-song {{
        font-size: 0.95rem;
        -webkit-line-clamp: 2;
    }}
    .bingo-board-root:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-diff {{
        font-size: 0.88rem;
        margin-top: 0.1rem;
    }}
    .bingo-board-root.is-detailed .bingo-cell {{
        grid-template-rows: minmax(3.5rem, auto) minmax(4.25rem, 1fr) minmax(2.15rem, auto);
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
    .bingo-board-root.has-player-data .bingo-cell-view {{
        transition: opacity 0.22s ease;
    }}
    .bingo-board-root.has-player-data:not(.is-player-board) .bingo-cell-player-view {{
        opacity: 0;
        pointer-events: none;
        position: absolute;
        inset: 0;
        z-index: 0;
    }}
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell {{
        grid-template-rows: 1fr 0fr;
    }}
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell-body {{
        position: relative;
        overflow: hidden;
        min-height: 0;
    }}
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell:hover {{
        grid-template-rows: minmax(3.5rem, auto) 1fr;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell {{
        grid-template-rows: minmax(3.5rem, auto) 1fr;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell-body {{
        position: relative;
        min-height: 0;
        display: grid;
        grid-template-rows: minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell-view {{
        grid-row: 1 / -1;
        grid-column: 1;
        display: grid;
        grid-template-rows: minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell-team-view {{
        opacity: 1;
        pointer-events: auto;
        display: flex;
        flex-direction: column;
        min-height: 0;
        height: 100%;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell-player-view {{
        opacity: 0;
        pointer-events: none;
    }}
    /* Detailed + selected player: hover reveals player-board view (inverse of player-board hover). */
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view:not(:empty)) {{
        z-index: 6;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view:not(:empty)) .bingo-cell-team-view {{
        opacity: 0;
        pointer-events: none;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view:not(:empty)) .bingo-cell-player-view {{
        opacity: 1;
        pointer-events: auto;
        z-index: 1;
        display: grid;
        grid-template-rows: minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view:not(:empty)) .bingo-cell-player-view:has(.bingo-cell-crit-row) {{
        grid-template-rows: minmax(3.25rem, 1fr) auto minmax(2.15rem, auto);
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view--not-played) .bingo-cell-player-view {{
        grid-template-rows: minmax(4.25rem, 1fr);
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view:not(:empty)) .bingo-cell-player-view .bingo-cell-mid,
    .bingo-board-root.has-player-data.is-detailed .bingo-cell:hover:has(.bingo-cell-player-view:not(:empty)) .bingo-cell-player-view .bingo-cell-bot {{
        opacity: 1;
        transform: none;
    }}
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-body {{
        min-height: 0;
        height: 100%;
        display: flex;
        flex-direction: column;
    }}
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-team-view {{
        position: relative;
        z-index: 1;
        display: flex;
        flex-direction: column;
        flex: 1 1 auto;
        min-height: 0;
        height: 100%;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell-team-view .bingo-cell-mid,
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-team-view .bingo-cell-mid {{
        flex: 1 1 auto;
        opacity: 1;
        transform: none;
    }}
    .bingo-board-root.has-player-data.is-detailed .bingo-cell-team-view .bingo-cell-bot,
    .bingo-board-root.has-player-data:not(.is-detailed):not(.is-player-board) .bingo-cell:hover .bingo-cell-team-view .bingo-cell-bot {{
        flex: 0 0 auto;
        margin-top: auto;
        opacity: 1;
        transform: none;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell {{
        grid-template-rows: minmax(3.5rem, auto) minmax(6.4rem, 1fr);
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-top {{
        min-height: 3.5rem;
        height: auto;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-header {{
        position: absolute;
        left: 0;
        right: 0;
        width: 100%;
        top: 0;
        transform: translateY(0);
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-song {{
        font-size: 0.95rem;
        -webkit-line-clamp: 2;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-diff {{
        font-size: 0.88rem;
        margin-top: 0.1rem;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-body {{
        position: relative;
        min-height: 0;
        display: grid;
        grid-template-rows: minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-view {{
        grid-row: 1 / -1;
        grid-column: 1;
        display: grid;
        grid-template-rows: minmax(4.25rem, 1fr) minmax(2.15rem, auto);
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-team-view {{
        opacity: 0;
        pointer-events: none;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-player-view {{
        opacity: 1;
        pointer-events: auto;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-player-view:has(.bingo-cell-crit-row) {{
        grid-template-rows: minmax(3.25rem, 1fr) auto minmax(2.15rem, auto);
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-player-view .bingo-cell-mid,
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-player-view .bingo-cell-bot {{
        opacity: 1;
        transform: none;
    }}
    .bingo-cell-crit-row {{
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 0;
        padding: 0.08rem 0.4rem 0.12rem;
    }}
    .bingo-cell-crit-disabled {{
        display: inline-block;
        color: #ff5c67;
        background: #000000;
        font-size: 0.78rem;
        font-weight: 800;
        line-height: 1.2;
        padding: 0.16rem 0.42rem;
        border-radius: 0.18rem;
        letter-spacing: 0.03em;
        white-space: nowrap;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell:hover {{
        z-index: 6;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell:hover .bingo-cell-team-view {{
        opacity: 1;
        pointer-events: auto;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell:hover .bingo-cell-player-view {{
        opacity: 0;
        pointer-events: none;
    }}
    .bingo-cell-body {{
        min-height: 0;
    }}
    .bingo-cell-player-footer {{
        width: 100%;
        color: rgba(245, 245, 245, 0.96);
        font-size: 1.05rem;
        font-weight: 700;
        line-height: 1.15;
        padding: 0.2rem 0.4rem;
        box-sizing: border-box;
    }}
    .bingo-cell-player-score {{
        color: rgba(245, 245, 245, 0.96) !important;
    }}
    .bingo-cell-leader--not-played {{
        min-height: auto;
    }}
    .bingo-cell-leader-team--spacer {{
        visibility: hidden;
    }}
    .bingo-cell-not-played {{
        display: inline-block;
        color: #ff5c67;
        background: #000000;
        font-size: 1.05rem;
        font-weight: 800;
        line-height: 1.2;
        padding: 0.22rem 0.55rem;
        border-radius: 0.18rem;
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-body--player-not-played {{
        grid-template-rows: minmax(4.25rem, 1fr);
    }}
    .bingo-board-root.is-player-board.has-player-data .bingo-cell-player-view--not-played {{
        grid-template-rows: minmax(4.25rem, 1fr);
    }}
    .bingo-cell-player-view .bingo-cell-bot {{
        justify-content: center;
        align-items: center;
        min-height: 2.15rem;
    }}
    .bingo-cell {{
        --bingo-cell-bg: {BINGO_CELL_BG};
        position: relative;
        background-color: var(--bingo-cell-bg);
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
        transition: background-color 0.22s ease, grid-template-rows 0.28s ease;
    }}
    .bingo-board-root.hide-colors:not(.is-detailed):not(.is-player-board) .bingo-cell,
    .bingo-board-root.hide-colors.is-detailed .bingo-cell,
    .bingo-board-root.hide-colors.is-player-board.has-player-data .bingo-cell,
    .bingo-board-root.hide-colors .bingo-cell {{
        background-color: {BINGO_CELL_BG};
    }}
    .bingo-board-root.hide-colors:not(.is-detailed):not(.is-player-board) .bingo-cell:hover,
    .bingo-board-root.hide-colors.is-detailed .bingo-cell:hover,
    .bingo-board-root.hide-colors.is-player-board.has-player-data .bingo-cell:hover,
    .bingo-board-root.hide-colors .bingo-cell:hover {{
        background-color: var(--bingo-cell-bg);
    }}
    .bingo-board-root.hide-colors .bingo-cell-claim-outline {{
        opacity: 0;
    }}
    .bingo-board-root.hide-colors .bingo-cell:hover .bingo-cell-claim-outline {{
        opacity: 1;
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
        opacity: 1;
        transition: opacity 0.22s ease;
    }}
    .bingo-line-svg {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        z-index: 3;
        pointer-events: none;
        overflow: visible;
        opacity: 1;
        visibility: visible;
        transition: opacity 0.14s ease, visibility 0s linear 0s;
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
        transition: min-height 0.28s ease, height 0.28s ease;
    }}
    .bingo-cell-header {{
        width: 100%;
        transition: top 0.28s ease, transform 0.28s ease;
    }}
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
        transition: font-size 0.28s ease;
    }}
    .bingo-cell-diff {{
        font-size: 0.88rem;
        font-weight: 400;
        line-height: 1.15;
        width: 100%;
        margin-top: 0.1rem;
        color: rgba(234, 234, 234, 0.82);
        transition: font-size 0.28s ease, margin-top 0.28s ease;
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
        width: fit-content;
        max-width: min(calc(100% - 3rem), 40rem);
        max-height: min(80vh, 760px);
        overflow-x: auto;
        overflow-y: auto;
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
    .bingo-chart-modal-header {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 0.75rem;
        margin: 0 2.2rem 0.2rem 0;
    }}
    .bingo-chart-modal-title {{
        font-size: 1.35rem;
        font-weight: 800;
        color: #f5f5f5;
        margin: 0;
        line-height: 1.25;
        flex: 1 1 auto;
        min-width: 0;
    }}
    .bingo-chart-modal-diff {{
        font-weight: 400;
        color: rgba(234, 234, 234, 0.82);
    }}
    {_BINGO_CHART_MODAL_SUBTITLE_CSS}
    .bingo-chart-modal-subtitle {{
        font-size: 0.95rem;
        font-weight: 600;
        color: rgba(234, 234, 234, 0.62);
    }}
    {_BINGO_CHART_MODAL_TABLE_LAYOUT_CSS}
    {_BINGO_CHART_JUDGEMENT_EXPAND_CSS}
    .bingo-chart-modal-table {{
        width: max-content;
        max-width: 100%;
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
    {_BINGO_CHART_MODAL_POINTS_COLUMN_CSS}
    {_BINGO_CHART_UPSCORE_CSS}
    .bingo-chart-modal-proof-col {{
        width: 2rem;
        min-width: 2rem;
        text-align: center !important;
        padding-left: 0.2rem !important;
        padding-right: 0.35rem !important;
    }}
    .bingo-chart-modal-table th.bingo-chart-modal-proof-col {{
        color: transparent;
        font-size: 0;
        user-select: none;
    }}
    .bingo-chart-modal-table tbody tr.bingo-chart-modal-row--highlighted td {{
        background: rgba(255, 255, 255, 0.085);
    }}
    .bingo-chart-modal-proof-badge,
    .bingo-chart-modal-proof-btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.15rem;
        height: 1.15rem;
        flex: 0 0 auto;
        border-radius: 999px;
        box-sizing: border-box;
    }}
    .bingo-chart-modal-proof-badge {{
        font-size: 0.72rem;
        font-weight: 800;
        line-height: 1;
    }}
    .bingo-chart-modal-proof-badge--ingame {{
        background: rgba(94, 224, 154, 0.22);
        color: #5ee09a;
        border: 1px solid rgba(94, 224, 154, 0.55);
    }}
    .bingo-chart-modal-proof-badge--missing {{
        background: rgba(245, 213, 71, 0.14);
        color: rgba(245, 213, 71, 0.92);
        border: 1px solid rgba(245, 213, 71, 0.38);
    }}
    .bingo-chart-modal-proof-btn {{
        padding: 0;
        border: 1px solid rgba(110, 176, 255, 0.42);
        background: rgba(110, 176, 255, 0.14);
        color: #9ec8ff;
        cursor: pointer;
    }}
    .bingo-chart-modal-proof-btn:hover {{
        background: rgba(110, 176, 255, 0.24);
        color: #d7eaff;
    }}
    .bingo-chart-modal-proof-btn svg {{
        width: 0.78rem;
        height: 0.78rem;
        display: block;
    }}
    .bingo-proof-modal-overlay {{
        position: fixed;
        inset: 0;
        z-index: 1001;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        pointer-events: none;
        transition: opacity 180ms ease;
    }}
    .bingo-proof-modal-overlay.is-open {{
        opacity: 1;
        pointer-events: auto;
    }}
    .bingo-proof-modal-backdrop {{
        position: absolute;
        inset: 0;
        border: 0;
        background: rgba(4, 8, 18, 0.82);
        cursor: pointer;
        z-index: 0;
    }}
    .bingo-proof-modal-panel {{
        position: relative;
        z-index: 2;
        max-width: min(92vw, 960px);
        max-height: min(88vh, 920px);
        padding: 0.75rem;
        border-radius: 0.75rem;
        border: 1px solid rgba(120, 190, 255, 0.24);
        background: rgba(12, 18, 36, 0.96);
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
    }}
    .bingo-proof-modal-close {{
        position: absolute;
        top: 0.35rem;
        right: 0.45rem;
        border: 0;
        background: transparent;
        color: rgba(245, 245, 245, 0.72);
        font-size: 1.5rem;
        line-height: 1;
        cursor: pointer;
    }}
    .bingo-proof-modal-close:hover {{
        color: #ffffff;
    }}
    .bingo-proof-modal-image {{
        display: block;
        max-width: min(88vw, 920px);
        max-height: min(82vh, 860px);
        width: auto;
        height: auto;
        margin: 0 auto;
        border-radius: 0.35rem;
    }}
    .bingo-chart-modal-empty {{
        padding: 1.25rem 0.5rem;
        color: rgba(234, 234, 234, 0.72);
        font-size: 1rem;
        font-weight: 600;
    }}
    """ + _bingo_rest_claimed_watermark_css()


def _bingo_board_component_height(rows: int, cols: int) -> int:
    cell_px = 204
    _ = cols
    return max(260, rows * cell_px)


_BINGO_UPSCORE_CALCULATOR_JS = r"""
          const TEAM_COLORS = { Eve: "#6eb0ff", Grace: "#ff7a84", Rest: "#5ee09a" };
          const TEAM_ROW_BG = { Eve: "#0f1f3a", Grace: "#2a1218", Rest: "#0f2418" };
          let currentUpscore = null;
          let selectedUpscorePlayerId = null;
          let upscoreAutoSliderPlayerId = null;
          let currentLeadThresholdPct = null;

          const upscoreBtn = document.getElementById("bingo-chart-upscore-btn");
          const upscorePanel = document.getElementById("bingo-chart-upscore-panel");
          const upscoreSearch = document.getElementById("bingo-upscore-search");
          const upscoreSelect = document.getElementById("bingo-upscore-player-select");
          const upscorePicker = document.getElementById("bingo-upscore-player-picker");
          const upscorePlayerName = document.getElementById("bingo-upscore-player-name");
          const upscoreCurrentScore = document.getElementById("bingo-upscore-current-score");
          const upscoreCurrentPct = document.getElementById("bingo-upscore-current-pct");
          const upscoreTargetPct = document.getElementById("bingo-upscore-target-pct");
          const upscoreSlider = document.getElementById("bingo-upscore-slider");
          const upscoreLeadMarker = document.getElementById("bingo-upscore-lead-marker");
          const upscoreRequiredScore = document.getElementById("bingo-upscore-required-score");
          const upscoreRequiredPlacement = document.getElementById("bingo-upscore-required-placement");
          const upscorePointChanges = document.getElementById("bingo-upscore-point-changes");

          function formatScore(score) {
            return Math.round(Number(score)).toLocaleString("en-US");
          }

          function formatPct(pct) {
            return Number(pct).toFixed(2) + "%";
          }

          function accuracyFormulaPoints(exAccuracy, floor) {
            const x = Math.max(Number(exAccuracy), Number(floor));
            const accuracyTerm = Math.pow(x, 3) / Math.pow(100, 3);
            const denominator = 1 - ((x - 1) / 100);
            if (denominator <= 0) return 0;
            return accuracyTerm * (75 + (0.25 / denominator));
          }

          function flooredAccuracyPoints(floor) {
            return accuracyFormulaPoints(floor, floor);
          }

          function playerAccuracyPoints(score, maxScore, floor) {
            const s = Number(score);
            if (s <= 0) return Math.max(0, flooredAccuracyPoints(floor) - 1);
            const exAcc = (s / maxScore) * 100;
            return accuracyFormulaPoints(exAcc, floor);
          }

          function placementBonus(rank) {
            if (rank <= 0) return 0;
            if (rank <= 11) return 100 - (rank - 1) * 3;
            if (rank <= 22) return 68 - (rank - 12) * 2;
            if (rank <= 30) return 47 - (rank - 23);
            return Math.max(0, 40 - (rank - 30));
          }

          function placementRanksByScore(players) {
            const ordered = players.slice().sort((a, b) => {
              if (b.score !== a.score) return b.score - a.score;
              return a.player_id.localeCompare(b.player_id);
            });
            const ranks = {};
            let index = 0;
            while (index < ordered.length) {
              let next = index + 1;
              while (next < ordered.length && ordered[next].score === ordered[index].score) {
                next += 1;
              }
              const rank = index + 1;
              for (let i = index; i < next; i += 1) {
                ranks[ordered[i].player_id] = rank;
              }
              index = next;
            }
            return ranks;
          }

          function computeBreakdowns(players, maxScore, floor) {
            const ranks = placementRanksByScore(players);
            const breakdowns = {};
            for (const player of players) {
              const accuracy = playerAccuracyPoints(player.score, maxScore, floor);
              const placement = placementBonus(ranks[player.player_id]);
              breakdowns[player.player_id] = {
                accuracy,
                placement,
                total: accuracy + placement,
                rank: ranks[player.player_id],
              };
            }
            return breakdowns;
          }

          function teamTotals(players, maxScore, floor) {
            const breakdowns = computeBreakdowns(players, maxScore, floor);
            const totals = { Eve: 0, Grace: 0, Rest: 0 };
            for (const player of players) {
              totals[player.team] += breakdowns[player.player_id].total;
            }
            return totals;
          }

          function exAccuracyForScore(score, maxScore) {
            if (maxScore <= 0) return 0;
            return (Number(score) / maxScore) * 100;
          }

          function requiredScoreForPercent(maxScore, pct) {
            const clamped = Math.max(0, Math.min(Number(pct), 100));
            return Math.floor((clamped / 100) * maxScore);
          }

          function minimumTargetPctForScore(maxScore, score) {
            const targetScore = Math.max(0, Math.floor(Number(score)));
            if (maxScore <= 0 || targetScore <= 0) {
              return 0;
            }
            let pct = Math.ceil((targetScore / maxScore) * 10000) / 100;
            while (requiredScoreForPercent(maxScore, pct) < targetScore && pct < 100) {
              pct = Math.round((pct + 0.01) * 100) / 100;
            }
            return Math.min(pct, 100);
          }

          function formatBingoPointsBody(absVal) {
            const magnitude = Math.abs(Number(absVal));
            if (magnitude >= 10) return String(Math.round(magnitude));
            if (magnitude === 0) return "0";
            if (magnitude < 0.1) return magnitude.toFixed(2);
            return magnitude.toFixed(1);
          }

          function formatBingoPoints(value, signed) {
            const num = Number(value);
            const body = formatBingoPointsBody(num);
            if (!signed) {
              return num < 0 ? "-" + body : body;
            }
            if (num > 0) return "+" + body;
            if (num < 0) return "-" + body;
            return body;
          }

          function signedDelta(value) {
            const num = Number(value);
            if (num <= 0) {
              if (num < 0) return String(Math.round(num));
              return "0";
            }
            return "+" + formatBingoPointsBody(num);
          }

          function otherTeamsMaxTotal(totals, team) {
            let otherMax = 0;
            for (const otherTeam of ["Eve", "Grace", "Rest"]) {
              if (otherTeam !== team) {
                otherMax = Math.max(otherMax, totals[otherTeam]);
              }
            }
            return otherMax;
          }

          function isTeamLeading(player, score, maxScore, floor) {
            const beforePlayers = currentUpscore.players.map((p) => ({ ...p }));
            const afterPlayers = beforePlayers.map((p) => (
              p.player_id === player.player_id ? { ...p, score: Number(score) } : { ...p }
            ));
            const afterTeams = teamTotals(afterPlayers, maxScore, floor);
            return afterTeams[player.team] > otherTeamsMaxTotal(afterTeams, player.team);
          }

          function computeLeadThresholdPct(player, maxScore, floor) {
            const beforePlayers = currentUpscore.players.map((p) => ({ ...p }));
            const beforeTeams = teamTotals(beforePlayers, maxScore, floor);
            const currentPct = exAccuracyForScore(player.score, maxScore);
            const minScore = Math.max(
              Number(player.score) || 0,
              requiredScoreForPercent(maxScore, currentPct)
            );

            if (beforeTeams[player.team] > otherTeamsMaxTotal(beforeTeams, player.team)) {
              return null;
            }
            if (!isTeamLeading(player, maxScore, maxScore, floor)) {
              return null;
            }

            let lo = minScore;
            let hi = maxScore;
            let bestScore = maxScore;
            while (lo <= hi) {
              const mid = Math.floor((lo + hi) / 2);
              if (isTeamLeading(player, mid, maxScore, floor)) {
                bestScore = mid;
                hi = mid - 1;
              } else {
                lo = mid + 1;
              }
            }
            return minimumTargetPctForScore(maxScore, bestScore);
          }

          function updateLeadMarker() {
            if (!upscoreLeadMarker) return;
            if (currentLeadThresholdPct === null) {
              upscoreLeadMarker.hidden = true;
              return;
            }
            const min = Number(upscoreSlider.min);
            const max = Number(upscoreSlider.max);
            if (currentLeadThresholdPct <= min || currentLeadThresholdPct > max) {
              upscoreLeadMarker.hidden = true;
              return;
            }
            const ratio = (currentLeadThresholdPct - min) / (max - min);
            upscoreLeadMarker.hidden = false;
            upscoreLeadMarker.style.left = "calc(0.55rem + (100% - 1.1rem) * " + ratio + ")";
          }

          function activeUpscoreHighlightPlayerId() {
            return selectedUpscorePlayerId || null;
          }

          function syncUpscoreScoreboardHighlight() {
            const playerId = activeUpscoreHighlightPlayerId();
            bodyEl.querySelectorAll(".bingo-chart-modal-data-row").forEach((row) => {
              const rowPlayerId = row.dataset.playerId || "";
              row.classList.toggle(
                "bingo-chart-modal-row--highlighted",
                !!playerId && rowPlayerId === playerId
              );
            });
          }

          function resetUpscorePanel() {
            currentUpscore = null;
            selectedUpscorePlayerId = null;
            upscoreAutoSliderPlayerId = null;
            currentLeadThresholdPct = null;
            upscorePanel.classList.remove("is-open");
            upscorePanel.setAttribute("aria-hidden", "true");
            upscoreBtn.classList.remove("is-active");
            upscoreBtn.hidden = true;
            upscoreSearch.value = "";
            if (upscoreLeadMarker) upscoreLeadMarker.hidden = true;
          }

          function filteredUpscorePlayers() {
            if (!currentUpscore) return [];
            const query = upscoreSearch.value.trim().toLowerCase();
            return currentUpscore.players
              .filter((player) => {
                if (!query) return true;
                const label = (player.display_name + " " + player.team).toLowerCase();
                return label.includes(query);
              })
              .slice()
              .sort((a, b) => {
                const byName = a.display_name.localeCompare(b.display_name, undefined, { sensitivity: "base" });
                if (byName !== 0) return byName;
                return a.player_id.localeCompare(b.player_id);
              });
          }

          function renderUpscorePlayerOptions() {
            const players = filteredUpscorePlayers();
            const query = upscoreSearch.value.trim();
            upscoreSelect.innerHTML = "";

            if (!query) {
              const placeholder = document.createElement("option");
              placeholder.value = "";
              placeholder.textContent = "Select a player...";
              placeholder.disabled = true;
              upscoreSelect.appendChild(placeholder);
            } else if (players.length === 0) {
              const placeholder = document.createElement("option");
              placeholder.value = "";
              placeholder.textContent = "No matching players";
              placeholder.disabled = true;
              upscoreSelect.appendChild(placeholder);
              selectedUpscorePlayerId = null;
              upscoreSelect.value = "";
              return;
            }

            for (const player of players) {
              const option = document.createElement("option");
              option.value = player.player_id;
              option.textContent = player.display_name + " (" + player.team + ")";
              upscoreSelect.appendChild(option);
            }

            if (query && players.length > 0) {
              selectedUpscorePlayerId = players[0].player_id;
              upscoreSelect.value = selectedUpscorePlayerId;
            } else if (selectedUpscorePlayerId && players.some((p) => p.player_id === selectedUpscorePlayerId)) {
              upscoreSelect.value = selectedUpscorePlayerId;
            } else {
              selectedUpscorePlayerId = null;
              upscoreSelect.value = "";
            }
          }

          function selectedUpscorePlayer() {
            if (!currentUpscore || !selectedUpscorePlayerId) return null;
            return currentUpscore.players.find((p) => p.player_id === selectedUpscorePlayerId) || null;
          }

          function renderUpscoreResults() {
            const player = selectedUpscorePlayer();
            if (!currentUpscore || !player) {
              upscorePlayerName.textContent = "";
              upscoreCurrentScore.textContent = "—";
              upscoreCurrentPct.textContent = "—";
              upscoreTargetPct.textContent = "—";
              upscoreRequiredScore.innerHTML = "—";
              if (upscoreRequiredPlacement) upscoreRequiredPlacement.textContent = "—";
              upscorePointChanges.innerHTML = "";
              return;
            }

            const maxScore = currentUpscore.max_score;
            const floor = currentUpscore.ex_accuracy_floor;
            const currentPct = exAccuracyForScore(player.score, maxScore);
            const targetPct = Math.max(currentPct, Number(upscoreSlider.value));
            const requiredScore = requiredScoreForPercent(maxScore, targetPct);

            upscorePlayerName.textContent = player.display_name;
            upscorePlayerName.style.color = TEAM_COLORS[player.team] || "#eaeaea";
            upscoreCurrentScore.textContent = player.score > 0 ? formatScore(player.score) : "Not Played";
            upscoreCurrentPct.textContent = player.score > 0 ? formatPct(currentPct) : "—";
            upscoreTargetPct.textContent = formatPct(targetPct);

            const beforePlayers = currentUpscore.players.map((p) => ({ ...p }));
            const afterPlayers = beforePlayers.map((p) => (
              p.player_id === player.player_id ? { ...p, score: requiredScore } : { ...p }
            ));
            const beforeBreakdowns = computeBreakdowns(beforePlayers, maxScore, floor);
            const afterBreakdowns = computeBreakdowns(afterPlayers, maxScore, floor);

            const currentScore = Math.max(0, Number(player.score) || 0);
            const scoreDelta = requiredScore - currentScore;
            const scoreDiffClass = scoreDelta > 0
              ? ""
              : scoreDelta < 0
                ? " is-negative"
                : " is-neutral";
            let scoreDiffText = "+0";
            if (scoreDelta > 0) {
              scoreDiffText = "+" + formatScore(scoreDelta);
            } else if (scoreDelta < 0) {
              scoreDiffText = "-" + formatScore(Math.abs(scoreDelta));
            }
            upscoreRequiredScore.innerHTML = (
              formatScore(requiredScore)
              + '<span class="bingo-upscore-required-points-diff' + scoreDiffClass + '">('
              + scoreDiffText
              + ")</span>"
            );

            const beforeTeams = teamTotals(beforePlayers, maxScore, floor);
            const afterTeams = teamTotals(afterPlayers, maxScore, floor);

            const beforeRank = beforeBreakdowns[player.player_id].rank;
            const afterRank = afterBreakdowns[player.player_id].rank;
            const climb = beforeRank - afterRank;
            if (upscoreRequiredPlacement) {
              let placementText = String(afterRank);
              if (climb > 0) {
                placementText += '<span class="bingo-upscore-placement-climb">(↑ ' + climb + ")</span>";
              }
              upscoreRequiredPlacement.innerHTML = placementText;
            }

            const teamOrder = ["Eve", "Grace", "Rest"].slice().sort((a, b) => a.localeCompare(b));
            let leaderTeam = teamOrder[0];
            let leaderTotal = afterTeams[leaderTeam];
            for (const team of teamOrder) {
              if (afterTeams[team] > leaderTotal) {
                leaderTeam = team;
                leaderTotal = afterTeams[team];
              }
            }

            const rows = [];
            for (const team of teamOrder) {
              const delta = afterTeams[team] - beforeTeams[team];
              const deltaClass = delta > 0 ? "is-positive" : delta < 0 ? "is-negative" : "is-neutral";
              const leaderClass = team === leaderTeam ? " is-leader" : "";
              const rowBg = TEAM_ROW_BG[team] || "#10162d";
              const teamColor = TEAM_COLORS[team] || "#eaeaea";
              rows.push(
                "<tr>"
                + '<td class="bingo-upscore-change-team" style="background:' + rowBg + "; color:" + teamColor + ';">'
                + team + "</td>"
                + '<td class="bingo-upscore-change-delta ' + deltaClass + '" style="background:' + rowBg + ';">'
                + signedDelta(delta) + "</td>"
                + '<td class="bingo-upscore-change-arrow" style="background:' + rowBg + ';">→</td>'
                + '<td class="bingo-upscore-change-total-cell" style="background:' + rowBg + ';">'
                + '<span class="bingo-upscore-change-total' + leaderClass + '" style="color:' + teamColor + ';">'
                + formatBingoPoints(afterTeams[team], false) + "</span>"
                + "</td>"
                + "</tr>"
              );
            }
            upscorePointChanges.innerHTML = (
              '<table class="bingo-upscore-changes-table">'
              + "<colgroup>"
              + '<col class="bingo-upscore-col-team">'
              + '<col class="bingo-upscore-col-delta">'
              + '<col class="bingo-upscore-col-arrow">'
              + '<col class="bingo-upscore-col-total">'
              + "</colgroup><tbody>"
              + rows.join("")
              + "</tbody></table>"
            );
          }

          function syncUpscorePlayerUi() {
            renderUpscorePlayerOptions();
            const player = selectedUpscorePlayer();
            if (!player) {
              upscoreAutoSliderPlayerId = null;
              currentLeadThresholdPct = null;
              updateLeadMarker();
              renderUpscoreResults();
              syncUpscoreScoreboardHighlight();
              return;
            }
            const maxScore = currentUpscore.max_score;
            const floor = currentUpscore.ex_accuracy_floor;
            const currentPct = exAccuracyForScore(player.score, maxScore);
            upscoreSlider.min = String(Math.max(0, currentPct));
            upscoreSlider.max = "100";
            upscoreSlider.step = "0.01";

            const isNewPlayer = upscoreAutoSliderPlayerId !== player.player_id;
            if (isNewPlayer) {
              upscoreAutoSliderPlayerId = player.player_id;
              currentLeadThresholdPct = computeLeadThresholdPct(player, maxScore, floor);
              if (currentLeadThresholdPct !== null && currentLeadThresholdPct > currentPct) {
                upscoreSlider.value = String(currentLeadThresholdPct);
              } else {
                upscoreSlider.value = String(currentPct);
              }
            } else {
              upscoreSlider.value = String(Math.max(currentPct, Number(upscoreSlider.value || currentPct)));
            }
            updateLeadMarker();
            renderUpscoreResults();
            syncUpscoreScoreboardHighlight();
          }

          function initUpscore(data) {
            resetUpscorePanel();
            if (!data || !data.upscore_json) {
              return;
            }
            try {
              currentUpscore = JSON.parse(data.upscore_json);
            } catch (error) {
              currentUpscore = null;
              return;
            }
            upscoreBtn.hidden = false;
            upscoreAutoSliderPlayerId = null;
            selectedUpscorePlayerId = null;
            if (
              currentUpscore.default_player_id &&
              currentUpscore.players.some((p) => p.player_id === currentUpscore.default_player_id)
            ) {
              selectedUpscorePlayerId = currentUpscore.default_player_id;
            }
            syncUpscorePlayerUi();
          }

          upscoreBtn.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (!currentUpscore) return;
            const isOpen = upscorePanel.classList.contains("is-open");
            upscorePanel.classList.toggle("is-open", !isOpen);
            upscorePanel.setAttribute("aria-hidden", isOpen ? "true" : "false");
            upscoreBtn.classList.toggle("is-active", !isOpen);
            if (!isOpen) syncUpscorePlayerUi();
          });
          upscoreSearch.addEventListener("input", () => {
            renderUpscorePlayerOptions();
            syncUpscorePlayerUi();
          });
          upscoreSelect.addEventListener("change", () => {
            selectedUpscorePlayerId = upscoreSelect.value || null;
            syncUpscorePlayerUi();
          });
          upscoreSlider.addEventListener("input", renderUpscoreResults);
"""


def _build_bingo_board_interactive_html(
    *,
    cells_html: list[str],
    cols: int,
    modal_payload: dict[str, dict[str, str]],
    player_board_payload: dict[str, dict[str, dict[str, str | bool]]],
    snapshot_label: str,
    updated_ms: int | None,
) -> str:
    payload_json = json.dumps(modal_payload).replace("</", "<\\/")
    player_board_json = json.dumps(player_board_payload).replace("</", "<\\/")
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
              <div class="bingo-chart-modal-header">
                <div id="bingo-chart-modal-title" class="bingo-chart-modal-title"></div>
                <button type="button" class="bingo-chart-modal-upscore-btn" id="bingo-chart-upscore-btn" hidden>Upscore Calculator</button>
              </div>
              <div class="bingo-chart-modal-subtitle-row">
                <button type="button"
                  class="bingo-chart-modal-refresh-btn"
                  id="bingo-chart-modal-refresh-btn"
                  aria-label="Refresh scoreboard">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
                    aria-hidden="true">
                    <path d="M21 12a9 9 0 1 1-2.64-6.36"></path>
                    <polyline points="21 3 21 9 15 9"></polyline>
                  </svg>
                </button>
                <div class="bingo-chart-modal-subtitle"></div>
              </div>
              <div class="bingo-chart-modal-upscore-panel" id="bingo-chart-upscore-panel" aria-hidden="true">
                <div class="bingo-chart-modal-upscore-inner">
                  <div class="bingo-upscore-player-picker" id="bingo-upscore-player-picker">
                    <input type="search" id="bingo-upscore-search" placeholder="Search players..." autocomplete="off" />
                    <select id="bingo-upscore-player-select"></select>
                  </div>
                  <div class="bingo-upscore-player-name" id="bingo-upscore-player-name"></div>
                  <dl class="bingo-upscore-metrics">
                    <div>
                      <dt>Current Score</dt>
                      <dd id="bingo-upscore-current-score">—</dd>
                    </div>
                    <div>
                      <dt>Current Score %</dt>
                      <dd id="bingo-upscore-current-pct">—</dd>
                    </div>
                  </dl>
                  <div class="bingo-upscore-slider-label">
                    <span>Target Score %</span>
                    <span id="bingo-upscore-target-pct">—</span>
                  </div>
                  <div class="bingo-upscore-slider-wrap">
                    <div class="bingo-upscore-slider-marker" id="bingo-upscore-lead-marker" hidden></div>
                    <input type="range" class="bingo-upscore-slider" id="bingo-upscore-slider" min="0" max="100" step="0.01" />
                  </div>
                  <div class="bingo-upscore-results">
                    <dl class="bingo-upscore-required-row">
                      <div class="bingo-upscore-required-item">
                        <dt>Required Score</dt>
                        <dd id="bingo-upscore-required-score">—</dd>
                      </div>
                      <div class="bingo-upscore-required-item">
                        <dt>Placement</dt>
                        <dd id="bingo-upscore-required-placement">—</dd>
                      </div>
                    </dl>
                    <div class="bingo-upscore-changes-title">Point Changes</div>
                    <div class="bingo-upscore-changes" id="bingo-upscore-point-changes"></div>
                  </div>
                </div>
              </div>
              <div class="bingo-chart-modal-body"></div>
            </div>
          </div>
        </div>
        <div id="bingo-proof-modal" class="bingo-proof-modal-overlay" aria-hidden="true">
          <button type="button" class="bingo-proof-modal-backdrop" aria-label="Close proof image"></button>
          <div class="bingo-proof-modal-panel" role="dialog" aria-modal="true" aria-label="Score proof">
            <button type="button" class="bingo-proof-modal-close" aria-label="Close">&times;</button>
            <img class="bingo-proof-modal-image" src="" alt="Score proof screenshot" />
          </div>
        </div>
        <script>
        (function () {{
          const root = document.getElementById("bingo-board-root");
          const modalData = {payload_json};
          const playerBoardData = {player_board_json};
          let selectedPlayerId = null;
          const snapshotLabel = {snapshot_json};
          const updatedMs = {updated_ms_json};
          const modal = document.getElementById("bingo-chart-modal");
          const proofModal = document.getElementById("bingo-proof-modal");
          const titleEl = modal.querySelector(".bingo-chart-modal-title");
          const subtitleEl = modal.querySelector(".bingo-chart-modal-subtitle");
          const refreshBtn = document.getElementById("bingo-chart-modal-refresh-btn");
          const bodyEl = modal.querySelector(".bingo-chart-modal-body");
          const backdropEl = modal.querySelector(".bingo-chart-modal-backdrop");
          const closeEl = modal.querySelector(".bingo-chart-modal-close");
          const proofImageEl = proofModal.querySelector(".bingo-proof-modal-image");
          const proofBackdropEl = proofModal.querySelector(".bingo-proof-modal-backdrop");
          const proofCloseEl = proofModal.querySelector(".bingo-proof-modal-close");
          let lastFocused = null;
          let subtitleTimer = null;
          let closeTimer = null;
          let modalUpdatedMs = updatedMs;
          let currentModalRow = null;
          let currentModalCol = null;
          let modalRefreshPending = false;
          let pendingProofPath = null;
          const MODAL_ANIM_MS = 220;
          {_BINGO_UPSCORE_CALCULATOR_JS}

          function closeProofModal() {{
            proofModal.classList.remove("is-open");
            proofModal.setAttribute("aria-hidden", "true");
            proofImageEl.removeAttribute("src");
          }}

          function openProofModal(url) {{
            proofImageEl.src = url;
            proofModal.classList.add("is-open");
            proofModal.setAttribute("aria-hidden", "false");
            proofCloseEl.focus();
          }}

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
            if (modalUpdatedMs !== null) {{
              subtitleEl.textContent = "as of " + formatAgo(modalUpdatedMs);
              return;
            }}
            subtitleEl.textContent = snapshotLabel;
          }}

          function findChartRefreshButton(row, col) {{
            const selectors = [
              ".st-key-bingo_chart_refresh_" + row + "_" + col + " button",
              '[class*="st-key-bingo_chart_refresh_' + row + "_" + col + '"] button',
            ];
            try {{
              const doc = window.parent.document;
              for (const selector of selectors) {{
                const button = doc.querySelector(selector);
                if (button) {{
                  return button;
                }}
              }}
            }} catch (error) {{}}
            return null;
          }}

          function setModalRefreshPending(isPending) {{
            modalRefreshPending = isPending;
            if (!refreshBtn) {{
              return;
            }}
            refreshBtn.disabled = isPending;
            refreshBtn.classList.toggle("is-spinning", isPending);
          }}

          function applyModalRefresh(payload) {{
            if (!payload || payload.row !== currentModalRow || payload.col !== currentModalCol) {{
              setModalRefreshPending(false);
              pendingProofPath = null;
              return;
            }}
            const key = payload.row + "," + payload.col;
            const openPlayerId = openJudgementPlayerId;
            const proofPathToOpen = pendingProofPath;
            pendingProofPath = null;
            if (!modalData[key]) {{
              modalData[key] = {{}};
            }}
            modalData[key].table_html = payload.table_html || "";
            if (payload.upscore_json) {{
              modalData[key].upscore_json = payload.upscore_json;
            }}
            bodyEl.innerHTML = modalData[key].table_html;
            closeJudgementRows();
            if (openPlayerId) {{
              toggleJudgementRow(openPlayerId);
            }}
            applyModalPlayerHighlight();
            initUpscore(modalData[key]);
            if (
              selectedPlayerId &&
              currentUpscore &&
              currentUpscore.players.some((p) => p.player_id === selectedPlayerId)
            ) {{
              selectedUpscorePlayerId = selectedPlayerId;
              syncUpscorePlayerUi();
            }}
            if (payload.updated_ms !== undefined && payload.updated_ms !== null && updatedMs !== null) {{
              modalUpdatedMs = Number(payload.updated_ms);
            }}
            updateSubtitle();
            setModalRefreshPending(false);
            if (proofPathToOpen) {{
              const proofBtn = Array.from(
                bodyEl.querySelectorAll(".bingo-chart-modal-proof-btn")
              ).find((btn) => btn.dataset.proofPath === proofPathToOpen);
              if (proofBtn && proofBtn.dataset.proofUrl) {{
                openProofModal(proofBtn.dataset.proofUrl);
              }}
            }}
          }}

          function requestModalRefresh() {{
            if (
              modalRefreshPending ||
              currentModalRow === null ||
              currentModalCol === null
            ) {{
              return;
            }}
            const button = findChartRefreshButton(currentModalRow, currentModalCol);
            if (!button) {{
              return;
            }}
            setModalRefreshPending(true);
            button.click();
            window.setTimeout(() => {{
              if (modalRefreshPending) {{
                setModalRefreshPending(false);
              }}
            }}, 10000);
          }}

          window.addEventListener("message", (event) => {{
            if (!event.data || event.data.type !== "bingo-chart-leaderboard-refresh") {{
              return;
            }}
            applyModalRefresh(event.data.payload);
          }});

          if (refreshBtn) {{
            refreshBtn.addEventListener("click", (event) => {{
              event.preventDefault();
              event.stopPropagation();
              requestModalRefresh();
            }});
          }}

          function syncBoardModes() {{
            let detailed = false;
            let hideLines = false;
            let hideColors = false;
            let playerBoard = false;
            try {{
              const parentDoc = window.parent.document;
              detailed = !!parentDoc.querySelector(".bingo-detailed-toggle:checked");
              hideColors = !!parentDoc.querySelector(".bingo-colors-toggle:checked");
              hideLines = !!parentDoc.querySelector(".bingo-lines-toggle:checked");
              const playerToggle = parentDoc.querySelector(".bingo-player-board-toggle");
              playerBoard = !!(
                playerToggle &&
                !playerToggle.disabled &&
                playerToggle.checked
              );
              if (detailed && playerBoard) {{
                playerBoard = false;
              }}
              syncSelectedPlayerFromParent(parentDoc);
            }} catch (error) {{}}
            root.classList.toggle("is-detailed", detailed);
            root.classList.toggle("is-player-board", playerBoard);
            root.classList.toggle("hide-colors", hideColors);
            root.classList.toggle("hide-lines", hideLines || hideColors);
          }}

          function applySelectedPlayer(playerId) {{
            selectedPlayerId = playerId || null;
            root.querySelectorAll(".bingo-cell-link").forEach((cell) => {{
              const playerView = cell.querySelector(".bingo-cell-player-view");
              const body = cell.querySelector(".bingo-cell-body");
              if (!playerView || !body) {{
                return;
              }}
              const key = cell.dataset.row + "," + cell.dataset.col;
              const data =
                playerId && playerBoardData[playerId]
                  ? playerBoardData[playerId][key]
                  : null;
              if (!data) {{
                playerView.className = "bingo-cell-view bingo-cell-player-view";
                playerView.innerHTML = "";
                body.classList.remove("bingo-cell-body--player-not-played");
                return;
              }}
              const notPlayed = !!data.not_played;
              playerView.className =
                "bingo-cell-view bingo-cell-player-view" +
                (notPlayed ? " bingo-cell-player-view--not-played" : "");
              let inner = data.mid_html || "";
              if (data.crit_html) {{
                inner += data.crit_html;
              }}
              if (data.footer_html) {{
                inner += '<div class="bingo-cell-bot">' + data.footer_html + "</div>";
              }}
              playerView.innerHTML = inner;
              body.classList.toggle("bingo-cell-body--player-not-played", notPlayed);
            }});
          }}

          function syncSelectedPlayerFromParent(parentDoc) {{
            let playerId = "";
            try {{
              const marker = parentDoc.querySelector(".bingo-view-player-id-marker");
              playerId = marker?.dataset.playerId || "";
            }} catch (error) {{
              playerId = "";
            }}
            if (playerId !== selectedPlayerId) {{
              applySelectedPlayer(playerId);
            }}
          }}

          let openJudgementPlayerId = null;

          function closeJudgementRows() {{
            bodyEl.querySelectorAll(".bingo-chart-modal-detail-row.is-open").forEach((row) => {{
              row.classList.remove("is-open");
            }});
            bodyEl.querySelectorAll(".bingo-chart-modal-data-row.is-expanded").forEach((row) => {{
              row.classList.remove("is-expanded");
              row.setAttribute("aria-expanded", "false");
            }});
            openJudgementPlayerId = null;
          }}

          function toggleJudgementRow(playerId) {{
            if (!playerId) {{
              return;
            }}
            if (openJudgementPlayerId === playerId) {{
              closeJudgementRows();
              return;
            }}
            closeJudgementRows();
            const dataRow = bodyEl.querySelector(
              '.bingo-chart-modal-data-row[data-player-id="' + playerId + '"]'
            );
            const detailRow = bodyEl.querySelector(
              '.bingo-chart-modal-detail-row[data-player-id="' + playerId + '"]'
            );
            if (!dataRow || !detailRow) {{
              return;
            }}
            dataRow.classList.add("is-expanded");
            dataRow.setAttribute("aria-expanded", "true");
            detailRow.classList.add("is-open");
            openJudgementPlayerId = playerId;
          }}

          function applyModalPlayerHighlight() {{
            bodyEl
              .querySelectorAll("tr.bingo-chart-modal-data-row.bingo-chart-modal-row--highlighted")
              .forEach((row) => row.classList.remove("bingo-chart-modal-row--highlighted"));
            if (!selectedPlayerId) {{
              return;
            }}
            const row = bodyEl.querySelector(
              '.bingo-chart-modal-data-row[data-player-id="' + selectedPlayerId + '"]'
            );
            if (row) {{
              row.classList.add("bingo-chart-modal-row--highlighted");
            }}
          }}

          function closeHelpTips() {{
            bodyEl.querySelectorAll(".bingo-chart-modal-help-wrap.is-open").forEach((wrap) => {{
              wrap.classList.remove("is-open");
            }});
          }}

          function finishCloseModal() {{
            modal.classList.remove("is-closing");
            closeTimer = null;
            closeHelpTips();
            if (subtitleTimer !== null) {{
              clearInterval(subtitleTimer);
              subtitleTimer = null;
            }}
            bodyEl.innerHTML = "";
            resetUpscorePanel();
            closeJudgementRows();
            currentModalRow = null;
            currentModalCol = null;
            pendingProofPath = null;
            setModalRefreshPending(false);
            if (lastFocused && typeof lastFocused.focus === "function") {{
              lastFocused.focus();
            }}
          }}

          function closeModal() {{
            closeProofModal();
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
            currentModalRow = Number(row);
            currentModalCol = Number(col);
            modalUpdatedMs = updatedMs;
            setModalRefreshPending(false);
            titleEl.innerHTML = data.title_html || data.title || "";
            updateSubtitle();
            if (modalUpdatedMs !== null && subtitleTimer === null) {{
              subtitleTimer = setInterval(updateSubtitle, 1000);
            }}
            bodyEl.innerHTML = data.table_html;
            closeJudgementRows();
            applyModalPlayerHighlight();
            initUpscore(data);
            if (
              selectedPlayerId &&
              currentUpscore &&
              currentUpscore.players.some((p) => p.player_id === selectedPlayerId)
            ) {{
              selectedUpscorePlayerId = selectedPlayerId;
              syncUpscorePlayerUi();
            }}
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
          bodyEl.addEventListener("click", (event) => {{
            const helpBtn = event.target.closest(".bingo-chart-modal-help-btn");
            if (helpBtn) {{
              event.preventDefault();
              event.stopPropagation();
              const wrap = helpBtn.closest(".bingo-chart-modal-help-wrap");
              if (!wrap) {{
                return;
              }}
              const isOpen = wrap.classList.contains("is-open");
              closeHelpTips();
              if (!isOpen) {{
                wrap.classList.add("is-open");
              }}
              return;
            }}
            closeHelpTips();
            const proofBtn = event.target.closest(".bingo-chart-modal-proof-btn");
            if (proofBtn) {{
              event.preventDefault();
              event.stopPropagation();
              const proofUrl = proofBtn.dataset.proofUrl;
              if (proofUrl) {{
                openProofModal(proofUrl);
                return;
              }}
              const proofPath = proofBtn.dataset.proofPath;
              if (proofPath) {{
                pendingProofPath = proofPath;
                requestModalRefresh();
              }}
              return;
            }}
            const dataRow = event.target.closest(".bingo-chart-modal-data-row.bingo-chart-modal-row--expandable");
            if (dataRow) {{
              event.preventDefault();
              event.stopPropagation();
              toggleJudgementRow(dataRow.dataset.playerId || "");
              return;
            }}
          }});
          bodyEl.addEventListener("keydown", (event) => {{
            const dataRow = event.target.closest(".bingo-chart-modal-data-row.bingo-chart-modal-row--expandable");
            if (!dataRow) {{
              return;
            }}
            if (event.key !== "Enter" && event.key !== " ") {{
              return;
            }}
            event.preventDefault();
            toggleJudgementRow(dataRow.dataset.playerId || "");
          }});
          proofBackdropEl.addEventListener("click", closeProofModal);
          proofCloseEl.addEventListener("click", closeProofModal);
          document.addEventListener("keydown", (event) => {{
            if (event.key === "Escape" && proofModal.classList.contains("is-open")) {{
              closeProofModal();
              return;
            }}
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
    player_board_payload: dict[str, dict[str, dict[str, str | bool]]],
    snapshot_label: str,
    updated_ms: int | None,
    has_player_data: bool = True,
) -> None:
    inner_html = _build_bingo_board_interactive_html(
        cells_html=cells_html,
        cols=cols,
        modal_payload=modal_payload,
        player_board_payload=player_board_payload,
        snapshot_label=snapshot_label,
        updated_ms=updated_ms,
    )
    root_classes = "bingo-board-root"
    if has_player_data:
        root_classes += " has-player-data"
    component_html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        + _bingo_board_component_css(cols=cols, rows=rows)
        + "</style></head><body>"
        + f'<div class="{root_classes}" id="bingo-board-root">{inner_html}</div>'
        + "</body></html>"
    )
    components.html(
        component_html,
        height=_bingo_board_component_height(rows, cols),
        scrolling=False,
    )


def _bingo_chart_proof_icon_html(
    entry: BingoChartLeaderboardEntry,
    *,
    proof_url: str | None = None,
) -> str:
    if entry.score <= 0:
        return ""

    if entry.source == SCORE_SOURCE_IN_GAME:
        return (
            '<span class="bingo-chart-modal-proof-badge bingo-chart-modal-proof-badge--ingame" '
            'title="In-game score" aria-label="In-game score">'
            "&#10003;"
            "</span>"
        )

    if entry.source == SCORE_SOURCE_SUBMISSION:
        if entry.proof_path:
            path_attr = html.escape(str(entry.proof_path), quote=True)
            url = str(proof_url or "").strip()
            url_attr = (
                f' data-proof-url="{html.escape(url, quote=True)}"' if url else ""
            )
            return (
                '<button type="button" class="bingo-chart-modal-proof-btn" '
                f'data-proof-path="{path_attr}"{url_attr} '
                'title="View submitted proof" aria-label="View submitted proof">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
                'aria-hidden="true">'
                '<rect x="3" y="3" width="18" height="18" rx="2"></rect>'
                '<circle cx="8.5" cy="8.5" r="1.5"></circle>'
                '<path d="M21 15l-5-5L5 21"></path>'
                "</svg></button>"
            )
        return (
            '<span class="bingo-chart-modal-proof-badge bingo-chart-modal-proof-badge--missing" '
            'title="No proof submitted" aria-label="No proof submitted">'
            "?"
            "</span>"
        )

    return ""


def _bingo_chart_points_header_html() -> str:
    tip = html.escape("Score Points (+ Placement Points)")
    return (
        '<th class="bingo-chart-modal-points">'
        '<span class="bingo-chart-modal-points-head">'
        "<span>Points</span>"
        '<span class="bingo-chart-modal-help-wrap">'
        '<button type="button" class="bingo-chart-modal-help-btn" '
        f'aria-label="Points format: {tip}">?</button>'
        f'<span class="bingo-chart-modal-help-tip" role="tooltip">{tip}</span>'
        "</span>"
        "</span>"
        "</th>"
    )


def _format_chart_ex_accuracy(
    *,
    song: str,
    difficulty: str,
    score: int,
) -> str:
    if int(score) <= 0:
        return "—"
    max_score = bingo_chart_max_score(song, difficulty)
    if max_score is None or max_score <= 0:
        return "—"
    pct = ex_accuracy_percent(int(score), int(max_score))
    return f"{pct:.2f}%"


def _format_chart_points_cell(breakdown: ChartPlayerPointBreakdown) -> str:
    accuracy = format_bingo_points(breakdown.accuracy_points)
    bonus = breakdown.placement_bonus
    if bonus > 0:
        return (
            f"{accuracy} "
            f'<span class="bingo-chart-modal-points-bonus">'
            f"(+{format_bingo_points(bonus)})"
            f"</span>"
        )
    return accuracy


_BINGO_JUDGEMENT_STAT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("critical", "Critical", "#ffffff"),
    ("perfect", "Perfect", "#ff5c33"),
    ("great", "Great", "#00cc44"),
    ("good", "Good", "#3399ff"),
    ("okay", "Okay", "#f5d547"),
    ("barely", "Barely", "#ff4757"),
    ("miss", "Miss", "#8b1a1a"),
)


def _render_bingo_judgement_stats_html(entry: BingoChartLeaderboardEntry) -> str:
    stats: list[str] = []
    for field, label, color in _BINGO_JUDGEMENT_STAT_SPECS:
        value = getattr(entry, field, None)
        if value is None:
            continue
        stats.append(
            '<div class="bingo-judgement-stat">'
            f'<div class="bingo-judgement-stat-label" style="color:{color};">{html.escape(label)}</div>'
            f'<div class="bingo-judgement-stat-value" style="color:{color};">'
            f"{html.escape(f'{int(value):,}')}</div>"
            "</div>"
        )
    parts: list[str] = []
    if stats:
        parts.append(f'<div class="bingo-judgement-stats">{"".join(stats)}</div>')
    else:
        parts.append(
            '<div class="bingo-judgement-empty">'
            "No judgement data recorded for this score."
            "</div>"
        )
    if entry.created_at is not None and int(entry.score) > 0:
        submitted_ago = _format_bingo_time_ago(entry.created_at)
        parts.append(
            f'<div class="bingo-judgement-submitted">'
            f"Submitted {html.escape(submitted_ago)}"
            "</div>"
        )
    return "".join(parts)


def _bingo_chart_modal_column_count(*, show_points: bool) -> int:
    return 6 if show_points else 4


def _render_bingo_chart_leaderboard_table_html(
    entries: list[BingoChartLeaderboardEntry],
    *,
    song: str | None = None,
    difficulty: str | None = None,
    highlight_player_id: str | None = None,
    proof_urls: dict[str, str] | None = None,
) -> str:
    if not entries:
        return (
            '<div class="bingo-chart-modal-empty">'
            "No players are on the bingo roster yet."
            "</div>"
        )

    show_points = (
        bingo_scoring_version() == "v2"
        and song is not None
        and difficulty is not None
    )
    breakdowns: dict[str, ChartPlayerPointBreakdown] = {}
    if show_points:
        players = {
            entry.player_id: (entry.team, int(entry.score)) for entry in entries
        }
        breakdowns = compute_chart_player_point_breakdowns(
            song=song,
            difficulty=difficulty,
            players=players,
        )
        entries = sorted(
            entries,
            key=lambda entry: (
                -int(entry.score),
                entry.display_name.casefold(),
            ),
        )

    colspan = _bingo_chart_modal_column_count(show_points=show_points)
    url_by_path = proof_urls or {}
    rows: list[str] = []
    rank = 0
    for index, entry in enumerate(entries):
        if show_points:
            rank = breakdowns[entry.player_id].rank
        elif index == 0 or entry.score != entries[index - 1].score:
            rank = index + 1
        team_color = TEAM_TEXT_COLORS.get(entry.team, "#eaeaea")
        player = html.escape(entry.display_name)
        score = html.escape(format_leader_score(entry.score))
        proof_path = str(entry.proof_path or "").strip()
        proof_icon = _bingo_chart_proof_icon_html(
            entry,
            proof_url=url_by_path.get(proof_path) if proof_path else None,
        )
        row_classes = ["bingo-chart-modal-data-row"]
        if highlight_player_id is not None and entry.player_id == highlight_player_id:
            row_classes.append("bingo-chart-modal-row--highlighted")
        expandable = int(entry.score) > 0
        if expandable:
            row_classes.append("bingo-chart-modal-row--expandable")
        row_class = html.escape(" ".join(row_classes))
        player_id_attr = html.escape(entry.player_id, quote=True)
        points_cell = ""
        accuracy_cell = ""
        if show_points:
            accuracy_cell = (
                f'<td class="bingo-chart-modal-accuracy">'
                f"{html.escape(_format_chart_ex_accuracy(song=song, difficulty=difficulty, score=int(entry.score)))}"
                f"</td>"
            )
            points_cell = (
                f'<td class="bingo-chart-modal-points">'
                f"{_format_chart_points_cell(breakdowns[entry.player_id])}"
                f"</td>"
            )
        row_attrs = (
            f' class="{row_class}" data-player-id="{player_id_attr}"'
        )
        if expandable:
            row_attrs += ' role="button" tabindex="0" aria-expanded="false"'
        rows.append(
            f"<tr{row_attrs}>"
            f'<td class="bingo-chart-modal-rank">{rank}</td>'
            f'<td class="bingo-chart-modal-player" style="color:{team_color};">'
            f"{player}</td>"
            f'<td class="bingo-chart-modal-score">{score}</td>'
            f"{accuracy_cell}"
            f"{points_cell}"
            f'<td class="bingo-chart-modal-proof-col">{proof_icon}</td>'
            "</tr>"
        )
        if expandable:
            detail_html = _render_bingo_judgement_stats_html(entry)
            rows.append(
                f'<tr class="bingo-chart-modal-detail-row" data-player-id="{player_id_attr}">'
                f'<td colspan="{colspan}">'
                f'<div class="bingo-chart-modal-detail-panel">{detail_html}</div>'
                "</td>"
                "</tr>"
            )
    accuracy_header = (
        '<th class="bingo-chart-modal-accuracy">Max Score %</th>' if show_points else ""
    )
    points_header = _bingo_chart_points_header_html() if show_points else ""
    return (
        '<div class="bingo-chart-modal-table-wrap">'
        '<table class="bingo-chart-modal-table">'
        "<thead><tr>"
        '<th class="bingo-chart-modal-rank">#</th>'
        '<th class="bingo-chart-modal-player">Player</th>'
        '<th class="bingo-chart-modal-score">Score</th>'
        f"{accuracy_header}"
        f"{points_header}"
        '<th class="bingo-chart-modal-proof-col" aria-label="Proof"></th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


@st.fragment
def _render_bingo_player_controls_fragment(
    *,
    settings: BingoSettings,
    charts: list,
    completed_days: int,
) -> None:
    """Player search/select — reruns alone without remounting the board iframe."""
    day_count = max(1, int(settings.day_count or 1))
    view_day = _resolve_bingo_view_day(completed_days, day_count=day_count)
    end_time = (
        bingo_day_end(settings.start_time, view_day)
        if view_day is not None and settings.start_time is not None
        else None
    )
    try:
        leaderboard_by_chart = load_all_bingo_chart_player_leaderboards(
            start_time=settings.start_time,
            end_time=end_time,
        )
    except Exception:
        leaderboard_by_chart = {}

    standings_data = load_bingo_chart_standings_data(
        start_time=settings.start_time,
        end_time=end_time,
    )
    totals = {key: values[0] for key, values in standings_data.items()}
    player_bests = {key: values[1] for key, values in standings_data.items()}
    leaders_by_chart: dict[tuple[str, str], str | None] = {}
    for chart in charts:
        standing = build_cell_standing(chart, totals, player_bests)
        leaders_by_chart[(chart.song, chart.difficulty)] = standing.leader

    teams = _cached_bingo_teams()
    width = max(1, int(settings.board_width))
    board_charts = bingo_charts_on_board(charts, width)
    view_player = _render_bingo_player_view_controls(
        teams,
        board_charts=board_charts,
        leaderboard_by_chart=leaderboard_by_chart,
        leaders_by_chart=leaders_by_chart,
    )
    if view_player is None:
        view_player = _resolve_bingo_view_player(teams)
        if view_player is not None:
            _inject_scoreboard_player_row_highlight(view_player.team)


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

    if view_day is not None:
        _render_bingo_historical_banner(
            view_day,
            day_count=day_count,
            show_live_button=show_live,
        )

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
    leaders_by_chart: dict[tuple[str, str], str | None] = {}
    for chart in charts:
        standing = build_cell_standing(chart, totals, player_bests)
        standings_by_coord[(chart.row, chart.column)] = standing
        leaders_by_coord[(chart.row, chart.column)] = standing.leader
        leaders_by_chart[(chart.song, chart.difficulty)] = standing.leader
    line_segments = _bingo_line_segments_by_cell(
        leaders_by_coord, rows=rows, cols=cols
    )

    teams = _cached_bingo_teams()
    board_charts = bingo_charts_on_board(charts, width)

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
                    player_board_ready=True,
                )
            )

    player_board_payload = _build_bingo_player_board_payload(
        charts=board_charts,
        teams=teams,
        leaderboard_by_chart=leaderboard_by_chart,
    )
    board_width = _bingo_board_width_expr(rows=rows)
    modal_payload = _build_bingo_chart_modal_payload(
        charts,
        leaderboard_by_chart,
        roster=teams,
        highlight_player_id=None,
    )
    updated_ms = (
        int(float(st.session_state.bingo_last_updated) * 1000)
        if view_day is None and _bingo_game_is_active(settings=settings)
        else None
    )
    with st.container(key="bingo_board_viewport"):
        _inject_bingo_board_layout_css(board_width)
        _render_bingo_board_toolbar(
            show_refresh=view_day is None and _bingo_game_is_active(settings=settings),
        )
        _render_bingo_board_component(
            cells_html=cells_html,
            cols=cols,
            rows=rows,
            modal_payload=modal_payload,
            player_board_payload=player_board_payload,
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
    _inject_scoreboard_day_highlight(highlight_day, day_count=day_count)


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
        require_proof=False,
        proof_bytes=pending.get("proof_bytes"),
        proof_filename=pending.get("proof_filename"),
    )
    st.session_state.bingo_submission_in_progress = False
    if ok:
        st.session_state.bingo_submit_success = message
        _touch_bingo_live_updated()
        _cached_bingo_charts.clear()
        _cached_bingo_teams.clear()
        clear_bingo_query_cache()
    else:
        st.session_state.bingo_submit_error = message


def render_bingo_board() -> None:
    if not supabase_configured():
        st.warning("Supabase is not configured, so the Bingo board cannot load.")
        return

    st.markdown(
        """
        <style>
        /* Spinner defaults to content-width (left-aligned); stretch + center the row */
        [data-testid="stSpinner"],
        [data-testid="stSpinner"] > div,
        .stSpinner,
        .stSpinner > div {
            width: 100% !important;
            max-width: 100% !important;
        }
        [data-testid="stSpinner"] div,
        .stSpinner div {
            justify-content: center !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _maybe_rerun_bingo_app()

    live_view = st.session_state.get("bingo_view_day") is None

    saving = bool(st.session_state.get("bingo_submission_in_progress"))
    spinner = (
        st.spinner("Saving score…", width="stretch") if saving else nullcontext()
    )
    with spinner:
        if saving:
            _commit_pending_bingo_submission()

        try:
            with st.spinner("Loading Bingo…", width="stretch"):
                settings = load_bingo_settings()
                charts = _cached_bingo_charts()
                teams = _cached_bingo_teams()
        except Exception as exc:
            st.error(f"Failed to load Bingo data: {exc}")
            return

        if settings is None:
            st.warning("Bingo settings are not available yet.")
            return

        game_is_active = _bingo_game_is_active(settings=settings)
        if live_view and game_is_active and "bingo_last_updated" not in st.session_state:
            _touch_bingo_live_updated()

        if live_view and _bingo_supports_live_refresh(settings=settings):
            _render_bingo_auto_refresh_trigger()

        # Paint the header before the heavy scoreboard/board queries so the page
        # doesn't sit blank while Postgres is busy.
        _render_bingo_header(
            settings,
            live_view=live_view and _bingo_supports_live_refresh(settings=settings),
            updated_ms=(
                int(float(st.session_state.bingo_last_updated) * 1000)
                if live_view and game_is_active
                else None
            ),
            final_standings=None,
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

        scoreboard: BingoScoreboard | None = None
        final_standings: BingoFinalStandings | None = None
        with st.spinner("Loading Bingo Board…", width="stretch"):
            if charts and settings.start_time is not None and settings.day_count is not None:
                try:
                    scoreboard = compute_bingo_scoreboard(
                        settings=settings,
                        charts=charts,
                    )
                except Exception as exc:
                    st.error(f"Failed to load Bingo scoreboard: {exc}")
                    scoreboard = None
                completed_for_winner = completed_bingo_days(
                    start_time=settings.start_time,
                    day_count=int(settings.day_count),
                )
                if (
                    scoreboard is not None
                    and completed_for_winner >= int(settings.day_count)
                ):
                    final_standings = compute_bingo_final_standings(
                        scoreboard=scoreboard,
                    )

            if final_standings is not None:
                # Game is over — replace the early header with the podium version.
                _render_bingo_header(
                    settings,
                    live_view=live_view and _bingo_supports_live_refresh(settings=settings),
                    updated_ms=(
                        int(float(st.session_state.bingo_last_updated) * 1000)
                        if live_view and game_is_active
                        else None
                    ),
                    final_standings=final_standings,
                )

            _render_bingo_player_controls_fragment(
                settings=settings,
                charts=charts,
                completed_days=completed_days,
            )
            _render_bingo_board_fragment(
                settings=settings,
                charts=charts,
                completed_days=completed_days,
            )
            _render_bingo_chart_refresh_bridge(
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
        if game_is_live or BINGO_MANUAL_SUBMISSION_FORCE_VISIBLE:
            _render_bingo_manual_submission(
                charts=charts,
                teams=teams,
                settings=settings,
            )
        _render_bingo_teams(teams)
        if game_is_live:
            view_player = _resolve_bingo_view_player(teams)
            highlight_player_id = (
                view_player.player_id if view_player is not None else None
            )
            try:
                leaderboard_by_chart = load_all_bingo_chart_player_leaderboards(
                    start_time=settings.start_time,
                )
            except Exception as exc:
                st.error(f"Failed to load board leaderboards: {exc}")
                leaderboard_by_chart = None
            if leaderboard_by_chart is not None:
                st.markdown(
                    """
                    <style>
                    .st-key-bingo_board_stat_buttons {
                        width: min(100%, 520px);
                        max-width: 100%;
                        margin: 0.35rem auto 0.5rem;
                    }
                    .st-key-bingo_board_stat_buttons [data-testid="stHorizontalBlock"] {
                        gap: 0.75rem;
                        align-items: center;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                with st.container(key="bingo_board_stat_buttons"):
                    completions_col, points_col = st.columns(2)
                    with completions_col:
                        _render_bingo_chart_completions(
                            charts=charts,
                            teams=teams,
                            settings=settings,
                            highlight_player_id=highlight_player_id,
                            leaderboard_by_chart=leaderboard_by_chart,
                        )
                    with points_col:
                        _render_bingo_point_counts(
                            charts=charts,
                            teams=teams,
                            settings=settings,
                            highlight_player_id=highlight_player_id,
                            leaderboard_by_chart=leaderboard_by_chart,
                        )
