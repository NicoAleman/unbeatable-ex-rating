"""Keybind Configurator UI for Streamlit."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Literal

import streamlit as st

from rating.keybind_configurator import (
    DEFAULT_INPUT_BINDINGS_PATH,
    KEYBOARD_ROW_COUNT,
    KEYBOARD_ROWS,
    LaneBindingState,
    apply_lane_bindings,
    cycle_lane_binding,
    load_input_bindings_file,
    parse_lane_bindings,
    save_input_bindings_file,
    serialize_input_bindings,
)

KeybindLoadSource = Literal["manual", "auto"]

# Keyboard layout tuning — change these values to test different sizes.
KEYBOARD_MAX_WIDTH_PX = 960
KEYBOARD_HORIZONTAL_PADDING_PX = 24
KEYBOARD_KEY_HEIGHT_REM = 4
KEYBOARD_KEY_GAP_PX = 14
KEYBOARD_DOWN_COLOR = "#ff7896"
KEYBOARD_UP_COLOR = "#58d6ff"
KEYBOARD_LEGEND_ITEM_GAP_PX = 32
KEYBOARD_LEGEND_MARGIN_BOTTOM_PX = 24
# Manual / Auto source picker stacks below this viewport width.
KEYBIND_SOURCE_PICKER_STACK_MAX_PX = 640
KEYBIND_BINDING_COUNT_FONT_SIZE_REM = 1.25
# Toggle colored outlines on keybind layout containers for debugging alignment.
KEYBIND_LAYOUT_DEBUG_BORDERS = False
# Fixed width for each Auto / Manual picker section (fits longest button label on one line).
KEYBIND_SOURCE_SECTION_WIDTH_PX = 360


def _init_keybind_session_state() -> None:
    if "keybind_source_data" not in st.session_state:
        st.session_state.keybind_source_data = None
    if "keybind_baseline" not in st.session_state:
        st.session_state.keybind_baseline = {}
    if "keybind_bindings" not in st.session_state:
        st.session_state.keybind_bindings = {}
    if "keybind_loaded_file_id" not in st.session_state:
        st.session_state.keybind_loaded_file_id = None
    if "keybind_load_source" not in st.session_state:
        st.session_state.keybind_load_source = None
    if "keybind_source_path" not in st.session_state:
        st.session_state.keybind_source_path = None


def _clear_keybind_config() -> None:
    st.session_state.keybind_source_data = None
    st.session_state.keybind_baseline = {}
    st.session_state.keybind_bindings = {}
    st.session_state.keybind_loaded_file_id = None
    st.session_state.keybind_load_source = None
    st.session_state.keybind_source_path = None


def _pick_input_bindings_file() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    initial_dir = DEFAULT_INPUT_BINDINGS_PATH.parent
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    selected = filedialog.askopenfilename(
        parent=root,
        title="Select Input-Bindings.json",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        initialdir=str(initial_dir if initial_dir.exists() else Path.home()),
        initialfile="Input-Bindings.json",
    )
    root.destroy()
    return Path(selected) if selected else None


def _load_keybind_from_path(path: Path, *, source: KeybindLoadSource) -> None:
    try:
        data = load_input_bindings_file(path)
    except (OSError, json.JSONDecodeError) as error:
        st.error(f"Could not load file: {error}")
        return

    try:
        parse_lane_bindings(data)
    except (KeyError, json.JSONDecodeError, TypeError, ValueError) as error:
        st.error(f"Could not read lane bindings from that file: {error}")
        return

    file_id = f"{source}:{path}"
    _load_keybind_file(
        data,
        file_id=file_id,
        source=source,
        source_path=path,
    )
    st.rerun()


def _load_keybind_file(
    data: dict[str, str],
    *,
    file_id: str,
    source: KeybindLoadSource,
    source_path: Path | None = None,
) -> None:
    bindings = parse_lane_bindings(data)
    st.session_state.keybind_source_data = data
    st.session_state.keybind_baseline = dict(bindings)
    st.session_state.keybind_bindings = dict(bindings)
    st.session_state.keybind_loaded_file_id = file_id
    st.session_state.keybind_load_source = source
    st.session_state.keybind_source_path = str(source_path) if source_path is not None else None


def _keyboard_row_weights(
    key_count: int,
    *,
    top_row_offset: bool = False,
) -> tuple[list[float], float, float]:
    left_pad = (KEYBOARD_ROW_COUNT - key_count) / 2.0
    if top_row_offset:
        left_pad -= 0.5
    if left_pad < 0:
        left_pad = 0.0
    right_pad = KEYBOARD_ROW_COUNT - left_pad - key_count
    if right_pad < 0:
        right_pad = 0.0
    weights: list[float] = []
    if left_pad > 0:
        weights.append(left_pad)
    weights.extend([1.0] * key_count)
    if right_pad > 0:
        weights.append(right_pad)
    return weights, left_pad, right_pad


def build_keybind_keyboard_layout_css() -> str:
    """Layout-only CSS for the key overlay pattern (colors use inline HTML)."""
    height = KEYBOARD_KEY_HEIGHT_REM
    gap = KEYBOARD_KEY_GAP_PX
    return f"""
    div[class*="st-key-kbcol_"] {{
        position: relative !important;
        min-height: {height}rem !important;
        min-width: 0 !important;
    }}
    div[class*="st-key-kbcol_"] [data-testid="stMarkdownContainer"] {{
        position: absolute !important;
        inset: 0 !important;
        z-index: 1 !important;
        pointer-events: none !important;
        margin: 0 !important;
    }}
    div[class*="st-key-kbcol_"] [data-testid="stMarkdownContainer"] p {{
        margin: 0 !important;
        height: 100% !important;
    }}
    div[class*="st-key-kbcol_"] [data-testid="stButton"] {{
        position: absolute !important;
        inset: 0 !important;
        z-index: 2 !important;
        margin: 0 !important;
        width: 100% !important;
    }}
    div[class*="st-key-kbcol_"] [data-testid="stButton"] button {{
        width: 100% !important;
        height: 100% !important;
        min-height: {height}rem !important;
        opacity: 0 !important;
        cursor: pointer !important;
    }}
    .st-key-keybind-keyboard [class*="st-key-kb-row-"] [data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: {gap}px !important;
        width: 100% !important;
        min-width: 0 !important;
    }}
    .st-key-keybind-keyboard [class*="st-key-kb-row-"] [data-testid="column"] {{
        min-width: 0 !important;
    }}
    .st-key-keybind-keyboard [class*="st-key-kb-row-"] {{
        margin-bottom: {gap}px !important;
    }}
    .st-key-keybind-keyboard [class*="st-key-kb-row-"]:last-child {{
        margin-bottom: 0 !important;
    }}
    """


def build_keybind_layout_debug_css() -> str:
    if not KEYBIND_LAYOUT_DEBUG_BORDERS:
        return ""
    return """
    .st-key-keybind-workspace {
        outline: 2px solid #ff4d4d !important;
        outline-offset: 2px;
    }
    .st-key-keybind-legend {
        outline: 2px solid #4dff88 !important;
        outline-offset: 2px;
    }
    .st-key-keybind-keyboard {
        outline: 2px solid #ffb84d !important;
        outline-offset: 2px;
    }
    .st-key-keybind-action-row {
        outline: 2px solid #ffe14d !important;
        outline-offset: 2px;
    }
    .st-key-keybind-source-picker,
    .st-key-keybind-source-loaded {
        outline: 2px solid #4dd2ff !important;
        outline-offset: 2px;
    }
    .st-key-keybind-action-row [data-testid="column"]:nth-child(1) {
        outline: 1px dashed #ffe14d !important;
    }
    .st-key-keybind-action-row [data-testid="column"]:nth-child(2) {
        outline: 1px dashed #fff !important;
    }
    .st-key-keybind-action-row [data-testid="column"]:nth-child(3) {
        outline: 1px dashed #ffe14d !important;
    }
    .st-key-tools-page-nav {
        outline: 2px solid #d64dff !important;
        outline-offset: 2px;
    }
    .st-key-tool-picker {
        outline: 2px solid #ff66b2 !important;
        outline-offset: 2px;
    }
    .st-key-page-header-row {
        outline: 2px solid #a98bff !important;
        outline-offset: 2px;
    }
    """


def build_keybind_source_loaded_css() -> str:
    width = KEYBIND_SOURCE_SECTION_WIDTH_PX
    return f"""
    .st-key-keybind-source-loaded {{
        width: {width}px !important;
        max-width: min(100%, {width}px) !important;
        margin: 0.75rem auto 1.25rem auto !important;
        box-sizing: border-box !important;
    }}
    .st-key-keybind-source-loaded [data-testid="stVerticalBlock"],
    .st-key-keybind-source-loaded [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100% !important;
        max-width: 100% !important;
        align-items: center !important;
        box-sizing: border-box !important;
    }}
    .st-key-keybind-source-loaded [data-testid="stMarkdownContainer"] {{
        width: 100% !important;
        text-align: center !important;
    }}
    .st-key-keybind-source-loaded [data-testid="stButton"] {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    .st-key-keybind-source-loaded [data-testid="stButton"] button {{
        width: 100% !important;
    }}
    """


def build_keybind_workspace_css() -> str:
    max_width = KEYBOARD_MAX_WIDTH_PX
    padding = KEYBOARD_HORIZONTAL_PADDING_PX
    return f"""
    .st-key-keybind-workspace {{
        width: 100% !important;
        max-width: {max_width}px !important;
        margin: 0 auto !important;
        padding: 0 {padding}px !important;
        box-sizing: border-box !important;
    }}
    .st-key-keybind-workspace .st-key-keybind-keyboard {{
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-keybind-workspace .st-key-keybind-keyboard [data-testid="stVerticalBlock"],
    .st-key-keybind-workspace .st-key-keybind-keyboard [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100% !important;
        max-width: 100% !important;
        align-items: stretch !important;
    }}
    .st-key-keybind-workspace .st-key-keybind-action-row {{
        width: 100% !important;
        max-width: 100% !important;
        margin: 0.75rem 0 0 0 !important;
        padding: 0 !important;
        align-self: stretch !important;
    }}
    .st-key-keybind-workspace .st-key-keybind-legend {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    .st-key-keybind-workspace [data-testid="stVerticalBlock"] {{
        align-items: stretch !important;
        width: 100% !important;
    }}
    """


def build_keybind_action_row_css() -> str:
    size = KEYBIND_BINDING_COUNT_FONT_SIZE_REM
    down_color = KEYBOARD_DOWN_COLOR
    up_color = KEYBOARD_UP_COLOR
    controls = ".st-key-keybind-action-controls"
    return f"""
    .st-key-keybind-action-row {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    .st-key-keybind-action-row [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-keybind-action-row [data-testid="stVerticalBlock"] {{
        width: 100% !important;
        max-width: 100% !important;
        align-items: stretch !important;
        gap: 0 !important;
    }}
    {controls} {{
        width: 100% !important;
        max-width: 100% !important;
        position: relative !important;
    }}
    {controls} [data-testid="stVerticalBlockBorderWrapper"],
    {controls} [data-testid="stVerticalBlock"] {{
        width: 100% !important;
        max-width: 100% !important;
        align-items: stretch !important;
        gap: 0 !important;
    }}
    {controls} [data-testid="stVerticalBlock"] > .element-container:not(:has(.keybind-action-counts-layer)) {{
        width: 100% !important;
        max-width: 100% !important;
        align-self: stretch !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    {controls} [data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
    }}
    {controls} [data-testid="column"] {{
        padding: 0 !important;
        margin: 0 !important;
    }}
    {controls} [data-testid="column"]:first-child {{
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: max-content !important;
        max-width: none !important;
    }}
    {controls} [data-testid="column"]:nth-child(2) {{
        flex: 1 1 0 !important;
        min-width: 0 !important;
        width: auto !important;
    }}
    {controls} [data-testid="column"]:last-child {{
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: max-content !important;
        max-width: none !important;
        display: flex !important;
        justify-content: flex-end !important;
        align-items: center !important;
        overflow: visible !important;
    }}
    {controls} [data-testid="column"]:first-child [data-testid="stVerticalBlock"] {{
        width: auto !important;
        align-items: flex-start !important;
        padding: 0 !important;
        margin: 0 !important;
        gap: 0 !important;
    }}
    {controls} [data-testid="column"]:last-child [data-testid="stVerticalBlock"] {{
        width: auto !important;
        align-items: flex-end !important;
        padding: 0 !important;
        margin: 0 !important;
        gap: 0 !important;
        overflow: visible !important;
    }}
    {controls} [data-testid="stButton"],
    {controls} [data-testid="stDownloadButton"] {{
        width: auto !important;
        max-width: none !important;
        flex-shrink: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    {controls} [data-testid="stButton"] button,
    {controls} [data-testid="stDownloadButton"] button {{
        width: auto !important;
        max-width: none !important;
        white-space: nowrap !important;
        margin: 0 !important;
    }}
    {controls} .element-container:has(.keybind-action-counts-layer) {{
        position: absolute !important;
        left: 0 !important;
        right: 0 !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        width: 100% !important;
        height: auto !important;
        overflow: visible !important;
        pointer-events: none !important;
        z-index: 1 !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    {controls} [data-testid="stMarkdownContainer"]:has(.keybind-action-counts-layer) {{
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        text-align: center !important;
    }}
    {controls} [data-testid="stMarkdownContainer"] {{
        width: auto !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    {controls} [data-testid="stMarkdownContainer"] p {{
        margin: 0 !important;
    }}
    {controls} .keybind-binding-counts {{
        display: block;
        margin: 0;
        text-align: center;
        white-space: nowrap;
        font-size: {size}rem;
        font-weight: 600;
        line-height: 1.4;
        color: rgba(250, 250, 250, 0.88);
    }}
    {controls} .keybind-count-down {{
        color: {down_color};
    }}
    {controls} .keybind-count-up {{
        color: {up_color};
    }}
    .st-key-keybind-action-feedback,
    .st-key-keybind-action-feedback [data-testid="stVerticalBlock"],
    .st-key-keybind-action-feedback [data-testid="stVerticalBlockBorderWrapper"] {{
        width: 100% !important;
        max-width: 100% !important;
        align-items: center !important;
        gap: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-keybind-action-feedback [data-testid="stAlert"] {{
        width: fit-content !important;
        max-width: 100% !important;
        margin: 0.5rem auto 0 auto !important;
    }}
    """


def _key_visual_html(label: str, binding: LaneBindingState) -> str:
    if binding == "down":
        style = (
            "background-color:rgba(220,58,88,0.92);color:#f5f5f5;"
            "border:1px solid rgba(255,120,150,0.65);"
        )
    elif binding == "up":
        style = (
            "background-color:rgba(42,130,228,0.92);color:#f5f5f5;"
            "border:1px solid rgba(88,214,255,0.65);"
        )
    else:
        style = (
            "background-color:rgba(14,17,23,0.35);color:inherit;"
            "border:1px solid rgba(250,250,250,0.22);"
        )
    safe_label = html.escape(label)
    return (
        f'<div class="kb-key-visual" style="{style}border-radius:0.35rem;'
        f"width:100%;height:100%;min-height:{KEYBOARD_KEY_HEIGHT_REM}rem;display:flex;"
        'align-items:center;justify-content:center;font-weight:700;">'
        f"{safe_label}</div>"
    )


def _cycle_keybind(key_code: int) -> None:
    bindings = dict(st.session_state.keybind_bindings)
    bindings[key_code] = cycle_lane_binding(bindings.get(key_code))
    if bindings[key_code] is None:
        bindings.pop(key_code, None)
    st.session_state.keybind_bindings = bindings


def _render_key_button(label: str, key_code: int, binding: LaneBindingState) -> None:
    with st.container(key=f"kbcol_{key_code}"):
        st.markdown(_key_visual_html(label, binding), unsafe_allow_html=True)
        st.button(
            label,
            key=f"kb_{key_code}",
            on_click=_cycle_keybind,
            args=(key_code,),
            use_container_width=True,
            type="secondary",
        )


def _render_keyboard_row(
    row: list[tuple[str, int]],
    *,
    row_index: int,
    bindings: dict[int, LaneBindingState],
) -> None:
    weights, left_pad, right_pad = _keyboard_row_weights(
        len(row),
        top_row_offset=row_index == 0,
    )
    columns = st.columns(weights)
    start = 1 if left_pad > 0 else 0
    end = len(columns) if right_pad <= 0 else -1

    for column, (label, key_code) in zip(columns[start:end], row, strict=True):
        with column:
            _render_key_button(label, key_code, bindings.get(key_code))


def _render_action_row(
    bindings: dict[int, LaneBindingState],
    baseline: dict[int, LaneBindingState],
    *,
    has_changes: bool,
    source_data: dict[str, str],
) -> None:
    down_count = sum(1 for value in bindings.values() if value == "down")
    up_count = sum(1 for value in bindings.values() if value == "up")
    counts_html = (
        f'<div class="keybind-action-counts-layer">'
        f'<div class="keybind-binding-counts">'
        f'<span class="keybind-count-down">{down_count} Down</span>'
        f" · "
        f'<span class="keybind-count-up">{up_count} Up</span>'
        f"</div></div>"
    )
    output_data = apply_lane_bindings(source_data, bindings)
    source_path_raw = st.session_state.keybind_source_path
    save_error: str | None = None
    save_success: str | None = None

    with st.container(key="keybind-action-row"):
        with st.container(key="keybind-action-controls"):
            st.markdown(counts_html, unsafe_allow_html=True)
            discard_col, _spacer_col, save_col = st.columns(
                [4, 2, 1.35],
                vertical_alignment="center",
                gap="small",
            )
            with discard_col:
                if st.button("Discard Changes", key="keybind-discard", disabled=not has_changes):
                    st.session_state.keybind_bindings = dict(baseline)
                    st.rerun()
            with save_col:
                if source_path_raw:
                    source_path = Path(source_path_raw)
                    if st.button("Save Input-Bindings.json", key="keybind-save"):
                        try:
                            save_input_bindings_file(source_path, output_data)
                        except OSError as error:
                            save_error = f"Could not save file: {error}"
                        else:
                            st.session_state.keybind_baseline = dict(bindings)
                            save_success = f"Saved to `{source_path}`"
                else:
                    st.download_button(
                        "Download Input-Bindings.json",
                        data=serialize_input_bindings(output_data),
                        file_name="Input-Bindings.json",
                        mime="application/json",
                        key="keybind-download",
                    )

        if save_error or save_success:
            with st.container(key="keybind-action-feedback"):
                if save_error:
                    st.error(save_error)
                else:
                    st.success(save_success)


def _render_keyboard_grid(bindings: dict[int, LaneBindingState]) -> None:
    with st.container(key="keybind-keyboard"):
        for row_index, row in enumerate(KEYBOARD_ROWS):
            row_container = st.container(key=f"kb-row-{row_index}")
            with row_container:
                _render_keyboard_row(row, row_index=row_index, bindings=bindings)


def _render_source_divider() -> None:
    st.markdown(
        """
        <div class="keybind-source-divider-wrap">
            <div class="keybind-source-divider--vertical" aria-hidden="true"></div>
            <div class="keybind-source-divider--horizontal" aria-hidden="true"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_source_section_label(label: str) -> None:
    safe_label = html.escape(label)
    st.markdown(
        f'<div class="keybind-source-label"><strong>{safe_label}</strong></div>',
        unsafe_allow_html=True,
    )


def _render_manual_source_section(*, show_only: bool) -> None:
    _render_source_section_label("Manual")

    if show_only:
        source_path = st.session_state.keybind_source_path
        if source_path:
            st.caption(f"Loaded from `{source_path}`")
        if st.button(
            "Discard Selected Configuration",
            key="keybind-discard-manual",
            use_container_width=True,
        ):
            _clear_keybind_config()
            st.rerun()
        return

    if st.button(
        "Select Input-Bindings.json",
        key="keybind-manual-select",
    ):
        path = _pick_input_bindings_file()
        if path is None:
            st.warning("No file selected.")
        else:
            _load_keybind_from_path(path, source="manual")


def _render_auto_source_section(*, show_only: bool) -> None:
    _render_source_section_label("Auto")
    local_exists = DEFAULT_INPUT_BINDINGS_PATH.exists()
    load_source = st.session_state.keybind_load_source

    if load_source == "auto":
        if st.button(
            "Discard Detected Configuration",
            key="keybind-discard-detected",
            use_container_width=True,
        ):
            _clear_keybind_config()
            st.rerun()
    elif local_exists:
        if st.button(
            "Detect Local Configuration",
            key="keybind-auto-detect",
        ):
            _load_keybind_from_path(DEFAULT_INPUT_BINDINGS_PATH, source="auto")
    elif not show_only:
        st.caption("Local Input-Bindings.json was not found.")


def _render_source_picker() -> None:
    load_source = st.session_state.keybind_load_source

    if load_source is None:
        with st.container(key="keybind-source-picker"):
            auto_col, divider_col, manual_col = st.columns([1, 0.06, 1], gap="small")
            with auto_col:
                _render_auto_source_section(show_only=False)
            with divider_col:
                _render_source_divider()
            with manual_col:
                _render_manual_source_section(show_only=False)
    elif load_source == "manual":
        with st.container(key="keybind-source-loaded"):
            _render_manual_source_section(show_only=True)
    else:
        with st.container(key="keybind-source-loaded"):
            _render_auto_source_section(show_only=True)


def render_keybind_configurator() -> None:
    _init_keybind_session_state()

    st.subheader("Keybind Configurator")
    st.markdown(
        "Configure extra **Up** and **Down** lane keys for UNBEATABLE by editing "
        "`Input-Bindings.json`. Saved changes are written back to the file you loaded.\n\n"
        "On Windows, this file is usually at "
        r"`C:\Users\<YourName>\AppData\LocalLow\D-CELL GAMES\UNBEATABLE\SYSTEM\Input-Bindings.json`."
    )
    st.caption("Click a key to cycle: Unbound → Down (Red) → Up (Blue) → Unbound.")

    _render_source_picker()

    if st.session_state.keybind_source_data is None:
        st.info("Choose Detect Local Configuration or Manual upload to begin.")
        return

    bindings: dict[int, LaneBindingState] = dict(st.session_state.keybind_bindings)
    baseline: dict[int, LaneBindingState] = dict(st.session_state.keybind_baseline)
    has_changes = bindings != baseline

    with st.container(key="keybind-workspace"):
        with st.container(key="keybind-legend"):
            st.markdown(
                f"""
                <div class="keybind-legend">
                    <span style="color:{KEYBOARD_DOWN_COLOR}; font-weight: 600;">
                        Down — Red
                    </span>
                    <span style="color:{KEYBOARD_UP_COLOR}; font-weight: 600;">
                        Up — Blue
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        _render_keyboard_grid(bindings)
        _render_action_row(
            bindings,
            baseline,
            has_changes=has_changes,
            source_data=st.session_state.keybind_source_data,
        )
