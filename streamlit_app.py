"""Unbeatable EX Rating — web UI (Streamlit)."""

import hashlib
import importlib
import json

from datetime import date, datetime, timezone

import streamlit as st

from rating import build_ratings, get_rating_boards
from rating import constants as constants_module
from rating.models import ChartRating

importlib.reload(constants_module)

from rating import board as board_module
from rating import chart_levels as chart_levels_module
from rating import data as data_module
from rating import formatting as formatting_module
from rating import shared_rankings as shared_rankings_module
from rating import submissions as submissions_module
from rating import imported_players as imported_players_module
from rating import ex_leaderboard_db as ex_leaderboard_db_module
from rating import full_ex_submissions as full_ex_submissions_module
from rating import public_leaderboard as public_leaderboard_module
from rating.supabase_config import supabase_configured

importlib.reload(data_module)
importlib.reload(formatting_module)
importlib.reload(board_module)
importlib.reload(chart_levels_module)
importlib.reload(submissions_module)
importlib.reload(shared_rankings_module)
importlib.reload(imported_players_module)
importlib.reload(ex_leaderboard_db_module)
importlib.reload(public_leaderboard_module)
importlib.reload(full_ex_submissions_module)

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
player_ex_rating_with_completion = board_module.player_ex_rating_with_completion
load_shared_ex_rankings = shared_rankings_module.load_shared_ex_rankings
find_player_ranking = shared_rankings_module.find_player_ranking
competition_ranks = shared_rankings_module.competition_ranks
rankings_after_submission = shared_rankings_module.rankings_after_submission
validate_rating_submission = shared_rankings_module.validate_rating_submission
pending_submission_url = submissions_module.pending_submission_url
submit_ranking = submissions_module.submit_ranking
submit_pending_ranking = submissions_module.submit_pending_ranking
load_ex_leaderboard = public_leaderboard_module.load_ex_leaderboard
load_ex_leaderboard_with_warning = public_leaderboard_module.load_ex_leaderboard_with_warning
leaderboard_available = public_leaderboard_module.leaderboard_available
SUPABASE_LOAD_ERROR_MESSAGE = public_leaderboard_module.SUPABASE_LOAD_ERROR_MESSAGE
validate_full_ex_rating_submission = full_ex_submissions_module.validate_full_ex_rating_submission
submit_full_ex_rating_update = full_ex_submissions_module.submit_full_ex_rating_update

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y")


def _entry_last_updated(entry: object) -> str:
    value = getattr(entry, "last_updated", None)
    if value:
        return str(value)
    return str(getattr(entry, "date_added", ""))


def format_last_updated(value: object) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        elif dt.hour or dt.minute or dt.second or dt.microsecond:
            dt = dt.replace(tzinfo=timezone.utc).astimezone()
        return dt.strftime("%B %d, %Y")
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%B %d, %Y")
        except ValueError:
            continue
    return text


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
# Leaderboard + submission panel are content-width; side-by-side below the full board breakpoint.
SHARED_RANKINGS_SIDE_BY_SIDE_MIN_PX = 1000
# Max width for the submission panel when shown beside the leaderboard.
SUBMIT_EX_RATING_PANEL_MAX_WIDTH_PX = 540
# Each board width at the side-by-side breakpoint (~1rem page inset per side, 1rem gap).
BOARD_MAX_WIDTH_PX = (SIDE_BY_SIDE_MIN_VIEWPORT_PX - 64 - 16) // 2

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
    .st-key-shared-rankings-outer [data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: flex-start !important;
        gap: 1rem;
        width: fit-content !important;
        max-width: 100% !important;
    }}
    .st-key-shared-rankings-outer .st-key-shared-ex-leaderboard {{
        flex: 0 0 auto !important;
        width: auto !important;
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
    .st-key-shared-rankings-outer .st-key-submit-ex-rating-panel {{
        flex: 0 0 auto !important;
        width: {SUBMIT_EX_RATING_PANEL_MAX_WIDTH_PX}px !important;
        max-width: 100% !important;
    }}
    .st-key-submit-ex-rating-panel [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }}
    .st-key-submit-ex-rating-panel [data-testid="stTextInput"],
    .st-key-submit-ex-rating-panel [data-testid="stFileUploader"],
    .st-key-submit-ex-rating-panel [data-testid="stForm"] {{
        max-width: 100% !important;
    }}
    .st-key-submit-ex-rating-panel [data-testid="stMarkdownContainer"]:has(.submission-ex-rating) {{
        margin: 0 !important;
        padding: 0.35rem 0 !important;
    }}
    .st-key-submit-ex-rating-panel [data-testid="stMarkdownContainer"]:has(.submission-rating-divider) {{
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-submit-ex-rating-panel .submission-ex-rating {{
        margin: 0;
        padding: 0;
        color: rgba(250, 250, 250, 0.6);
    }}
    .st-key-submit-ex-rating-panel .submission-ex-rating-value {{
        font-size: 1.125rem;
        line-height: 1.4;
    }}
    .st-key-submit-ex-rating-panel .submission-ex-rating-note {{
        font-size: 0.875rem;
        font-style: italic;
        line-height: 1.4;
        margin-top: 0.15rem;
    }}
    .st-key-submit-ex-rating-panel .submission-rating-divider {{
        border-top: 1px solid rgba(250, 250, 250, 0.2);
        margin: 0;
        height: 0;
    }}
    .st-key-submit-ex-rating-panel [data-testid="stMarkdownContainer"]:has(.submission-accepted) {{
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-submit-ex-rating-panel .submission-accepted {{
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
    @media (min-width: {SHARED_RANKINGS_SIDE_BY_SIDE_MIN_PX}px) {{
        .st-key-shared-rankings-outer .st-key-shared-ex-leaderboard {{
            margin-right: 1.5rem !important;
        }}
        .st-key-full-ex-leaderboard-layout .st-key-full-ex-leaderboard-content {{
            margin-right: 1.5rem !important;
        }}
    }}
    @media (max-width: {SHARED_RANKINGS_SIDE_BY_SIDE_MIN_PX - 1}px) {{
        .st-key-shared-rankings-outer [data-testid="stHorizontalBlock"] {{
            flex-direction: column !important;
            align-items: flex-start !important;
        }}
        .st-key-shared-rankings-outer .st-key-submit-ex-rating-panel {{
            width: 100% !important;
        }}
        .st-key-shared-rankings-outer .st-key-shared-ex-leaderboard {{
            margin-right: 0 !important;
        }}
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
    expander_label: str = "Potential Gains from 100%'s",
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


def board_header(title: str, rating: str, caption: str | None = None) -> None:
    caption_html = (
        f'<span style="font-size: 0.85rem; color: #a0a0a0; margin-left: 0.75rem;">{caption}</span>'
        if caption
        else ""
    )

    st.markdown(
        f"""
        <p style="text-decoration: underline; font-size: 1.375rem; font-weight: 600;
                  margin: 0 0 0.35rem 0;">{title}</p>
        <div style="display: flex; align-items: baseline; margin: 0 0 0.5rem 0;
                    min-height: 2.5rem;">
            <span style="font-size: 2rem; font-weight: 700; line-height: 1;">{rating}</span>
            {caption_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _uploaded_file_hash(uploaded: st.runtime.uploaded_file_manager.UploadedFile) -> str:
    return hashlib.sha256(uploaded.getvalue()).hexdigest()


def _already_submitted(
    player: str,
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None,
) -> bool:
    last = st.session_state.get("last_submission")
    if not last or uploaded is None or not player:
        return False
    return last["player"] == player and last["file_hash"] == _uploaded_file_hash(uploaded)


def _accepted_submission_message() -> str | None:
    last = st.session_state.get("last_submission")
    if not last:
        return None
    message = last.get("message")
    return str(message).strip() if message else None


def _record_submission(
    player: str,
    uploaded: st.runtime.uploaded_file_manager.UploadedFile,
    message: str,
) -> None:
    st.session_state.last_submission = {
        "player": player,
        "file_hash": _uploaded_file_hash(uploaded),
        "message": message,
    }


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


def _get_leaderboard_rankings() -> list | None:
    if "leaderboard_rankings" not in st.session_state:
        st.session_state.leaderboard_rankings = load_shared_ex_rankings()
    return st.session_state.leaderboard_rankings


def _refresh_leaderboard_rankings(player: str, ex_rating: float, date_added: str) -> None:
    fallback = st.session_state.get("leaderboard_rankings") or []
    st.session_state.leaderboard_rankings = rankings_after_submission(
        player,
        ex_rating,
        date_added,
        fallback,
    )


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


MANUAL_PLAYER_ENTRY = "- New Player / Manual Entry -"
FULL_EX_PLAYER_SELECT_PLACEHOLDER = "— Select a player —"
FULL_EX_SUBMIT_PLAYER_SEARCH_LIMIT = 50


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
                · Last updated <strong>{format_last_updated(entry.last_updated)}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_full_ex_submission_panel(full_rankings: list) -> None:
    submission_file = st.file_uploader(
        "arcade-highscores.json",
        type="json",
        key="full-ex-submission-highscores",
    )
    submission_ratings: list[ChartRating] | None = None
    submission_error: str | None = None

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
        "Select an existing player from the full leaderboard, then upload your "
        "arcade-highscores.json to submit an updated rating."
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


def _render_leaderboard_table(rankings: list) -> None:
    ranks = competition_ranks(rankings)
    st.dataframe(
        [
            {
                "Rank": rank,
                "Player": entry.player,
                "EX Rating": format_rating_display(entry.ex_rating),
                "Last Updated": format_last_updated(_entry_last_updated(entry)),
            }
            for rank, entry in zip(ranks, rankings, strict=True)
        ],
        width="content",
        hide_index=True,
        height=LEADERBOARD_TABLE_HEIGHT,
    )


def _render_full_ex_leaderboard_table(rankings: list) -> None:
    table_height = min((len(rankings) + 1) * TABLE_ROW_HEIGHT, LEADERBOARD_TABLE_HEIGHT)
    st.dataframe(
        [
            {
                "Rank": entry.rank,
                "Player": entry.player,
                "EX Rating": format_rating_display(entry.ex_rating),
                "Last Updated": format_last_updated(entry.last_updated),
            }
            for entry in rankings
        ],
        width="content",
        hide_index=True,
        height=table_height,
    )


@st.cache_data(ttl=300)
def _load_ranked_ex_leaderboard():
    return load_ex_leaderboard_with_warning()


def render_full_ex_rating_leaderboard() -> None:
    st.divider()

    with st.container(key="full-ex-leaderboard-outer", width="content"):
        st.subheader("\*WIP* Full EX Rating Leaderboard (Incomplete)")
        st.caption(
            "Estimated EX Ratings from imported leaderboard scores. "
            "This list is incomplete and may change as more player data is added."
        )
        st.markdown(
            '<p style="font-size: 1.125rem; font-weight: 700; margin: 0.25rem 0 0.75rem 0;">'
            "Note: Ratings are as of June 27th, 2026."
            "</p>",
            unsafe_allow_html=True,
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
                _render_full_ex_submission_panel(full_rankings)


def _render_submission_panel(
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None,
    ratings: list[ChartRating] | None,
    leaderboard_rankings: list | None,
) -> None:
    submission_file = uploaded
    submission_ratings = ratings
    submission_error: str | None = None

    if uploaded is not None:
        submission_file = uploaded
        submission_ratings = ratings
        _render_submission_using_line(uploaded.name, from_above=True)
    else:
        panel_upload = st.session_state.get("submission-highscores")
        uploader_label = (
            f"Using {panel_upload.name}."
            if panel_upload is not None
            else "arcade-highscores.json"
        )
        submission_file = st.file_uploader(
            uploader_label,
            type="json",
            key="submission-highscores",
        )
        if submission_file is not None:
            submission_ratings, submission_error = _load_ratings_from_upload(submission_file)
            if submission_error:
                st.error(submission_error)
        else:
            st.info("Upload your arcade-highscores.json to submit.")

    if submission_ratings:
        submitted_rating = player_ex_rating_with_completion(submission_ratings)
        _render_submission_ex_rating(submitted_rating)
        st.markdown('<div class="submission-rating-divider"></div>', unsafe_allow_html=True)
    else:
        submitted_rating = None

    if pending_submission_url() is None:
        st.info(
            "Submissions are not set up on this server yet. "
            "Add your Apps Script deployment URL to `.streamlit/secrets.toml` as "
            "`pending_submission_url` (see `.streamlit/secrets.toml.example`)."
        )
    else:
        st.caption(
            "New names are added to the leaderboard automatically. "
            "If you're already listed, you can update your score by submitting with the same name or selecting your name from the dropdown."
        )
        st.caption(
            "_Note: Existing ratings can only be updated with a higher rating. "
            "Contact Nico with any issues or requests._"
        )

    if leaderboard_rankings:
        player_options = [MANUAL_PLAYER_ENTRY] + sorted(
            {entry.player for entry in leaderboard_rankings},
            key=str.casefold,
        )
        selected_player_option = st.selectbox(
            "Player",
            options=player_options,
            key="submission-player-mode",
        )
        if selected_player_option == MANUAL_PLAYER_ENTRY:
            player = st.text_input("Player name", max_chars=64, key="submission-player").strip()
        else:
            player = selected_player_option.strip()
    else:
        player = st.text_input("Player name", max_chars=64, key="submission-player").strip()

    existing_entry = (
        find_player_ranking(player, leaderboard_rankings)
        if player and leaderboard_rankings
        else None
    )
    submission_accepted = _already_submitted(player, submission_file)
    accepted_message = _accepted_submission_message() if submission_accepted else None

    if existing_entry and not submission_accepted:
        st.caption(
            "Leaderboard entry found: "
            f"**{format_rating_display(existing_entry.ex_rating)}** "
            f"(last updated {format_last_updated(_entry_last_updated(existing_entry))})"
        )

    submission_blocked_reason: str | None = None
    if (
        player
        and submitted_rating is not None
        and leaderboard_rankings
        and not submission_accepted
    ):
        _, submission_blocked_reason = validate_rating_submission(
            player,
            submitted_rating,
            leaderboard_rankings,
        )

    submission_in_progress = st.session_state.get("submission_in_progress", False)

    if submission_accepted:
        _render_submission_accepted(accepted_message or "Added to the leaderboard!")
    else:
        if submission_blocked_reason:
            st.warning(submission_blocked_reason)

        submit_label = "Update leaderboard rating" if existing_entry else "Add to leaderboard"
        with st.form("submit-ex-rating", clear_on_submit=False, enter_to_submit=False):
            submitted = st.form_submit_button(
                submit_label,
                disabled=(
                    submission_in_progress
                    or submission_file is None
                    or submission_ratings is None
                    or submission_error is not None
                    or pending_submission_url() is None
                    or submission_blocked_reason is not None
                ),
            )

        if submitted and not submission_in_progress:
            if not player:
                st.error("Enter your player name.")
            elif submission_file is None:
                st.error("Upload your arcade-highscores.json to submit.")
            elif submission_error:
                st.error(submission_error)
            elif submission_blocked_reason:
                st.warning(submission_blocked_reason)
            elif submission_ratings and submitted_rating is not None:
                st.session_state.pending_submission = {
                    "player": player,
                    "ex_rating": submitted_rating,
                    "date_added": date.today().isoformat(),
                }
                st.session_state.submission_in_progress = True
                st.rerun()
            else:
                st.warning("No rated charts found in that file.")

    if submission_in_progress and st.session_state.get("pending_submission"):
        pending = st.session_state.pop("pending_submission")
        with st.spinner("Submitting to leaderboard…"):
            success, message = submit_ranking(
                pending["player"],
                pending["ex_rating"],
                pending["date_added"],
            )
        st.session_state.submission_in_progress = False
        if success:
            if submission_file is not None:
                _record_submission(pending["player"], submission_file, message)
            _refresh_leaderboard_rankings(
                pending["player"],
                pending["ex_rating"],
                pending["date_added"],
            )
            st.rerun()
        else:
            st.warning(message)


def render_shared_ex_rankings(
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None = None,
    ratings: list[ChartRating] | None = None,
) -> None:
    st.divider()

    with st.container(key="shared-rankings-outer", width="content"):
        with st.container(
            key="shared-rankings-layout",
            horizontal=True,
            gap="medium",
            vertical_alignment="top",
        ):
            with st.container(key="shared-ex-leaderboard", width="content"):
                st.subheader("EX Rating Leaderboard")
                st.caption(
                    "Community leaderboard. Submit your rating to join or update your score!"
                )

                try:
                    rankings = _get_leaderboard_rankings()
                except Exception as error:
                    st.error(f"Could not load shared rankings: {error}")
                    rankings = None

                if rankings is not None:
                    _render_leaderboard_table(rankings)

            with st.container(border=True, key="submit-ex-rating-panel", width="content"):
                st.subheader("Submit your EX Rating")
                _render_submission_panel(uploaded, ratings, rankings)


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
    "Upload your **arcade-highscores.json** to see your EX and Standard rating boards. "
    "Only Classic speed charts are rated (no Double Time / Half Time or custom charts)."
)
st.markdown(
    "On Windows, this file is usually at "
    "`C:\\Users\\<YourName>\\AppData\\LocalLow\\D-CELL GAMES\\UNBEATABLE\\PROFILES\\<profile>\\arcade-highscores.json`. "
)

uploaded = st.file_uploader("arcade-highscores.json", type="json", key="arcade-highscores")
ratings: list[ChartRating] | None = None

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
                st.warning("No rated charts found. Check that your file has Classic mode scores for known charts.")
            else:
                _, standard_total, ex_top, standard_top = get_rating_boards(ratings)
                ex_with_completion = player_ex_rating_with_completion(ratings)
                standard_with_completion = standard_total + COMPLETION_BONUS

                with st.container(
                    key="rating-boards-layout",
                    horizontal=True,
                    gap="medium",
                    vertical_alignment="top",
                ):
                    with st.container(border=True, key="ex-rating-board"):
                        board_header(
                            "EX Rating",
                            format_rating_display(ex_with_completion),
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
                                    "Score": chart.score,
                                    "Max Score": chart.max_score,
                                    "EX Accuracy": f"{chart.ex_accuracy:.2f}",
                                    "EX Grade": chart.ex_grade,
                                    "EX Rating": format_rating_display(chart.ex_rating),
                                }
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
                            expander_label="Potential Gains from EX 100%'s",
                            potential_column_label="Potential EX Rating",
                            target_accuracy_label="Target EX Accuracy",
                        )

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

                st.download_button(
                    label="Download full board (CSV)",
                    data=format_rating_board_csv(ratings).encode("utf-8"),
                    file_name="ex_rating_board.csv",
                    mime="text/csv",
                )

render_shared_ex_rankings(uploaded, ratings)
render_full_ex_rating_leaderboard()
render_ex_rating_info()
