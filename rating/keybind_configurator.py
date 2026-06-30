"""Parse and rewrite UNBEATABLE Input-Bindings.json lane keybinds."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Literal

from rating.constants import PROJECT_ROOT, REWIRED_KEYBOARD_IDENTIFIERS_PATH

LaneBinding = Literal["down", "up"]
LaneBindingState = LaneBinding | None

GAMEPLAY_MAP_KEY = (
    "playerId=0|dataType=ControllerMap|kv=0|controllerMapType=0|categoryId=1|"
    "layoutId=5|hardwareGuid=ae4830f9-63db-4d4c-90b3-1beb46ecaf49"
)
ACTION_ID_DOWN = 4
ACTION_ID_UP = 2
LANE_ACTION_IDS = {ACTION_ID_DOWN, ACTION_ID_UP}

DEFAULT_INPUT_BINDINGS_PATH = (
    Path.home() / "AppData" / "LocalLow" / "D-CELL GAMES" / "UNBEATABLE" / "SYSTEM" / "Input-Bindings.json"
)

# US QWERTY rows: (display label, Rewired/Unity key code). Omits `, \\, and Space.
KEYBOARD_ROW_COUNT = 12
KEYBOARD_ROWS: list[list[tuple[str, int]]] = [
    [("1", 49), ("2", 50), ("3", 51), ("4", 52), ("5", 53), ("6", 54), ("7", 55), ("8", 56), ("9", 57), ("0", 48), ("-", 45), ("=", 61)],
    [("Q", 113), ("W", 119), ("E", 101), ("R", 114), ("T", 116), ("Y", 121), ("U", 117), ("I", 105), ("O", 111), ("P", 112), ("[", 91), ("]", 93)],
    [("A", 97), ("S", 115), ("D", 100), ("F", 102), ("G", 103), ("H", 104), ("J", 106), ("K", 107), ("L", 108), (";", 59), ("'", 39)],
    [("Z", 122), ("X", 120), ("C", 99), ("V", 118), ("B", 98), ("N", 110), ("M", 109), (",", 44), (".", 46), ("/", 47)],
]


def load_rewired_keyboard_identifiers(
    csv_path: Path = REWIRED_KEYBOARD_IDENTIFIERS_PATH,
) -> dict[int, int]:
    """Map keyboard key codes to Rewired element identifier ids."""
    lines = [
        line
        for line in csv_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    reader = csv.DictReader(StringIO("\n".join(lines)))
    mapping: dict[int, int] = {}
    for row in reader:
        element_id = int(row["Element Identifier Id"])
        key_code = int(row["KeyCode value"])
        if key_code <= 0:
            continue
        mapping[key_code] = element_id
    return mapping


def parse_lane_bindings(data: dict[str, str]) -> dict[int, LaneBindingState]:
    """Read up/down lane bindings from the active gameplay controller map."""
    raw_map = data.get(GAMEPLAY_MAP_KEY)
    if not raw_map:
        return {}

    controller_map = json.loads(raw_map)
    bindings: dict[int, LaneBindingState] = {}
    for entry in controller_map.get("buttonMaps", []):
        action_id = entry.get("actionId")
        if action_id not in LANE_ACTION_IDS:
            continue
        key_code = int(entry.get("keyboardKeyCode", 0))
        if key_code <= 0:
            continue
        bindings[key_code] = "down" if action_id == ACTION_ID_DOWN else "up"
    return bindings


def _lane_button_map_entry(
    *,
    action_id: int,
    key_code: int,
    element_identifier_id: int,
) -> dict[str, object]:
    return {
        "actionCategoryId": -1,
        "actionId": action_id,
        "elementType": 1,
        "elementIdentifierId": element_identifier_id,
        "axisRange": 0,
        "invert": False,
        "axisContribution": 0,
        "keyboardKeyCode": key_code,
        "modifierKey1": 0,
        "modifierKey2": 0,
        "modifierKey3": 0,
        "enabled": True,
    }


def apply_lane_bindings(
    data: dict[str, str],
    bindings: dict[int, LaneBindingState],
    *,
    identifiers_csv: Path = REWIRED_KEYBOARD_IDENTIFIERS_PATH,
) -> dict[str, str]:
    """Return a copy of the bindings file with lane keybinds replaced."""
    if GAMEPLAY_MAP_KEY not in data:
        raise KeyError("Gameplay controller map not found in Input-Bindings.json")

    identifier_by_keycode = load_rewired_keyboard_identifiers(identifiers_csv)
    updated = dict(data)
    controller_map = json.loads(updated[GAMEPLAY_MAP_KEY])

    kept_maps = [
        entry
        for entry in controller_map.get("buttonMaps", [])
        if entry.get("actionId") not in LANE_ACTION_IDS
    ]

    new_lane_maps: list[dict[str, object]] = []
    for key_code, binding in sorted(bindings.items(), key=lambda item: item[0]):
        if binding is None:
            continue
        action_id = ACTION_ID_DOWN if binding == "down" else ACTION_ID_UP
        element_id = identifier_by_keycode.get(key_code, 0)
        new_lane_maps.append(
            _lane_button_map_entry(
                action_id=action_id,
                key_code=key_code,
                element_identifier_id=element_id,
            )
        )

    controller_map["buttonMaps"] = kept_maps + new_lane_maps
    updated[GAMEPLAY_MAP_KEY] = json.dumps(controller_map, separators=(",", ":"))
    return updated


def serialize_input_bindings(data: dict[str, str]) -> str:
    return json.dumps(data, separators=(",", ":"))


def save_input_bindings_file(path: Path, data: dict[str, str]) -> None:
    path.write_text(serialize_input_bindings(data), encoding="utf-8")


def load_input_bindings_file(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def cycle_lane_binding(current: LaneBindingState) -> LaneBindingState:
    if current is None:
        return "down"
    if current == "down":
        return "up"
    return None
