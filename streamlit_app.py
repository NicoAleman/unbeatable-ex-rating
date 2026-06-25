"""Unbeatable EX Rating — web UI (Streamlit)."""

import hashlib
import importlib
import json

from datetime import date, datetime

import streamlit as st

from rating import build_ratings, get_rating_boards
from rating import constants as constants_module
from rating.models import ChartRating

importlib.reload(constants_module)

from rating import board as board_module
from rating import data as data_module
from rating import formatting as formatting_module
from rating import shared_rankings as shared_rankings_module
from rating import submissions as submissions_module

importlib.reload(data_module)
importlib.reload(formatting_module)
importlib.reload(board_module)
importlib.reload(submissions_module)
importlib.reload(shared_rankings_module)

COMPLETION_BONUS = constants_module.COMPLETION_BONUS
DEFAULT_MAX_SCORES_PATH = constants_module.DEFAULT_MAX_SCORES_PATH
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
        return datetime.fromisoformat(text).strftime("%B %d, %Y")
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
    @media (min-width: {SHARED_RANKINGS_SIDE_BY_SIDE_MIN_PX}px) {{
        .st-key-shared-rankings-outer .st-key-shared-ex-leaderboard {{
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


def _render_potential_gains_expander(
    ratings: list[ChartRating],
    rating_attr: str,
    *,
    key: str,
    expander_label: str = "Potential Gains from 100%'s",
    potential_column_label: str = "Potential Rating",
) -> None:
    with st.expander(expander_label, expanded=False):
        level_cap = st.select_slider(
            "Level Cap",
            options=list(range(1, 26)),
            value=25,
            key=f"{key}-level-cap",
        )
        gains = potential_gains_from_perfect(ratings, rating_attr, level_cap=level_cap)
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
            height=LEADERBOARD_TABLE_HEIGHT,
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
                        )

                st.download_button(
                    label="Download full board (CSV)",
                    data=format_rating_board_csv(ratings).encode("utf-8"),
                    file_name="ex_rating_board.csv",
                    mime="text/csv",
                )

render_shared_ex_rankings(uploaded, ratings)
render_ex_rating_info()
