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

st.title("Unbeatable EX Rating")
st.markdown(
    "Upload your **arcade-highscores.json** to see your EX and Standard rating boards. "
    "Only Classic speed charts are rated (no Double Time / Half Time or custom charts)."
)

uploaded = st.file_uploader("arcade-highscores.json", type="json")

if uploaded is None:
    st.info("Choose your arcade highscores file to get started.")
    st.stop()

try:
    highscores = json.loads(uploaded.getvalue().decode("utf-8"))
except json.JSONDecodeError:
    st.error("That file doesn't look like valid JSON. Make sure you're uploading arcade-highscores.json.")
    st.stop()

if "highScores" not in highscores:
    st.error("Missing `highScores` in the JSON. Is this the right file?")
    st.stop()

with st.spinner("Calculating ratings…"):
    ratings = build_ratings(highscores, DEFAULT_MAX_SCORES_PATH)

if not ratings:
    st.warning("No rated charts found. Check that your file has Classic mode scores for known charts.")
    st.stop()

ex_total, standard_total, ex_top, standard_top = get_rating_boards(ratings)

ex_col, std_col = st.columns(2)
ex_col.metric("EX Rating", f"{ex_total:.3f}")
std_col.metric("Standard Rating (w/ +2.0 Completion)", f"{standard_total + COMPLETION_BONUS:.3f}")

st.divider()

TABLE_ROW_HEIGHT = 35
TABLE_HEIGHT = (TOP_N + 1) * TABLE_ROW_HEIGHT

ex_board_col, std_board_col = st.columns(2)

with ex_board_col:
    st.subheader(f"Top {TOP_N} EX Rating")
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
    st.subheader(f"Top {TOP_N} Standard Rating")
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

st.divider()


st.download_button(
    label="Download full board (CSV)",
    data=format_rating_board_csv(ratings).encode("utf-8"),
    file_name="ex_rating_board.csv",
    mime="text/csv",
)
