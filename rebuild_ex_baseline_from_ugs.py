"""
Rebuild Full EX Rating baseline from fresh UGS Classic leaderboards + Supabase scores.

Does NOT write to Supabase. Outputs a new offline compilation:
  resources/ex_rating_rebuild_<date>/
    ex_rating_baseline.csv          — all players ranked by EX
    top_1000_player_scores.json     — chart scores for top 1000 by EX
    top_100_comparison.csv          — vs current committed baseline
    fetch_manifest.json             — UGS fetch progress
    ugs_charts/*.json               — per-chart score dumps (resume-safe)

For each (player, song, difficulty), uses max(UGS score, Supabase scores.score).
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
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

from rating.baseline_leaderboard import load_baseline_leaderboard_csv  # noqa: E402
from rating.board import competition_ranks_for_values, player_ex_rating_with_completion  # noqa: E402
from rating.chart_levels import load_chart_rating_levels  # noqa: E402
from rating.constants import (  # noqa: E402
    BASELINE_CSV_HEADERS,
    CHART_RATING_LEVELS_PATH,
    EX_RATING_BASELINE_PATH,
    TOP_SCORES_SYNC_PLAYER_COUNT,
)
from rating.imported_players import build_ratings_from_imported_player  # noqa: E402
from rating.supabase_config import get_supabase_db_url, supabase_configured  # noqa: E402
from rating.supabase_postgres import acquire_postgres_connection  # noqa: E402

PAGE_LIMIT = 1000
SPEED = "Classic"
REGION = "global"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def output_dir() -> Path:
    return PROJECT_ROOT / "resources" / f"ex_rating_rebuild_{_stamp()}"


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


def list_rateable_boards(*, min_level: int | None = None) -> list[dict]:
    levels = load_chart_rating_levels(CHART_RATING_LEVELS_PATH)
    boards: list[dict] = []
    seen: set[str] = set()
    for chart_key, level in levels.items():
        if "/" not in chart_key:
            continue
        if min_level is not None and int(level) < min_level:
            continue
        song, difficulty = chart_key.rsplit("/", 1)
        try:
            board_id = song_to_leaderboard_id(song, difficulty, SPEED, REGION)
        except ValueError:
            continue
        if board_id in seen:
            continue
        seen.add(board_id)
        boards.append(
            {
                "song": song,
                "difficulty": difficulty,
                "level": level,
                "leaderboard_id": board_id,
                "chart_key": chart_key,
            }
        )
    boards.sort(key=lambda b: (-int(b["level"]), b["chart_key"]))
    return boards


def _board_fetch_complete(
    existing: list,
    total: int | None,
    *,
    complete_flag: bool,
    per_chart_limit: int | None,
) -> bool:
    if per_chart_limit is not None and len(existing) >= per_chart_limit:
        return True
    if complete_flag:
        return True
    if total is not None and len(existing) >= total:
        return True
    return False


def fetch_board(
    board: dict,
    token: str,
    out_path: Path,
    *,
    per_chart_limit: int | None = None,
) -> tuple[str, str, str | None]:
    """Returns (status, token, error). status: complete | not_found | error"""
    existing: list = []
    total: int | None = None
    if out_path.is_file():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            existing = list(data.get("results") or [])
            total = data.get("total")
            if _board_fetch_complete(
                existing,
                total,
                complete_flag=bool(data.get("complete")),
                per_chart_limit=per_chart_limit,
            ):
                if per_chart_limit is not None and len(existing) > per_chart_limit:
                    existing = existing[:per_chart_limit]
                    payload = {
                        **board,
                        "speed": SPEED,
                        "region": REGION,
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "total": total,
                        "returned": len(existing),
                        "complete": True,
                        "per_chart_limit": per_chart_limit,
                        "results": existing,
                    }
                    out_path.write_text(json.dumps(payload), encoding="utf-8")
                return "complete", token, None
        except json.JSONDecodeError:
            existing = []

    offset = len(existing)
    try:
        while True:
            page, token = request_page(board["leaderboard_id"], token, offset)
            batch = page.get("results") or []
            if page.get("total") is not None:
                total = page.get("total")
            if not batch:
                if offset == 0:
                    # Empty leaderboard — still write a complete stub.
                    payload = {
                        **board,
                        "speed": SPEED,
                        "region": REGION,
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "total": total if total is not None else 0,
                        "returned": 0,
                        "complete": True,
                        "per_chart_limit": per_chart_limit,
                        "results": [],
                    }
                    out_path.write_text(json.dumps(payload), encoding="utf-8")
                break
            existing.extend(batch)
            if per_chart_limit is not None and len(existing) > per_chart_limit:
                existing = existing[:per_chart_limit]
            offset = len(existing)
            hit_limit = per_chart_limit is not None and len(existing) >= per_chart_limit
            complete = (
                hit_limit
                or bool(total is not None and len(existing) >= total)
                or len(batch) < PAGE_LIMIT
            )
            payload = {
                **board,
                "speed": SPEED,
                "region": REGION,
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total": total,
                "returned": len(existing),
                "complete": complete,
                "per_chart_limit": per_chart_limit,
                "results": existing,
            }
            out_path.write_text(json.dumps(payload), encoding="utf-8")
            if complete:
                break
            time.sleep(0.03)
        return "complete", token, None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "not_found", token, "Leaderboard not found"
        return "error", token, f"HTTP {exc.code}"
    except RuntimeError as exc:
        return "error", token, str(exc)


def fetch_all_ugs_charts(
    charts_dir: Path,
    manifest_path: Path,
    *,
    min_level: int | None = None,
    per_chart_limit: int | None = None,
) -> dict:
    charts_dir.mkdir(parents=True, exist_ok=True)
    boards = list_rateable_boards(min_level=min_level)
    manifest = {"boards": {}, "speed": SPEED, "region": REGION}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.setdefault("boards", {})
        except json.JSONDecodeError:
            pass
    manifest["min_level"] = min_level
    manifest["per_chart_limit"] = per_chart_limit

    token = authenticate_anonymous()
    scope = f"level>={min_level}" if min_level is not None else "all levels"
    limit_txt = f", top {per_chart_limit}/chart" if per_chart_limit is not None else ""
    print(f"UGS boards to fetch: {len(boards)} ({scope}{limit_txt})", flush=True)
    complete = skipped = not_found = failed = 0
    start = time.perf_counter()

    for i, board in enumerate(boards, 1):
        out_path = charts_dir / f"{board['leaderboard_id']}.json"
        entry = manifest["boards"].get(board["leaderboard_id"], {})
        if entry.get("status") in ("complete", "not_found") and (
            out_path.is_file() or entry.get("status") == "not_found"
        ):
            if entry.get("status") == "complete" and out_path.is_file():
                try:
                    data = json.loads(out_path.read_text(encoding="utf-8"))
                    existing = list(data.get("results") or [])
                    if _board_fetch_complete(
                        existing,
                        data.get("total"),
                        complete_flag=bool(data.get("complete")),
                        per_chart_limit=per_chart_limit,
                    ):
                        if per_chart_limit is not None and len(existing) > per_chart_limit:
                            # Old full dump: trim to requested top-N without re-fetch.
                            existing = existing[:per_chart_limit]
                            data = {
                                **board,
                                "speed": SPEED,
                                "region": REGION,
                                "fetched_at": data.get("fetched_at")
                                or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "total": data.get("total"),
                                "returned": len(existing),
                                "complete": True,
                                "per_chart_limit": per_chart_limit,
                                "results": existing,
                            }
                            out_path.write_text(json.dumps(data), encoding="utf-8")
                        skipped += 1
                        if i % 50 == 0 or i == len(boards):
                            print(f"[{i}/{len(boards)}] skipped (already complete)", flush=True)
                        continue
                except json.JSONDecodeError:
                    pass
            elif entry.get("status") == "not_found":
                skipped += 1
                continue

        print(
            f"[{i}/{len(boards)}] lv{board['level']} {board['chart_key']} ...",
            flush=True,
        )
        status, token, err = fetch_board(
            board, token, out_path, per_chart_limit=per_chart_limit
        )
        manifest["boards"][board["leaderboard_id"]] = {
            "song": board["song"],
            "difficulty": board["difficulty"],
            "level": board["level"],
            "status": status,
            "error": err,
            "file": out_path.name if status == "complete" else None,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if status == "complete":
            complete += 1
        elif status == "not_found":
            not_found += 1
        else:
            failed += 1
            print(f"  FAILED: {err}", flush=True)

    elapsed = time.perf_counter() - start
    summary = {
        "board_count": len(boards),
        "min_level": min_level,
        "per_chart_limit": per_chart_limit,
        "newly_complete": complete,
        "skipped": skipped,
        "not_found": not_found,
        "failed": failed,
        "elapsed_seconds": round(elapsed, 1),
    }
    manifest["summary"] = summary
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"\nUGS fetch done in {elapsed/60:.1f} min: "
        f"complete={complete} skipped={skipped} not_found={not_found} failed={failed}",
        flush=True,
    )
    return manifest


def build_player_scores_from_charts(charts_dir: Path) -> dict[str, dict]:
    """player_id -> {playerId, playerName, scores: [...]}"""
    players: dict[str, dict] = {}
    chart_files = sorted(p for p in charts_dir.glob("*.json") if p.name != "manifest.json")
    print(f"Building player scores from {len(chart_files)} chart files...", flush=True)

    for i, path in enumerate(chart_files, 1):
        data = json.loads(path.read_text(encoding="utf-8"))
        song = data.get("song")
        difficulty = data.get("difficulty")
        board_id = data.get("leaderboard_id")
        for entry in data.get("results") or []:
            pid = entry.get("playerId")
            if not pid:
                continue
            score = int(entry.get("score") or 0)
            rec = players.get(pid)
            if rec is None:
                rec = {
                    "playerId": pid,
                    "playerName": entry.get("playerName") or "",
                    "scores_by_chart": {},
                }
                players[pid] = rec
            elif entry.get("playerName") and not rec.get("playerName"):
                rec["playerName"] = entry["playerName"]

            key = (song, difficulty)
            prev = rec["scores_by_chart"].get(key)
            if prev is None or score > prev["score"]:
                rec["scores_by_chart"][key] = {
                    "leaderboard_id": board_id,
                    "song": song,
                    "difficulty": difficulty,
                    "speed": SPEED,
                    "region": REGION,
                    "rank": entry.get("rank"),
                    "rank_display": (entry.get("rank", 0) + 1) if entry.get("rank") is not None else None,
                    "score": score,
                    "source": "ugs",
                }
        if i % 50 == 0 or i == len(chart_files):
            print(f"  charts {i}/{len(chart_files)} players={len(players)}", flush=True)

    return players


def _ensure_db_url_from_secrets_toml() -> None:
    """Allow CLI runs to pick up .streamlit/secrets.toml without Streamlit."""
    if get_supabase_db_url():
        return
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.is_file():
        return
    text = secrets_path.read_text(encoding="utf-8")
    # Simple parse for db_url = "..."
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("db_url"):
            _, _, rest = line.partition("=")
            url = rest.strip().strip('"').strip("'")
            if url and "YOUR_" not in url:
                import os

                os.environ["SUPABASE_DB_URL"] = url
            break


def load_all_supabase_scores() -> dict[tuple[str, str, str], dict]:
    """(player_id, song, difficulty) -> {score, ...} taking max score if duplicates."""
    _ensure_db_url_from_secrets_toml()
    if not supabase_configured() and not get_supabase_db_url():
        print("WARNING: Supabase not configured — skipping DB score merge", flush=True)
        return {}

    print("Loading all scores from Supabase...", flush=True)
    conn = acquire_postgres_connection(get_supabase_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT player_id, song, difficulty, score, source,
                       accuracy, miss_count, max_combo, cleared, critical_count
                FROM scores
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    best: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        player_id, song, difficulty, score, source = row[0], row[1], row[2], int(row[3]), row[4]
        key = (str(player_id), str(song), str(difficulty))
        prev = best.get(key)
        if prev is None or score > prev["score"]:
            best[key] = {
                "score": score,
                "source": source,
                "accuracy": row[5],
                "miss_count": row[6],
                "max_combo": row[7],
                "cleared": row[8],
                "critical_count": row[9],
            }
    print(f"  Supabase unique chart scores: {len(best)}", flush=True)
    return best


def merge_db_scores(
    players: dict[str, dict],
    db_scores: dict[tuple[str, str, str], dict],
) -> tuple[int, int]:
    """Merge Supabase scores into player records. Returns (charts_replaced, charts_added)."""
    replaced = 0
    added = 0
    for (player_id, song, difficulty), db_row in db_scores.items():
        rec = players.get(player_id)
        if rec is None:
            rec = {
                "playerId": player_id,
                "playerName": "",
                "scores_by_chart": {},
            }
            players[player_id] = rec

        key = (song, difficulty)
        ugs = rec["scores_by_chart"].get(key)
        db_score = int(db_row["score"])
        if ugs is None:
            rec["scores_by_chart"][key] = {
                "song": song,
                "difficulty": difficulty,
                "speed": SPEED,
                "score": db_score,
                "source": f"db:{db_row.get('source')}",
                "accuracy": db_row.get("accuracy"),
                "miss_count": db_row.get("miss_count"),
                "max_combo": db_row.get("max_combo"),
                "cleared": db_row.get("cleared"),
                "critical_count": db_row.get("critical_count"),
            }
            added += 1
        elif db_score > int(ugs["score"]):
            ugs["score"] = db_score
            ugs["source"] = f"db:{db_row.get('source')}(was_ugs)"
            if db_row.get("accuracy") is not None:
                ugs["accuracy"] = db_row["accuracy"]
            if db_row.get("miss_count") is not None:
                ugs["miss_count"] = db_row["miss_count"]
            if db_row.get("max_combo") is not None:
                ugs["max_combo"] = db_row["max_combo"]
            if db_row.get("cleared") is not None:
                ugs["cleared"] = db_row["cleared"]
            if db_row.get("critical_count") is not None:
                ugs["critical_count"] = db_row["critical_count"]
            replaced += 1
    return replaced, added


def load_display_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if EX_RATING_BASELINE_PATH.is_file():
        for entry in load_baseline_leaderboard_csv(EX_RATING_BASELINE_PATH):
            names[entry.player_id] = entry.display_name
    return names


def rate_players(players: dict[str, dict], display_names: dict[str, str]) -> list[dict]:
    print(f"Rating {len(players)} players...", flush=True)
    chart_levels = load_chart_rating_levels()
    results: list[dict] = []
    for i, (pid, rec) in enumerate(players.items(), 1):
        scores = list(rec["scores_by_chart"].values())
        player_data = {"playerId": pid, "scores": scores}
        ratings = build_ratings_from_imported_player(player_data, chart_rating_levels=chart_levels)
        if not ratings:
            continue
        ex_rating = player_ex_rating_with_completion(ratings)
        display = (
            display_names.get(pid)
            or rec.get("displayName")
            or rec.get("playerName")
            or pid
        )
        results.append(
            {
                "player_id": pid,
                "display_name": display,
                "ex_rating": float(ex_rating),
                "charts_rated": len(ratings),
                "scores": scores,
            }
        )
        if i % 5000 == 0 or i == len(players):
            print(f"  rated {i}/{len(players)} kept={len(results)}", flush=True)

    results.sort(key=lambda r: (-r["ex_rating"], r["display_name"].casefold(), r["player_id"]))
    ranks = competition_ranks_for_values([r["ex_rating"] for r in results])
    for entry, rank in zip(results, ranks):
        entry["rank"] = rank
    return results


def write_baseline_csv(results: list[dict], path: Path, last_updated: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BASELINE_CSV_HEADERS)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "player_id": row["player_id"],
                    "display_name": row["display_name"],
                    "ex_rating": row["ex_rating"],
                    "last_updated": last_updated,
                }
            )


def write_top_scores(results: list[dict], path: Path, top_n: int) -> None:
    top = results[:top_n]
    payload = {
        "top_n": top_n,
        "player_count": len(top),
        "players": [
            {
                "rank": row["rank"],
                "player_id": row["player_id"],
                "display_name": row["display_name"],
                "ex_rating": row["ex_rating"],
                "charts_rated": row["charts_rated"],
                "scores": [
                    {
                        "song": s["song"],
                        "difficulty": s["difficulty"],
                        "score": s["score"],
                        "source": s.get("source"),
                    }
                    for s in row["scores"]
                ],
            }
            for row in top
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def compare_top_100(new_results: list[dict], path: Path) -> None:
    old_entries = list(load_baseline_leaderboard_csv(EX_RATING_BASELINE_PATH))
    old_by_id = {e.player_id: e for e in old_entries}
    old_ranks = competition_ranks_for_values([e.ex_rating for e in old_entries])
    old_rank_by_id = {
        e.player_id: rank for e, rank in zip(old_entries, old_ranks)
    }

    new_top = new_results[:100]
    old_top_ids = {e.player_id for e in old_entries[:100]}

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "new_rank",
                "old_rank",
                "rank_change",
                "player_id",
                "display_name",
                "new_ex_rating",
                "old_ex_rating",
                "ex_delta",
                "status",
            ],
        )
        writer.writeheader()
        for row in new_top:
            pid = row["player_id"]
            old = old_by_id.get(pid)
            old_rank = old_rank_by_id.get(pid)
            if old is None:
                status = "NEW"
                old_rating = ""
                delta = ""
                rank_change = ""
            else:
                old_rating = old.ex_rating
                delta = row["ex_rating"] - old.ex_rating
                if old_rank is None:
                    status = "ENTERED_TOP_100"
                    rank_change = ""
                else:
                    rank_change = old_rank - row["rank"]  # positive = moved up
                    if pid not in old_top_ids:
                        status = "ENTERED_TOP_100"
                    elif abs(delta) < 1e-9 and old_rank == row["rank"]:
                        status = "SAME"
                    else:
                        status = "CHANGED"
            writer.writerow(
                {
                    "new_rank": row["rank"],
                    "old_rank": old_rank if old_rank is not None else "",
                    "rank_change": rank_change,
                    "player_id": pid,
                    "display_name": row["display_name"],
                    "new_ex_rating": f"{row['ex_rating']:.6f}",
                    "old_ex_rating": f"{old_rating:.6f}" if old_rating != "" else "",
                    "ex_delta": f"{delta:.6f}" if delta != "" else "",
                    "status": status,
                }
            )

        # Players who dropped out of top 100
        new_top_ids = {r["player_id"] for r in new_top}
        for e, rank in zip(old_entries[:100], old_ranks[:100]):
            if e.player_id in new_top_ids:
                continue
            new_entry = next((r for r in new_results if r["player_id"] == e.player_id), None)
            writer.writerow(
                {
                    "new_rank": new_entry["rank"] if new_entry else "",
                    "old_rank": rank,
                    "rank_change": (rank - new_entry["rank"]) if new_entry else "",
                    "player_id": e.player_id,
                    "display_name": e.display_name,
                    "new_ex_rating": f"{new_entry['ex_rating']:.6f}" if new_entry else "",
                    "old_ex_rating": f"{e.ex_rating:.6f}",
                    "ex_delta": f"{(new_entry['ex_rating'] - e.ex_rating):.6f}" if new_entry else "",
                    "status": "DROPPED_FROM_TOP_100",
                }
            )


def main() -> int:
    import argparse

    # Windows consoles often default to cp1252; force UTF-8 for player names.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Rebuild EX baseline from UGS + Supabase")
    parser.add_argument("--skip-fetch", action="store_true", help="Reuse existing ugs_charts/")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=TOP_SCORES_SYNC_PLAYER_COUNT)
    parser.add_argument(
        "--min-level",
        type=int,
        default=None,
        help="Only fetch UGS boards for charts at this rating level or higher",
    )
    parser.add_argument(
        "--per-chart-limit",
        type=int,
        default=None,
        help="Only keep/fetch the top N scores per chart (e.g. 1000)",
    )
    parser.add_argument(
        "--seed-charts-from",
        type=Path,
        default=None,
        help="Copy ugs_charts/ from a prior rebuild before fetching (keeps charts outside --min-level)",
    )
    parser.add_argument(
        "--refetch-matching",
        action="store_true",
        help="Delete existing chart dumps for boards in this fetch scope so they are re-pulled",
    )
    args = parser.parse_args()

    out = args.output or output_dir()
    out.mkdir(parents=True, exist_ok=True)
    charts_dir = out / "ugs_charts"
    manifest_path = out / "fetch_manifest.json"

    print(f"Output: {out}", flush=True)

    if args.seed_charts_from is not None and not args.skip_fetch:
        seed = args.seed_charts_from
        seed_charts = seed / "ugs_charts" if seed.name != "ugs_charts" else seed
        if not seed_charts.is_dir():
            print(f"ERROR: --seed-charts-from has no ugs_charts/: {seed}", file=sys.stderr)
            return 1
        if charts_dir.exists():
            print(f"Seed target already has ugs_charts/; leaving in place: {charts_dir}", flush=True)
        else:
            print(f"Seeding ugs_charts/ from {seed_charts} ...", flush=True)
            shutil.copytree(seed_charts, charts_dir)
        seed_manifest = seed / "fetch_manifest.json"
        if seed_manifest.is_file() and not manifest_path.is_file():
            shutil.copy2(seed_manifest, manifest_path)

    if not args.skip_fetch:
        if args.refetch_matching:
            boards = list_rateable_boards(min_level=args.min_level)
            cleared = 0
            manifest = {"boards": {}}
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest.setdefault("boards", {})
                except json.JSONDecodeError:
                    pass
            for board in boards:
                board_id = board["leaderboard_id"]
                path = charts_dir / f"{board_id}.json"
                if path.is_file():
                    path.unlink()
                    cleared += 1
                manifest.get("boards", {}).pop(board_id, None)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(
                f"Cleared {cleared} chart dumps for refetch "
                f"(min_level={args.min_level})",
                flush=True,
            )
        fetch_all_ugs_charts(
            charts_dir,
            manifest_path,
            min_level=args.min_level,
            per_chart_limit=args.per_chart_limit,
        )
    elif not charts_dir.is_dir():
        print(f"ERROR: --skip-fetch but {charts_dir} missing", file=sys.stderr)
        return 1

    players = build_player_scores_from_charts(charts_dir)
    db_scores = load_all_supabase_scores()
    replaced, added = merge_db_scores(players, db_scores)
    print(f"DB merge: replaced_higher={replaced} added_only_in_db={added}", flush=True)

    display_names = load_display_names()
    results = rate_players(players, display_names)
    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    baseline_path = out / "ex_rating_baseline.csv"
    write_baseline_csv(results, baseline_path, last_updated)
    print(f"Wrote {len(results)} players -> {baseline_path}", flush=True)

    top_path = out / "top_1000_player_scores.json"
    write_top_scores(results, top_path, args.top_n)
    print(f"Wrote top {args.top_n} score sets -> {top_path}", flush=True)

    cmp_path = out / "top_100_comparison.csv"
    compare_top_100(results, cmp_path)
    print(f"Wrote top 100 comparison -> {cmp_path}", flush=True)

    # Quick console summary of top 100 changes
    with cmp_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    entered = [r for r in rows if r["status"] == "ENTERED_TOP_100"]
    dropped = [r for r in rows if r["status"] == "DROPPED_FROM_TOP_100"]
    newbies = [r for r in rows if r["status"] == "NEW"]
    changed = [r for r in rows if r["status"] == "CHANGED"]
    print("\n=== Top 100 summary ===")
    print(f"Changed ratings/ranks: {len(changed)}")
    print(f"Entered top 100: {len(entered)}")
    print(f"Dropped from top 100: {len(dropped)}")
    print(f"Brand new players: {len(newbies)}")
    if entered:
        print("Entered:")
        for r in entered[:15]:
            print(f"  #{r['new_rank']} {r['display_name']} (was #{r['old_rank'] or '?'})")
    if dropped:
        print("Dropped:")
        for r in dropped[:15]:
            print(f"  was #{r['old_rank']} {r['display_name']} (now #{r['new_rank'] or 'gone'})")

    # Strip scores from memory dump summary
    summary = {
        "player_count": len(results),
        "db_charts_replaced": replaced,
        "db_charts_added": added,
        "top_player": {
            "rank": results[0]["rank"],
            "display_name": results[0]["display_name"],
            "ex_rating": results[0]["ex_rating"],
        }
        if results
        else None,
        "output_dir": str(out),
    }
    (out / "rebuild_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nDone. Summary: {summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
