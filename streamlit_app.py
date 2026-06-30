"""Unbeatable EX Rating — web UI (Streamlit)."""

import contextlib
import hashlib
import importlib
import json

from datetime import datetime, timezone

import streamlit as st

from rating import build_ratings, get_rating_boards
from rating import constants as constants_module
from rating.models import ChartRating

importlib.reload(constants_module)

from rating import board as board_module
from rating import chart_levels as chart_levels_module
from rating import data as data_module
from rating import formatting as formatting_module
from rating import imported_players as imported_players_module
from rating import ex_leaderboard_db as ex_leaderboard_db_module
from rating import full_ex_submissions as full_ex_submissions_module
from rating import public_leaderboard as public_leaderboard_module
from rating import supabase_leaderboard as supabase_leaderboard_module
from rating.supabase_config import supabase_configured

importlib.reload(data_module)
importlib.reload(formatting_module)
importlib.reload(board_module)
importlib.reload(chart_levels_module)
importlib.reload(imported_players_module)
importlib.reload(ex_leaderboard_db_module)
importlib.reload(public_leaderboard_module)
importlib.reload(full_ex_submissions_module)
importlib.reload(supabase_leaderboard_module)

COMPLETION_BONUS = constants_module.COMPLETION_BONUS
DEFAULT_MAX_SCORES_PATH = constants_module.DEFAULT_MAX_SCORES_PATH
EX_RATING_BASELINE_PATH = constants_module.EX_RATING_BASELINE_PATH
EX_RATING_LEADERBOARD_DB_PATH = constants_module.EX_RATING_LEADERBOARD_DB_PATH
FULL_EX_RATING_LEADERBOARD_PATH = constants_module.FULL_EX_RATING_LEADERBOARD_PATH
TOP_N = constants_module.TOP_N
format_potential_gain_display = formatting_module.format_potential_gain_display
format_rating_display = formatting_module.format_rating_display
format_song_display_name = formatting_module.format_song_display_name
potential_gains_from_perfect = board_module.potential_gains_from_perfect
competition_ranks_for_values = board_module.competition_ranks_for_values
format_rating_board_csv = board_module.format_rating_board_csv
format_ex_rating_board_csv = board_module.format_ex_rating_board_csv
player_ex_rating_with_completion = board_module.player_ex_rating_with_completion
load_ex_leaderboard = public_leaderboard_module.load_ex_leaderboard
load_ex_leaderboard_with_warning = public_leaderboard_module.load_ex_leaderboard_with_warning
leaderboard_available = public_leaderboard_module.leaderboard_available
SUPABASE_LOAD_ERROR_MESSAGE = public_leaderboard_module.SUPABASE_LOAD_ERROR_MESSAGE
validate_full_ex_rating_submission = full_ex_submissions_module.validate_full_ex_rating_submission
submit_full_ex_rating_update = full_ex_submissions_module.submit_full_ex_rating_update
load_players_with_scores_from_supabase = supabase_leaderboard_module.load_players_with_scores_from_supabase
load_player_ratings_from_supabase = supabase_leaderboard_module.load_player_ratings_from_supabase

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y")


def _local_timezone():
    return datetime.now().astimezone().tzinfo


def parse_last_updated(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone()
        if dt.hour or dt.minute or dt.second or dt.microsecond:
            return dt.replace(tzinfo=timezone.utc).astimezone()
        return dt.replace(tzinfo=_local_timezone())
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_local_timezone())
        except ValueError:
            continue
    return None


def format_last_updated(value: object, *, include_time: bool = False) -> str:
    dt = parse_last_updated(value)
    if dt is None:
        text = str(value).strip() if value is not None else ""
        return text if text else "—"
    if include_time:
        return dt.strftime("%B %d, %Y %I:%M %p")
    return dt.strftime("%B %d, %Y")


st.set_page_config(
    page_title="Unbeatable EX Rating",
    page_icon="⭐",
    layout="wide",
)

TABLE_ROW_HEIGHT = 35
TABLE_HEIGHT = (TOP_N + 1) * TABLE_ROW_HEIGHT
LEADERBOARD_VISIBLE_ROWS = 15.5
LEADERBOARD_TABLE_HEIGHT = int((LEADERBOARD_VISIBLE_ROWS + 1) * TABLE_ROW_HEIGHT)
SIDE_BY_SIDE_MIN_VIEWPORT_PX = 1900
LEADERBOARD_SIDE_BY_SIDE_MIN_PX = 1000
# Max width for the submission panel when shown beside the leaderboard.
SUBMIT_EX_RATING_PANEL_MAX_WIDTH_PX = 540
# Last Updated column width (fits "June 26, 2026 5:00 PM").
FULL_EX_LEADERBOARD_LAST_UPDATED_WIDTH_PX = 160
# Each board width at the side-by-side breakpoint (~1rem page inset per side, 1rem gap).
BOARD_MAX_WIDTH_PX = (SIDE_BY_SIDE_MIN_VIEWPORT_PX - 64 - 16) // 2
# Upload, search, picker, and radio in the board viewer (~240px auto × 1.5).
BOARD_VIEWER_CONTROL_WIDTH_PX = 360

st.markdown(
    f"""
    <style>
    [data-testid="stMainBlockContainer"] {{
        padding-top: 2rem !important;
    }}
    [data-testid="stMarkdownContainer"]:has(.page-header) {{
        overflow: visible !important;
    }}
    .page-header > p {{
        margin-top: -0.55rem !important;
    }}
    .st-key-rating-boards-layout[data-testid="stHorizontalBlock"],
    .st-key-rating-boards-layout > [data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-direction: row !important;
        align-items: flex-start !important;
        gap: 1rem;
        width: 100% !important;
    }}
    .st-key-rating-boards-layout .st-key-ex-rating-board-column,
    .st-key-rating-boards-layout .st-key-ex-rating-board,
    .st-key-rating-boards-layout .st-key-std-rating-board {{
        flex: 1 1 0 !important;
        min-width: 0 !important;
        width: 100% !important;
        max-width: {BOARD_MAX_WIDTH_PX}px !important;
    }}
    .st-key-rating-boards-layout [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100%;
    }}
    .st-key-board-viewer-section {{
        width: fit-content !important;
        max-width: min(100%, {BOARD_MAX_WIDTH_PX}px) !important;
        align-self: flex-start !important;
    }}
    .st-key-board-viewer-section [data-testid="stVerticalBlock"],
    .st-key-board-viewer-section [data-testid="stVerticalBlockBorderWrapper"] {{
        width: fit-content !important;
        max-width: min(100%, {BOARD_MAX_WIDTH_PX}px) !important;
        align-self: flex-start !important;
    }}
    .st-key-board-viewer-section [data-testid="stTextInput"],
    .st-key-board-viewer-section [data-testid="stTextInput"] > div,
    .st-key-board-viewer-section [data-testid="stTextInput"] input,
    .st-key-board-viewer-section [data-testid="stSelectbox"],
    .st-key-board-viewer-section [data-testid="stSelectbox"] > div,
    .st-key-board-viewer-section [data-testid="stRadio"] {{
        width: {BOARD_VIEWER_CONTROL_WIDTH_PX}px !important;
        max-width: min(100%, {BOARD_MAX_WIDTH_PX}px) !important;
        box-sizing: border-box !important;
    }}
    .st-key-board-viewer-section [data-testid="stFileUploader"] {{
        width: max-content !important;
        min-width: {BOARD_VIEWER_CONTROL_WIDTH_PX}px !important;
        max-width: min(100%, {BOARD_MAX_WIDTH_PX}px) !important;
        box-sizing: border-box !important;
    }}
    .st-key-board-viewer-section [data-testid="stFileUploader"] > section {{
        width: auto !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }}
    /* Streamlit stacks the Upload button and size hint below 23rem; keep them inline. */
    .st-key-board-viewer-section [data-testid="stFileUploaderDropzone"] {{
        flex-direction: row !important;
        align-items: flex-start !important;
        height: auto !important;
    }}
    .st-key-board-viewer-section [data-testid="stFileUploaderDropzoneInstructions"] {{
        align-self: center !important;
    }}
    .st-key-board-viewer-section [data-testid="stAlert"],
    .st-key-board-viewer-section [data-testid="stNotification"] {{
        width: auto !important;
        max-width: min(100%, {BOARD_MAX_WIDTH_PX}px) !important;
        box-sizing: border-box !important;
    }}
    .st-key-ex-rating-board-column {{
        width: fit-content !important;
        max-width: min(100%, {BOARD_MAX_WIDTH_PX}px) !important;
        align-self: flex-start !important;
    }}
    .st-key-ex-rating-board-column [data-testid="stVerticalBlock"],
    .st-key-ex-rating-board-column [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    .st-key-ex-rating-board-column [data-testid="stAlert"],
    .st-key-ex-rating-board-column [data-testid="stNotification"] {{
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }}
    .st-key-ex-rating-board-column .st-key-ex-rating-board {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-outer {{
        width: fit-content !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-layout [data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: flex-start !important;
        gap: 1rem;
        width: fit-content !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-layout .st-key-full-ex-leaderboard-content {{
        flex: 0 0 auto !important;
        width: auto !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-layout .st-key-full-ex-submit-panel {{
        flex: 0 0 auto !important;
        width: {SUBMIT_EX_RATING_PANEL_MAX_WIDTH_PX}px !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-submit-panel [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-full-ex-submit-panel [data-testid="stTextInput"],
    .st-key-full-ex-submit-panel [data-testid="stFileUploader"],
    .st-key-full-ex-submit-panel [data-testid="stForm"],
    .st-key-full-ex-submit-panel [data-testid="stSelectbox"] {{
        max-width: 100% !important;
    }}
    .st-key-full-ex-submit-panel [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100% !important;
        box-sizing: border-box !important;
    }}
    .st-key-full-ex-submit-panel [data-testid="stMarkdownContainer"]:has(.submission-ex-rating),
    .st-key-full-ex-submit-panel [data-testid="stMarkdownContainer"]:has(.submission-selected-player),
    .st-key-full-ex-submit-panel [data-testid="stMarkdownContainer"]:has(.submission-rating-divider) {{
        margin: 0 !important;
        padding: 0.35rem 0 !important;
    }}
    .st-key-full-ex-submit-panel .submission-ex-rating,
    .st-key-full-ex-submit-panel .submission-selected-player {{
        margin: 0;
        padding: 0;
        color: rgba(250, 250, 250, 0.6);
    }}
    .st-key-full-ex-submit-panel .submission-ex-rating-value,
    .st-key-full-ex-submit-panel .submission-selected-player-value {{
        font-size: 1.125rem;
        line-height: 1.4;
    }}
    .st-key-full-ex-submit-panel .submission-ex-rating-note,
    .st-key-full-ex-submit-panel .submission-selected-player-detail {{
        font-size: 0.875rem;
        line-height: 1.4;
        margin-top: 0.15rem;
    }}
    .st-key-full-ex-submit-panel .submission-rating-divider {{
        border-top: 1px solid rgba(250, 250, 250, 0.2);
        margin: 0;
        height: 0;
    }}
    .st-key-full-ex-submit-panel [data-testid="stMarkdownContainer"]:has(.submission-accepted) {{
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-full-ex-submit-panel .submission-accepted {{
        background: rgba(33, 195, 84, 0.15);
        border: 1px solid rgba(33, 195, 84, 0.45);
        border-radius: 0.5rem;
        color: rgb(33, 195, 84);
        font-size: 1rem;
        font-weight: 600;
        line-height: 1.4;
        margin: 0.75rem 0 0;
        padding: 0.85rem 1rem;
        text-align: center;
    }}
    .st-key-full-ex-leaderboard-body {{
        display: flex !important;
        flex-direction: column-reverse !important;
        align-items: stretch !important;
        width: fit-content !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-search {{
        width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-table {{
        width: fit-content !important;
        max-width: 100% !important;
    }}
    .st-key-full-ex-leaderboard-body [data-testid="stTextInput"],
    .st-key-full-ex-leaderboard-body [data-testid="stTextInput"] > div,
    .st-key-full-ex-leaderboard-body [data-testid="stTextInput"] input {{
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }}
    .st-key-full-ex-leaderboard-body [data-testid="stDataFrame"],
    .st-key-full-ex-leaderboard-body [data-testid="stDataFrameResizable"] {{
        width: fit-content !important;
        max-width: 100% !important;
    }}
    [data-testid="stMarkdownContainer"]:has(.potential-gains-slider-divider) {{
        display: flex !important;
        align-items: stretch !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    .potential-gains-slider-divider {{
        border-left: 1px solid rgba(250, 250, 250, 0.2);
        height: 100%;
        min-height: 4.5rem;
        margin: 0 auto;
        width: 0;
    }}
    @media (min-width: {LEADERBOARD_SIDE_BY_SIDE_MIN_PX}px) {{
        .st-key-full-ex-leaderboard-layout .st-key-full-ex-leaderboard-content {{
            margin-right: 1.5rem !important;
        }}
    }}
    @media (max-width: {LEADERBOARD_SIDE_BY_SIDE_MIN_PX - 1}px) {{
        .st-key-full-ex-leaderboard-layout [data-testid="stHorizontalBlock"] {{
            flex-direction: column !important;
            align-items: flex-start !important;
        }}
        .st-key-full-ex-leaderboard-layout .st-key-full-ex-submit-panel {{
            width: 100% !important;
        }}
        .st-key-full-ex-leaderboard-layout .st-key-full-ex-leaderboard-content {{
            margin-right: 0 !important;
        }}
    }}
    @media (max-width: {SIDE_BY_SIDE_MIN_VIEWPORT_PX - 1}px) {{
        .st-key-rating-boards-layout[data-testid="stHorizontalBlock"],
        .st-key-rating-boards-layout > [data-testid="stHorizontalBlock"] {{
            flex-direction: column !important;
        }}
        .st-key-rating-boards-layout .st-key-ex-rating-board-column,
        .st-key-rating-boards-layout .st-key-ex-rating-board,
        .st-key-rating-boards-layout .st-key-std-rating-board {{
            flex: 0 0 auto !important;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def _target_accuracy_options() -> list[float]:
    options = [float(value) for value in range(80, 98)]
    options.extend(98 + 0.25 * step for step in range(9))
    return options


def _format_target_accuracy(value: float) -> str:
    if value == int(value):
        return f"{int(value)}%"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _render_potential_gains_expander(
    ratings: list[ChartRating],
    rating_attr: str,
    *,
    key: str,
    expander_label: str = "Potential Rating Gains",
    potential_column_label: str = "Potential Rating",
    target_accuracy_label: str = "Target Accuracy",
) -> None:
    with st.expander(expander_label, expanded=False):
        level_cap_col, divider_col, target_accuracy_col = st.columns(
            [1, 0.04, 1],
            vertical_alignment="center",
        )
        with level_cap_col:
            level_cap = st.select_slider(
                "Level Cap",
                options=list(range(10, 26)),
                value=25,
                key=f"{key}-level-cap",
            )
        with divider_col:
            st.markdown(
                '<div class="potential-gains-slider-divider"></div>',
                unsafe_allow_html=True,
            )
        with target_accuracy_col:
            target_accuracy = st.select_slider(
                target_accuracy_label,
                options=_target_accuracy_options(),
                value=100.0,
                format_func=_format_target_accuracy,
                key=f"{key}-target-accuracy",
            )
        gains = potential_gains_from_perfect(
            ratings,
            rating_attr,
            level_cap=level_cap,
            target_accuracy=float(target_accuracy),
        )
        if not gains:
            st.caption(
                f"No charts at or below level {level_cap} with potential rating to gain."
            )
            return

        ranks = competition_ranks_for_values([entry.potential_gain for entry in gains])
        st.dataframe(
            [
                {
                    "Rank": rank,
                    "Chart": format_song_display_name(entry.chart.song),
                    "Difficulty": entry.chart.difficulty,
                    "Level": entry.chart.level,
                    potential_column_label: format_potential_gain_display(entry.potential_gain),
                }
                for rank, entry in zip(ranks, gains, strict=True)
            ],
            use_container_width=True,
            hide_index=True,
            height=min((len(gains) + 1) * TABLE_ROW_HEIGHT, LEADERBOARD_TABLE_HEIGHT),
            key=key,
        )


def board_header(
    title: str,
    rating: str,
    caption: str | None = None,
    as_of: str | None = None,
) -> None:
    caption_html = (
        f'<span style="font-size: 0.85rem; color: #a0a0a0; margin-left: 0.75rem;">{caption}</span>'
        if caption
        else ""
    )
    as_of_html = (
        f'<span style="font-size: 0.95rem; font-weight: 400; color: #a0a0a0; '
        f'margin-left: 0.4rem;">as of {as_of}</span>'
        if as_of
        else ""
    )

    st.markdown(
        f"""
        <div style="display: flex; align-items: baseline; margin: 0 0 0.35rem 0;">
            <p style="text-decoration: underline; font-size: 1.375rem; font-weight: 600;
                      margin: 0;">{title}</p>
            {as_of_html}
        </div>
        <div style="display: flex; align-items: baseline; margin: 0 0 0.5rem 0;
                    min-height: 2.5rem;">
            <span style="font-size: 2rem; font-weight: 700; line-height: 1;">{rating}</span>
            {caption_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=300, show_spinner="Loading...")
def _load_players_with_scores() -> list[dict[str, object]] | None:
    try:
        players = load_players_with_scores_from_supabase()
        if not players:
            return players
        rankings, _ = load_ex_leaderboard_with_warning()
        rank_by_id = {entry.player_id: entry.rank for entry in rankings}
        last_updated_by_id = {entry.player_id: entry.last_updated for entry in rankings}
        return [
            {
                **player,
                "rank": rank_by_id.get(str(player["player_id"])),
                "last_updated": last_updated_by_id.get(str(player["player_id"])),
            }
            for player in players
        ]
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner="Loading...")
def _load_player_board_data(player_id: str) -> tuple[list[ChartRating], bool]:
    return load_player_ratings_from_supabase(player_id)


def _board_player_option_label(player: dict[str, object]) -> str:
    rank = player.get("rank")
    if rank:
        return f'{player["display_name"]} (#{rank})'
    return str(player["display_name"])


def _find_board_player(
    players: list[dict[str, object]],
    *,
    option_label: str = "",
) -> dict[str, object] | None:
    if not option_label or option_label == BOARD_PLAYER_SELECT_PLACEHOLDER:
        return None
    for player in players:
        if _board_player_option_label(player) == option_label:
            return player
    return None


def _ex_board_table_row(
    rank: int,
    chart: ChartRating,
    *,
    include_accuracy: bool,
) -> dict[str, object]:
    row: dict[str, object] = {
        "Rank": rank,
        "Chart": format_song_display_name(chart.song),
        "Difficulty": chart.difficulty,
        "Level": chart.level,
    }
    if include_accuracy:
        row["Accuracy"] = f"{chart.standard_accuracy:.2f}"
    row.update(
        {
            "Score": chart.score,
            "Max Score": chart.max_score,
            "EX Accuracy": f"{chart.ex_accuracy:.2f}",
            "EX Grade": chart.ex_grade,
            "EX Rating": format_rating_display(chart.ex_rating),
        }
    )
    return row


def _render_rating_boards(
    ratings: list[ChartRating],
    *,
    csv_file_name: str = "ex_rating_board.csv",
    include_standard: bool = True,
    include_accuracy: bool = True,
    as_of: str | None = None,
    notice: str | None = None,
) -> None:
    _, standard_total, ex_top, standard_top = get_rating_boards(ratings)
    ex_with_completion = player_ex_rating_with_completion(ratings)
    standard_with_completion = standard_total + COMPLETION_BONUS

    if include_standard:
        board_layout = st.container(
            key="rating-boards-layout",
            horizontal=True,
            gap="medium",
            vertical_alignment="top",
        )
    else:
        board_layout = st.container(key="rating-boards-layout")

    with board_layout:
        ex_board_wrapper = (
            st.container(key="ex-rating-board-column")
            if notice
            else contextlib.nullcontext()
        )
        with ex_board_wrapper:
            if notice:
                st.info(notice)
            with st.container(border=True, key="ex-rating-board"):
                board_header(
                    "EX Rating",
                    format_rating_display(ex_with_completion),
                    "Includes +2.0 completion bonus",
                    as_of=format_last_updated(as_of) if as_of else None,
                )
                st.dataframe(
                    [
                        _ex_board_table_row(
                            rank,
                            chart,
                            include_accuracy=include_accuracy,
                        )
                        for rank, chart in enumerate(ex_top, 1)
                    ],
                    use_container_width=True,
                    hide_index=True,
                    height=TABLE_HEIGHT,
                )
                _render_potential_gains_expander(
                    ratings,
                    "ex_rating",
                    key="ex-potential-gains",
                    potential_column_label="Potential EX Rating",
                    target_accuracy_label="Target EX Accuracy",
                )

        if include_standard:
            with st.container(border=True, key="std-rating-board"):
                board_header(
                    "Standard Rating",
                    format_rating_display(standard_with_completion),
                    "Includes +2.0 completion bonus",
                )
                st.dataframe(
                    [
                        {
                            "Rank": rank,
                            "Chart": format_song_display_name(chart.song),
                            "Difficulty": chart.difficulty,
                            "Level": chart.level,
                            "Accuracy": f"{chart.standard_accuracy:.2f}",
                            "Grade": chart.standard_grade,
                            "Rating": format_rating_display(chart.standard_rating),
                        }
                        for rank, chart in enumerate(standard_top, 1)
                    ],
                    use_container_width=True,
                    hide_index=True,
                    height=TABLE_HEIGHT,
                )
                _render_potential_gains_expander(
                    ratings,
                    "standard_rating",
                    key="std-potential-gains",
                    target_accuracy_label="Target Accuracy",
                )

    csv_data = (
        format_rating_board_csv(ratings)
        if include_standard
        else format_ex_rating_board_csv(ratings, include_accuracy=include_accuracy)
    )
    st.download_button(
        label="Download full board (CSV)",
        data=csv_data.encode("utf-8"),
        file_name=csv_file_name,
        mime="text/csv",
    )


def _uploaded_file_hash(uploaded: st.runtime.uploaded_file_manager.UploadedFile) -> str:
    return hashlib.sha256(uploaded.getvalue()).hexdigest()


def _already_submitted_full_ex(
    player_id: str,
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None,
) -> bool:
    last = st.session_state.get("last_full_ex_submission")
    if not last or uploaded is None or not player_id:
        return False
    return (
        last["player_id"] == player_id
        and last["file_hash"] == _uploaded_file_hash(uploaded)
    )


def _accepted_full_ex_submission_message() -> str | None:
    last = st.session_state.get("last_full_ex_submission")
    if not last:
        return None
    message = last.get("message")
    return str(message).strip() if message else None


def _record_full_ex_submission(
    player_id: str,
    uploaded: st.runtime.uploaded_file_manager.UploadedFile,
    message: str,
) -> None:
    st.session_state.last_full_ex_submission = {
        "player_id": player_id,
        "file_hash": _uploaded_file_hash(uploaded),
        "message": message,
    }


def _load_ratings_from_upload(
    uploaded_file: st.runtime.uploaded_file_manager.UploadedFile,
) -> tuple[list[ChartRating] | None, str | None]:
    try:
        highscores = json.loads(uploaded_file.getvalue().decode("utf-8"))
    except json.JSONDecodeError:
        return None, "That file doesn't look like valid JSON."
    if "highScores" not in highscores:
        return None, "Missing `highScores` in the JSON."
    loaded_ratings = build_ratings(highscores, DEFAULT_MAX_SCORES_PATH)
    if not loaded_ratings:
        return None, "No rated charts found in that file."
    return loaded_ratings, None


FULL_EX_PLAYER_SELECT_PLACEHOLDER = "— Select a player —"
FULL_EX_SUBMIT_PLAYER_SEARCH_LIMIT = 50
BOARD_PLAYER_SELECT_PLACEHOLDER = "— Select a player —"
BOARD_PLAYER_SEARCH_LIMIT = 50


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


def _render_submission_using_line(filename: str, from_above: bool) -> None:
    if from_above:
        st.caption(f"Using **{filename}** from your upload above.")
    else:
        st.caption(f"Using **{filename}**.")


def _render_submission_ex_rating(submitted_rating: float) -> None:
    st.markdown(
        f"""
        <div class="submission-ex-rating">
            <div class="submission-ex-rating-value">
                Your EX Rating: <strong>{format_rating_display(submitted_rating)}</strong>
            </div>
            <div class="submission-ex-rating-note">(includes +2.0 completion bonus)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_submission_accepted(message: str) -> None:
    st.markdown(
        f'<div class="submission-accepted">{message}</div>',
        unsafe_allow_html=True,
    )


def _full_ex_player_option_label(entry: object) -> str:
    return f"{entry.player} (#{entry.rank})"


def _find_full_ex_leaderboard_entry(
    full_rankings: list,
    *,
    player_id: str = "",
    option_label: str = "",
) -> object | None:
    if player_id:
        for entry in full_rankings:
            if entry.player_id == player_id:
                return entry
    if option_label and option_label != FULL_EX_PLAYER_SELECT_PLACEHOLDER:
        for entry in full_rankings:
            if _full_ex_player_option_label(entry) == option_label:
                return entry
    return None


def _render_full_ex_selected_player(entry: object) -> None:
    st.markdown(
        f"""
        <div class="submission-selected-player">
            <div class="submission-selected-player-value">
                Selected player: <strong>{entry.player}</strong>
            </div>
            <div class="submission-selected-player-detail">
                Rank <strong>#{entry.rank}</strong>
                · EX Rating <strong>{format_rating_display(entry.ex_rating)}</strong>
                · Last updated <strong>{format_last_updated(entry.last_updated, include_time=True)}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_full_ex_submission_panel(
    full_rankings: list,
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None = None,
    ratings: list[ChartRating] | None = None,
) -> None:
    submission_file: st.runtime.uploaded_file_manager.UploadedFile | None = None
    submission_ratings: list[ChartRating] | None = None
    submission_error: str | None = None

    if uploaded is not None:
        submission_file = uploaded
        submission_ratings = ratings
        _render_submission_using_line(uploaded.name, from_above=True)
    else:
        submission_file = st.file_uploader(
            "arcade-highscores.json",
            type="json",
            key="full-ex-submission-highscores",
        )
        if submission_file is not None:
            submission_ratings, submission_error = _load_ratings_from_upload(submission_file)
            if submission_error:
                st.error(submission_error)
        else:
            st.info("Upload your arcade-highscores.json to submit.")

    submitted_rating: float | None = None
    if submission_ratings:
        submitted_rating = player_ex_rating_with_completion(submission_ratings)
        _render_submission_ex_rating(submitted_rating)
        st.markdown('<div class="submission-rating-divider"></div>', unsafe_allow_html=True)

    st.caption(
        "Select an existing player from the full leaderboard"
        + (
            " to submit your updated rating."
            if uploaded is not None
            else ", then upload your arcade-highscores.json to submit an updated rating."
        )
    )
    st.caption(
        "_Note: Existing ratings can only be updated with a higher rating. "
        "Contact Nico with any issues or requests._"
    )

    if not supabase_configured():
        st.info(
            "Full leaderboard submissions are not set up on this server yet. "
            "Add `supabase.db_url` to `.streamlit/secrets.toml` "
            "(see `.streamlit/secrets.toml.example`)."
        )

    player_search = st.text_input(
        "Search players",
        placeholder="Search by player name…",
        key="full-ex-submit-player-search",
    ).strip()
    search_needle = player_search.casefold()

    if not search_needle:
        st.caption("Search for a player to select them.")
        player_options = [FULL_EX_PLAYER_SELECT_PLACEHOLDER]
        candidate_entries: list = []
    else:
        candidate_entries = [
            entry
            for entry in full_rankings
            if search_needle in entry.player.casefold()
        ][:FULL_EX_SUBMIT_PLAYER_SEARCH_LIMIT]
        player_options = [FULL_EX_PLAYER_SELECT_PLACEHOLDER] + [
            _full_ex_player_option_label(entry) for entry in candidate_entries
        ]
        if not candidate_entries:
            st.caption("No players match your search.")

    _auto_select_if_single_match(
        select_key="full-ex-submit-player-select",
        placeholder=FULL_EX_PLAYER_SELECT_PLACEHOLDER,
        matches=[_full_ex_player_option_label(entry) for entry in candidate_entries],
    )

    selected_option = st.selectbox(
        "Player",
        options=player_options,
        key="full-ex-submit-player-select",
        disabled=not search_needle or not candidate_entries,
    )

    selected_entry = _find_full_ex_leaderboard_entry(
        full_rankings,
        option_label=selected_option,
    )
    if selected_entry is not None:
        _render_full_ex_selected_player(selected_entry)
        st.markdown('<div class="submission-rating-divider"></div>', unsafe_allow_html=True)

    submission_accepted = (
        selected_entry is not None
        and _already_submitted_full_ex(selected_entry.player_id, submission_file)
    )
    accepted_message = (
        _accepted_full_ex_submission_message() if submission_accepted else None
    )

    submission_blocked_reason: str | None = None
    if (
        selected_entry is not None
        and submitted_rating is not None
        and not submission_accepted
    ):
        _, submission_blocked_reason = validate_full_ex_rating_submission(
            selected_entry.ex_rating,
            submitted_rating,
        )

    submission_in_progress = st.session_state.get("full_ex_submission_in_progress", False)

    if submission_accepted:
        _render_submission_accepted(accepted_message or "Rating update saved!")
    else:
        if submission_blocked_reason:
            st.warning(submission_blocked_reason)

        with st.form("full-ex-submit-ex-rating", clear_on_submit=False, enter_to_submit=False):
            submitted = st.form_submit_button(
                "Update leaderboard rating",
                disabled=(
                    submission_in_progress
                    or submission_file is None
                    or submission_ratings is None
                    or submission_error is not None
                    or not supabase_configured()
                    or selected_entry is None
                    or submission_blocked_reason is not None
                ),
            )

        if submitted and not submission_in_progress:
            if submission_file is None:
                st.error("Upload your arcade-highscores.json to submit.")
            elif submission_error:
                st.error(submission_error)
            elif selected_entry is None:
                st.error("Select a player from the full leaderboard.")
            elif submission_blocked_reason:
                st.warning(submission_blocked_reason)
            elif submitted_rating is not None:
                try:
                    highscores = json.loads(submission_file.getvalue().decode("utf-8"))
                except json.JSONDecodeError:
                    st.error("That file doesn't look like valid JSON.")
                else:
                    st.session_state.full_ex_pending_submission = {
                        "player_id": selected_entry.player_id,
                        "ex_rating": submitted_rating,
                        "highscores": highscores,
                    }
                    st.session_state.full_ex_submission_in_progress = True
                    st.rerun()
            else:
                st.warning("No rated charts found in that file.")

    if submission_in_progress and st.session_state.get("full_ex_pending_submission"):
        pending = st.session_state.pop("full_ex_pending_submission")
        with st.spinner("Saving rating update…"):
            success, message = submit_full_ex_rating_update(
                player_id=pending["player_id"],
                ex_rating=pending["ex_rating"],
                highscores=pending["highscores"],
            )
        st.session_state.full_ex_submission_in_progress = False
        if success:
            if submission_file is not None:
                _record_full_ex_submission(
                    pending["player_id"],
                    submission_file,
                    message,
                )
            _load_ranked_ex_leaderboard.clear()
            st.rerun()
        else:
            st.warning(message)


def _render_full_ex_leaderboard_table(rankings: list) -> None:
    table_height = min((len(rankings) + 1) * TABLE_ROW_HEIGHT, LEADERBOARD_TABLE_HEIGHT)
    st.dataframe(
        [
            {
                "Rank": entry.rank,
                "Player": entry.player,
                "EX Rating": format_rating_display(entry.ex_rating),
                "Last Updated": parse_last_updated(entry.last_updated),
            }
            for entry in rankings
        ],
        column_config={
            "Last Updated": st.column_config.DatetimeColumn(
                format="MMMM D, YYYY h:mm A",
                width=FULL_EX_LEADERBOARD_LAST_UPDATED_WIDTH_PX,
            ),
        },
        width="content",
        hide_index=True,
        height=table_height,
    )


@st.cache_data(ttl=300, show_spinner="Loading...")
def _load_ranked_ex_leaderboard():
    return load_ex_leaderboard_with_warning()


def render_full_ex_rating_leaderboard(
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None = None,
    ratings: list[ChartRating] | None = None,
) -> None:
    st.divider()

    with st.container(key="full-ex-leaderboard-outer", width="content"):
        st.subheader("EX Rating Leaderboard")
        st.caption(
            "Estimated EX Ratings from imported leaderboard scores. "
            "Submit your highscores file to update your rating!"
        )

        if not leaderboard_available():
            st.warning(
                "Full EX rating leaderboard data is not available yet. "
                "Ensure `resources/ex_rating_baseline.csv` is present in the repo."
            )
            return

        search_query = st.session_state.get("full-ex-leaderboard-search-input", "").strip()

        try:
            full_rankings, supabase_load_failed = _load_ranked_ex_leaderboard()
        except Exception as error:
            st.error(f"Could not load full EX rating leaderboard: {error}")
            return

        if supabase_load_failed:
            st.warning(SUPABASE_LOAD_ERROR_MESSAGE)

        if not full_rankings:
            st.info("No players found in the full EX rating leaderboard.")
            return

        display_rankings = full_rankings
        if search_query:
            needle = search_query.casefold()
            display_rankings = [
                entry for entry in full_rankings if needle in entry.player.casefold()
            ]

        with st.container(
            key="full-ex-leaderboard-layout",
            horizontal=True,
            gap="medium",
            vertical_alignment="top",
        ):
            with st.container(key="full-ex-leaderboard-content", width="content"):
                with st.container(key="full-ex-leaderboard-body", width="content"):
                    if display_rankings:
                        with st.container(key="full-ex-leaderboard-table"):
                            _render_full_ex_leaderboard_table(display_rankings)
                    elif search_query:
                        st.caption("No players match your search.")

                    with st.container(key="full-ex-leaderboard-search"):
                        st.text_input(
                            "Search players",
                            placeholder="Search by player name…",
                            key="full-ex-leaderboard-search-input",
                        )

            with st.container(border=True, key="full-ex-submit-panel", width="content"):
                st.subheader("Submit your EX Rating")
                _render_full_ex_submission_panel(full_rankings, uploaded, ratings)


def render_ex_rating_info() -> None:
    st.divider()
    st.subheader("How EX Rating Works")
    st.markdown(
        """
Your **EX Rating** is the sum of your **top 25** chart EX Ratings from Classic mode scores
(excluding custom charts). Each chart on the board contributes one EX Rating value.

### EX Accuracy

**EX Accuracy** measures how close your score is to the chart's maximum possible score:

**EX Accuracy = (Your Score ÷ Critical Max Score) × 100**

Critical Max Score is the highest score achievable on that chart when every note is hit within +/- 8ms of accuracy.

### EX Grade

**EX Grade** uses the same grade brackets as the standard system, but checks **EX Accuracy**
instead of note accuracy. A +1% bonus is still applied when you have no misses.

The two EX-specific differences:

- **EX S++** — No misses, S-tier EX Accuracy, **and** every note in your combo was a Critical
  (your critical count equals your max combo).
- **EX S+** — No misses and EX Accuracy of **98% or higher** (standard S+ requires above 99%).

All other grades follow the same thresholds as standard: S at 95%+, A at 85%+, B at 75%+,
C at 65%+, D at 55%+, and HOW? below that.

### EX Rating (per chart)

Each chart's **EX Rating** uses the same formula as standard rating, substituting EX Accuracy
and the grade bonus derived from it:

**EX Rating = (Chart Level × (accPower + gradeBonus)) ÷ 5625**

where **accPower = (EX Accuracy − 50)^1.12** (when EX Accuracy is above 50%).

The **grade bonus** follows the same rules as standard rating — up to 25 points when accuracy
is high enough, with lower bonuses for lower grades.

### Standard Rating (for comparison)

The Standard Rating board uses **note accuracy** from your save file instead of score-based
EX Accuracy. Its player total includes a **+2.0 completion bonus** on top of the top-25 sum,
matching the in-game display.
"""
    )


st.markdown(
    """
    <div class="page-header">
        <h1 style="margin: 0 0 0.1rem 0; padding-top: 0.15rem; line-height: 1.25; font-size: 2.25rem;">
            Unbeatable EX Rating
        </h1>
        <p style="margin: -0.55rem 0 0.5rem 0; font-size: 1.375rem; font-weight: 500; opacity: 0.9;">
            A Community-Created EX Rating System by FacadeNico
        </p>
        <hr style="margin: 0.5rem 0 1rem 0; border: none; border-top: 1px solid rgba(250, 250, 250, 0.2);">
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "Upload your **arcade-highscores.json** or search for a player to see rating boards. "
    "Only Classic speed charts are rated (no Double Time / Half Time or custom charts)."
)
st.markdown(
    "On Windows, this file is usually at "
    "`C:\\Users\\<YourName>\\AppData\\LocalLow\\D-CELL GAMES\\UNBEATABLE\\PROFILES\\<profile>\\arcade-highscores.json`. "
)

board_source_options = ["Upload file"]
if supabase_configured():
    board_source_options.append("Search player")

uploaded = None
ratings: list[ChartRating] | None = None
board_view_include_standard = True
board_view_include_accuracy = True
board_view_as_of: str | None = None
board_view_csv_name = "ex_rating_board.csv"
board_view_notice: str | None = None

with st.container(key="board-viewer-section", width="content"):
    board_source = st.radio(
        "View boards from",
        options=board_source_options,
        horizontal=True,
        key="board-source-mode",
    )

    if board_source == "Upload file":
        uploaded = st.file_uploader("arcade-highscores.json", type="json", key="arcade-highscores")

        if uploaded is None:
            st.info("Choose your arcade highscores file to get started.")
        else:
            try:
                highscores = json.loads(uploaded.getvalue().decode("utf-8"))
            except json.JSONDecodeError:
                st.error("That file doesn't look like valid JSON. Make sure you're uploading arcade-highscores.json.")
            else:
                if "highScores" not in highscores:
                    st.error("Missing `highScores` in the JSON. Is this the right file?")
                else:
                    with st.spinner("Calculating ratings…"):
                        ratings = build_ratings(highscores, DEFAULT_MAX_SCORES_PATH)

                    if not ratings:
                        st.warning(
                            "No rated charts found. Check that your file has Classic mode scores for known charts."
                        )
    else:
        if not supabase_configured():
            st.info(
                "Player search is not set up on this server yet. "
                "Add `supabase.db_url` to `.streamlit/secrets.toml` "
                "(see `.streamlit/secrets.toml.example`)."
            )
        else:
            players_with_scores = _load_players_with_scores()
            if players_with_scores is None:
                st.error("Could not load players with stored scores.")
            elif not players_with_scores:
                st.info("No stored player scores are available yet.")
            else:
                player_search = st.text_input(
                    "Search players",
                    placeholder="Search by player name…",
                    key="board-player-search",
                ).strip()
                search_needle = player_search.casefold()

                if not search_needle:
                    st.caption(
                        f"Search one of {len(players_with_scores)} players with stored scores."
                    )
                    player_options = [BOARD_PLAYER_SELECT_PLACEHOLDER]
                    candidate_players: list[dict[str, object]] = []
                else:
                    candidate_players = [
                        player
                        for player in players_with_scores
                        if search_needle in str(player["display_name"]).casefold()
                    ][:BOARD_PLAYER_SEARCH_LIMIT]
                    player_options = [BOARD_PLAYER_SELECT_PLACEHOLDER] + [
                        _board_player_option_label(player) for player in candidate_players
                    ]
                    if not candidate_players:
                        st.caption("No players match your search.")

                _auto_select_if_single_match(
                    select_key="board-player-select",
                    placeholder=BOARD_PLAYER_SELECT_PLACEHOLDER,
                    matches=[_board_player_option_label(player) for player in candidate_players],
                )

                selected_option = st.selectbox(
                    "Player",
                    options=player_options,
                    key="board-player-select",
                    disabled=not search_needle or not candidate_players,
                )
                selected_player = _find_board_player(
                    players_with_scores,
                    option_label=selected_option,
                )

                if selected_player is not None:
                    ratings, has_accuracy = _load_player_board_data(
                        str(selected_player["player_id"])
                    )

                    if not ratings:
                        st.warning("No rated charts found for that player.")
                    else:
                        if not has_accuracy:
                            player_name = str(selected_player["display_name"])
                            board_view_notice = (
                                "Note: Only EX Accuracies and Ratings are available. "
                                f"**{player_name}** may submit their arcade-highscores.json below "
                                "to share their Accuracies and Standard Rating Board."
                            )
                        board_view_include_standard = has_accuracy
                        board_view_include_accuracy = has_accuracy
                        safe_name = str(selected_player["display_name"]).strip().replace(" ", "_")
                        board_view_csv_name = f"{safe_name}_ex_rating_board.csv"
                        last_updated = selected_player.get("last_updated")
                        board_view_as_of = (
                            str(last_updated).strip() if last_updated else None
                        )

if ratings:
    _render_rating_boards(
        ratings,
        csv_file_name=board_view_csv_name,
        include_standard=board_view_include_standard,
        include_accuracy=board_view_include_accuracy,
        as_of=board_view_as_of,
        notice=board_view_notice,
    )

render_full_ex_rating_leaderboard(uploaded, ratings if uploaded is not None else None)
render_ex_rating_info()
