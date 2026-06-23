import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path

from rating.constants import (
    GOOGLE_SHEET_APPROVED_TAB,
    GOOGLE_SHEET_ID,
    SHARED_EX_RANKINGS_PATH,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%B %d, %Y",
    "%b %d, %Y",
)


@dataclass
class SharedExRanking:
    player: str
    ex_rating: float
    last_updated: str


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


def format_date_added(date_added: str | None) -> str:
    return format_last_updated(date_added)


def _normalize_date_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _csv_value(row: dict[str, str | None], *header_names: str) -> str:
    normalized = {(key or "").strip().lower(): value for key, value in row.items()}
    for name in header_names:
        value = normalized.get(name.strip().lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _csv_date_value(row: dict[str, str | None]) -> str:
    direct = _csv_value(row, "Last Updated", "Date Added", "last updated", "date added")
    if direct:
        return direct
    for key, value in row.items():
        if not key or value is None:
            continue
        key_lower = key.strip().lower()
        if "updated" in key_lower or "added" in key_lower or key_lower == "date":
            text = str(value).strip()
            if text:
                return text
    return ""


def _sheet_csv_url(tab_name: str) -> str:
    query = urllib.parse.urlencode({"tqx": "out:csv", "sheet": tab_name})
    return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/gviz/tq?{query}"


def _fetch_sheet_csv(tab_name: str) -> str:
    request = urllib.request.Request(_sheet_csv_url(tab_name), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8-sig")


def _parse_rankings_csv(csv_text: str) -> list[SharedExRanking]:
    rankings: list[SharedExRanking] = []
    for row in csv.DictReader(StringIO(csv_text)):
        player = _csv_value(row, "Player")
        if not player:
            continue
        ex_rating = _csv_value(row, "EX Rating")
        if not ex_rating:
            continue
        rankings.append(
            SharedExRanking(
                player=player,
                ex_rating=float(ex_rating),
                last_updated=_csv_date_value(row),
            )
        )
    return sorted(rankings, key=lambda ranking: ranking.ex_rating, reverse=True)


def _load_shared_ex_rankings_from_json(path: Path = SHARED_EX_RANKINGS_PATH) -> list[SharedExRanking]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rankings = [
        SharedExRanking(
            player=entry["player"],
            ex_rating=float(entry["ex_rating"]),
            last_updated=_normalize_date_value(entry.get("last_updated") or entry.get("date_added")),
        )
        for entry in data.get("rankings", [])
    ]
    return sorted(rankings, key=lambda ranking: ranking.ex_rating, reverse=True)


def load_shared_ex_rankings() -> list[SharedExRanking]:
    try:
        return _parse_rankings_csv(_fetch_sheet_csv(GOOGLE_SHEET_APPROVED_TAB))
    except (OSError, urllib.error.URLError, ValueError, KeyError):
        if SHARED_EX_RANKINGS_PATH.exists():
            return _load_shared_ex_rankings_from_json()
        raise
