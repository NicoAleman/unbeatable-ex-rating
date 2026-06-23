"""Unbeatable EX Rating — web UI (Streamlit)."""

import json

import streamlit as st

from rating import build_ratings, get_rating_boards
from rating.board import format_rating_board_csv
from rating.constants import COMPLETION_BONUS, DEFAULT_MAX_SCORES_PATH, TOP_N
from rating.shared_rankings import (
    format_date_added,
    format_shared_rankings_last_updated,
    load_shared_ex_rankings,
    shared_rankings_last_updated,
)

st.set_page_config(
    page_title="Unbeatable EX Rating",
    page_icon="⭐",
    layout="wide",
)

TABLE_ROW_HEIGHT = 35
TABLE_HEIGHT = (TOP_N + 1) * TABLE_ROW_HEIGHT
SIDE_BY_SIDE_MIN_VIEWPORT_PX = 1900
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


def render_shared_ex_rankings() -> None:
    st.divider()

    st.subheader("Shared EX Ratings")

    with st.container(key="shared-ex-rankings-content", width="content"):
        st.caption(
            "Updated manually by Nico. Share your EX Rating or arcade-highscores.json with Nico to be included."
        )

        rankings = load_shared_ex_rankings()
        st.dataframe(
            [
                {
                    "Rank": rank,
                    "Player": entry.player,
                    "EX Rating": f"{entry.ex_rating:.3f}",
                    "Date Added": format_date_added(entry.date_added),
                }
                for rank, entry in enumerate(rankings, 1)
            ],
            width="content",
            hide_index=True,
        )

        last_updated = shared_rankings_last_updated()
        if last_updated is not None:
            st.caption(f"Last updated {format_shared_rankings_last_updated(last_updated)}")


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
            A Community-Created EX Ranking System by FacadeNico
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

uploaded = st.file_uploader("arcade-highscores.json", type="json")

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
                ex_total, standard_total, ex_top, standard_top = get_rating_boards(ratings)
                standard_with_completion = standard_total + COMPLETION_BONUS

                with st.container(
                    key="rating-boards-layout",
                    horizontal=True,
                    gap="medium",
                    vertical_alignment="top",
                ):
                    with st.container(border=True, key="ex-rating-board"):
                        board_header("EX Rating", f"{ex_total:.3f}")
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
                                    "EX Rating": f"{chart.ex_rating:.3f}",
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
                            f"{standard_with_completion:.3f}",
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
                                    "Rating": f"{chart.standard_rating:.3f}",
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

render_shared_ex_rankings()
render_ex_rating_info()
