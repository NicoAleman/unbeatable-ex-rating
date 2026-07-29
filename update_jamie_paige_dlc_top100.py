"""Fetch top 100 UGS scores for Jamie Paige DLC charts and merge into a rebuild dir."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = PROJECT_ROOT / "unbeatable-leaderboard-tools"
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from unbeatable_leaderboard import (  # noqa: E402
    LEADERBOARDS_BASE,
    PROJECT_ID,
    authenticate_anonymous,
    song_to_leaderboard_id,
)
from rating.chart_levels import load_chart_rating_levels  # noqa: E402
from rating.constants import CHART_RATING_LEVELS_PATH  # noqa: E402

JAMIE_PAIGE_SONGS = [
    "NOT LOSING",
    "birdbrain",
    "dream diary",
    "ebichahan",
    "i wish i could fall",
    "little secret",
    "machine love",
    "my universal",
    "newly human feeling",
    "no eulogies",
    "nothing ever",
    "rot for clout",
    "sleeping in jp remix",
    "square up synthetic",
    "turn back",
    "women wrestling emoji",
]
SPEED = "Classic"
REGION = "global"
TOP_N = 100
PAGE_LIMIT = 100


def request_page(board_id: str, token: str, offset: int) -> tuple[dict, str]:
    url = (
        f"{LEADERBOARDS_BASE}/{PROJECT_ID}/leaderboards/{board_id}/scores"
        f"?offset={offset}&limit={PAGE_LIMIT}&includeMetadata=false"
    )
    for attempt in range(6):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode()), token
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            if exc.code in (401, 403) and attempt < 5:
                token = authenticate_anonymous()
                time.sleep(2)
                continue
            if exc.code == 429 and attempt < 5:
                retry = exc.headers.get("Retry-After")
                time.sleep(int(retry) if retry and str(retry).isdigit() else 10)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
    raise RuntimeError("unreachable")


def list_dlc_boards() -> list[dict]:
    levels = load_chart_rating_levels(CHART_RATING_LEVELS_PATH)
    song_set = set(JAMIE_PAIGE_SONGS)
    boards: list[dict] = []
    for chart_key, level in levels.items():
        if "/" not in chart_key:
            continue
        song, difficulty = chart_key.rsplit("/", 1)
        if song not in song_set:
            continue
        board_id = song_to_leaderboard_id(song, difficulty, SPEED, REGION)
        boards.append(
            {
                "song": song,
                "difficulty": difficulty,
                "level": level,
                "leaderboard_id": board_id,
                "chart_key": chart_key,
            }
        )
    boards.sort(key=lambda b: (b["song"].casefold(), b["difficulty"]))
    return boards


def fetch_top_n(board_id: str, token: str, top_n: int = TOP_N) -> tuple[list[dict], str, int | None]:
    results: list[dict] = []
    total: int | None = None
    offset = 0
    while len(results) < top_n:
        page, token = request_page(board_id, token, offset)
        if page.get("total") is not None:
            total = page.get("total")
        batch = page.get("results") or []
        if not batch:
            break
        results.extend(batch)
        offset = len(results)
        if len(batch) < PAGE_LIMIT:
            break
        time.sleep(0.03)
    return results[:top_n], token, total


def merge_top_into_chart_file(path: Path, board: dict, top_rows: list[dict], total: int | None) -> dict:
    existing: list[dict] = []
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = list(data.get("results") or [])
            if total is None:
                total = data.get("total")
        except json.JSONDecodeError:
            existing = []

    by_player: dict[str, dict] = {}
    for entry in existing:
        pid = entry.get("playerId")
        if not pid:
            continue
        prev = by_player.get(pid)
        if prev is None or int(entry.get("score") or 0) > int(prev.get("score") or 0):
            by_player[pid] = entry

    improved = 0
    added = 0
    for entry in top_rows:
        pid = entry.get("playerId")
        if not pid:
            continue
        score = int(entry.get("score") or 0)
        prev = by_player.get(pid)
        if prev is None:
            by_player[pid] = entry
            added += 1
        elif score > int(prev.get("score") or 0):
            by_player[pid] = entry
            improved += 1

    merged = sorted(
        by_player.values(),
        key=lambda e: (-int(e.get("score") or 0), str(e.get("playerName") or "").casefold()),
    )
    for rank, entry in enumerate(merged):
        entry["rank"] = rank

    payload = {
        **board,
        "speed": SPEED,
        "region": REGION,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total if total is not None else len(merged),
        "returned": len(merged),
        "complete": True,
        "top100_refresh": True,
        "results": merged,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {"added": added, "improved": improved, "merged_players": len(merged), "top_fetched": len(top_rows)}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    rebuild_dir = PROJECT_ROOT / "resources" / "ex_rating_rebuild_20260728"
    charts_dir = rebuild_dir / "ugs_charts"
    if not charts_dir.is_dir():
        print(f"ERROR: missing charts dir {charts_dir}", file=sys.stderr)
        return 1

    boards = list_dlc_boards()
    print(f"Jamie Paige DLC boards: {len(boards)} (top {TOP_N} each)", flush=True)
    token = authenticate_anonymous()
    summary = []

    for i, board in enumerate(boards, 1):
        board_id = board["leaderboard_id"]
        out_path = charts_dir / f"{board_id}.json"
        print(f"[{i}/{len(boards)}] {board['chart_key']} ...", flush=True)
        try:
            top_rows, token, total = fetch_top_n(board_id, token, TOP_N)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print("  404 not found", flush=True)
                summary.append({**board, "status": "not_found"})
                continue
            print(f"  ERROR HTTP {exc.code}", flush=True)
            summary.append({**board, "status": "error", "error": f"HTTP {exc.code}"})
            continue
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)
            summary.append({**board, "status": "error", "error": str(exc)})
            continue

        stats = merge_top_into_chart_file(out_path, board, top_rows, total)
        print(
            f"  fetched={stats['top_fetched']} total={total} "
            f"added={stats['added']} improved={stats['improved']} "
            f"merged_players={stats['merged_players']}",
            flush=True,
        )
        summary.append({**board, "status": "ok", **stats, "ugs_total": total})

    out_summary = rebuild_dir / "jamie_paige_top100_refresh.json"
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    ok = sum(1 for s in summary if s.get("status") == "ok")
    print(f"\nDone: {ok}/{len(boards)} boards refreshed -> {out_summary}", flush=True)
    return 0 if ok == len(boards) else 1


if __name__ == "__main__":
    raise SystemExit(main())
