"""Other Tools page for the Streamlit app."""

import streamlit as st

from bingo_board_ui import render_bingo_board
from keybind_configurator_ui import render_keybind_configurator


def render_other_tools_page() -> None:
    if "selected_tool" not in st.session_state:
        st.session_state.selected_tool = "keybind_configurator"

    selected_tool = st.session_state.selected_tool
    if selected_tool == "keybind_configurator":
        render_keybind_configurator()
    elif selected_tool == "bingo":
        render_bingo_board()
    else:
        st.warning("That tool is not available yet.")
