"""Unbeatable EX Rating — web UI (Streamlit)."""

import json

import streamlit as st

from rating import build_ratings, get_rating_boards
from rating.board import format_rating_board_csv
from rating.constants import COMPLETION_BONUS, DEFAULT_MAX_SCORES_PATH, TOP_N

st.set_page_config(
    page_title="Unbeatable EX Rating",
    page_icon="⭐",
    layout="wide",
)

TABLE_ROW_HEIGHT = 35
TABLE_HEIGHT = (TOP_N + 1) * TABLE_ROW_HEIGHT


def board_header(title: str, rating: str, caption: str | None = None) -> None:
    caption_html = ""
    if caption:
        caption_html = (
            f'<span style="font-size: 0.85rem; color: #a0a0a0; margin-left: 0.75rem; '
            f'padding-bottom: 0.3rem;">{caption}</span>'
        )

    st.markdown(
        f"""
        <p style="text-decoration: underline; font-size: 1.375rem; font-weight: 600;
                  margin: 0 0 0.35rem 0;">{title}</p>
        <div style="display: flex; align-items: baseline; margin: 0 0 0.5rem 0;">
            <span style="font-size: 2rem; font-weight: 700; line-height: 1;">{rating}</span>
            {caption_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


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


st.title("Unbeatable EX Rating")
st.markdown(
    "Upload your **arcade-highscores.json** to see your EX and Standard rating boards. "
    "Only Classic speed charts are rated (no Double Time / Half Time or custom charts)."
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

                ex_board_col, std_board_col = st.columns(2)

                with ex_board_col:
                    with st.container(border=True):
                        board_header(f"Top {TOP_N} EX Rating", f"{ex_total:.3f}")
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

                with std_board_col:
                    with st.container(border=True):
                        board_header(
                            f"Top {TOP_N} Standard Rating",
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

render_ex_rating_info()
