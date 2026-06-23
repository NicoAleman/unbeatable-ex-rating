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
from rating import formatting as formatting_module
from rating import shared_rankings as shared_rankings_module
from rating import submissions as submissions_module

importlib.reload(formatting_module)
importlib.reload(board_module)
importlib.reload(submissions_module)
importlib.reload(shared_rankings_module)

COMPLETION_BONUS = constants_module.COMPLETION_BONUS
DEFAULT_MAX_SCORES_PATH = constants_module.DEFAULT_MAX_SCORES_PATH
TOP_N = constants_module.TOP_N
format_rating_display = formatting_module.format_rating_display
format_rating_board_csv = board_module.format_rating_board_csv
player_ex_rating_with_completion = board_module.player_ex_rating_with_completion
load_shared_ex_rankings = shared_rankings_module.load_shared_ex_rankings
pending_submission_url = submissions_module.pending_submission_url
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
SIDE_BY_SIDE_MIN_VIEWPORT_PX = 1900
# Leaderboard + submission panel are content-width; side-by-side below the full board breakpoint.
SHARED_RANKINGS_SIDE_BY_SIDE_MIN_PX = 1000
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
        align-items: center !important;
        gap: 1rem;
        width: fit-content !important;
        max-width: 100% !important;
    }}
    .st-key-shared-rankings-outer .st-key-shared-ex-leaderboard,
    .st-key-shared-rankings-outer .st-key-submit-ex-rating-panel {{
        flex: 0 0 auto !important;
        width: auto !important;
        max-width: 100% !important;
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


def _record_submission(
    player: str,
    uploaded: st.runtime.uploaded_file_manager.UploadedFile,
) -> None:
    st.session_state.last_submission = {
        "player": player,
        "file_hash": _uploaded_file_hash(uploaded),
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


def _render_submission_panel(
    uploaded: st.runtime.uploaded_file_manager.UploadedFile | None,
    ratings: list[ChartRating] | None,
) -> None:
    submission_file = uploaded
    submission_ratings = ratings
    submission_error: str | None = None

    if uploaded is not None:
        st.caption(f"Using **{uploaded.name}** from your upload above.")
    else:
        submission_file = st.file_uploader(
            "arcade-highscores.json",
            type="json",
            key="submission-highscores",
        )
        if submission_file is not None:
            submission_ratings, submission_error = _load_ratings_from_upload(submission_file)
            if submission_error:
                st.error(submission_error)
            else:
                st.caption(f"Using **{submission_file.name}**.")
        else:
            st.info("Upload your arcade-highscores.json to submit.")

    if submission_ratings:
        st.caption(
            f"Your EX Rating: **{format_rating_display(player_ex_rating_with_completion(submission_ratings))}** "
            "(includes +2.0 completion bonus)"
        )

    if pending_submission_url() is None:
        st.info(
            "Submissions are not set up on this server yet. "
            "Add your Apps Script deployment URL to `.streamlit/secrets.toml` as "
            "`pending_submission_url` (see `.streamlit/secrets.toml.example`)."
        )

    player_name = st.text_input("Player name", max_chars=64, key="submission-player")
    player = player_name.strip()
    already_submitted = _already_submitted(player, submission_file)
    if already_submitted:
        st.caption(
            "Already submitted with this file and player name. "
            "Change your name or upload a new file to submit again."
        )

    with st.form("submit-ex-rating", clear_on_submit=False, enter_to_submit=False):
        submitted = st.form_submit_button(
            "Submit for review",
            disabled=(
                submission_file is None
                or submission_ratings is None
                or submission_error is not None
                or pending_submission_url() is None
                or already_submitted
            ),
        )

    if submitted:
        if not player:
            st.error("Enter your player name.")
        elif submission_file is None:
            st.error("Upload your arcade-highscores.json to submit.")
        elif submission_error:
            st.error(submission_error)
        elif already_submitted:
            st.warning(
                "Already submitted with this file and player name. "
                "Change your name or upload a new file to submit again."
            )
        elif submission_ratings:
            success, message = submit_pending_ranking(
                player,
                player_ex_rating_with_completion(submission_ratings),
                date.today().isoformat(),
            )
            if success:
                _record_submission(player, submission_file)
                st.success(message)
            else:
                st.warning(message)
        else:
            st.warning("No rated charts found in that file.")


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
                    "Community-curated leaderboard. Submit your rating for review!"
                )

                try:
                    rankings = load_shared_ex_rankings()
                except Exception as error:
                    st.error(f"Could not load shared rankings: {error}")
                    rankings = None

                if rankings is not None:
                    st.dataframe(
                        [
                            {
                                "Rank": rank,
                                "Player": entry.player,
                                "EX Rating": format_rating_display(entry.ex_rating),
                                "Last Updated": format_last_updated(_entry_last_updated(entry)),
                            }
                            for rank, entry in enumerate(rankings, 1)
                        ],
                        width="content",
                        hide_index=True,
                    )

            with st.container(border=True, key="submit-ex-rating-panel", width="content"):
                st.subheader("Submit your EX Rating")
                _render_submission_panel(uploaded, ratings)


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
                                    "Chart": chart.song,
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
                                    "Chart": chart.song,
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

                st.download_button(
                    label="Download full board (CSV)",
                    data=format_rating_board_csv(ratings).encode("utf-8"),
                    file_name="ex_rating_board.csv",
                    mime="text/csv",
                )

render_shared_ex_rankings(uploaded, ratings)
render_ex_rating_info()
