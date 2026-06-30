"""Other Tools page for the Streamlit app."""

import streamlit as st

from keybind_configurator_ui import render_keybind_configurator

TOOLS = {
    "keybind_configurator": "Keybind Configurator",
}


def render_other_tools_page() -> None:
    if "selected_tool" not in st.session_state:
        st.session_state.selected_tool = "keybind_configurator"

    with st.container(key="tools-page-nav"):
        with st.container(key="tool-picker", horizontal=True, gap="small"):
            for tool_id, label in TOOLS.items():
                button_type = "primary" if st.session_state.selected_tool == tool_id else "secondary"
                if st.button(
                    label,
                    key=f"tool-select-{tool_id}",
                    type=button_type,
                ):
                    st.session_state.selected_tool = tool_id
                    st.rerun()

        st.divider()

    selected_tool = st.session_state.selected_tool
    if selected_tool == "keybind_configurator":
        render_keybind_configurator()
    else:
        st.warning("That tool is not available yet.")
