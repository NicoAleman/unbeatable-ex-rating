"""Helpers for reading and filtering arcade highscore entries."""


def chart_key(song: str) -> str:
    """WORNOUTTAPES/Star\\Classic -> WORNOUTTAPES/Star"""
    return song.rsplit("\\", 1)[0]


def split_chart_key(chart_key: str) -> tuple[str, str]:
    """WORNOUTTAPES/Star -> (WORNOUTTAPES, Star)"""
    song, difficulty = chart_key.rsplit("/", 1)
    return song, difficulty


def is_classic_entry(entry: dict) -> bool:
    song = entry.get("song", "")
    return song.endswith("\\Classic") and not song.split("/")[0].startswith("CUSTOM_")


def note_count(entry: dict, timing: str) -> int:
    for note in entry.get("notes", []):
        if note.get("timing") == timing:
            return note.get("count", 0)
    return 0


def miss_count(entry: dict) -> int:
    return note_count(entry, "Miss")


def critical_count(entry: dict) -> int:
    return note_count(entry, "Critical")
