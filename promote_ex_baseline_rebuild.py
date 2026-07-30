"""
Promote an offline EX baseline rebuild to the live site files + Supabase.

Typical future workflow:
  1. python rebuild_ex_baseline_from_ugs.py
  2. python promote_ex_baseline_rebuild.py --rebuild-dir resources/ex_rating_rebuild_YYYYMMDD

This script:
  - Writes resources/ex_rating_baseline.csv with last_updated = now
  - Writes resources/ex_rating_baseline_meta.json (last_full_rebuild cutoff)
  - Prunes Supabase updated_ratings with last_updated <= promote time
  - Re-seeds top-1000 chart scores from top_1000_player_scores.json

Does not commit/push git. Deploy the updated baseline CSV/meta to Streamlit after promote.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def _ensure_db_url_from_secrets_toml() -> None:
    if os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL"):
        return
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.is_file():
        return
    for line in secrets_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("db_url"):
            _, _, rest = line.partition("=")
            url = rest.strip().strip('"').strip("'")
            if url and "YOUR_" not in url:
                os.environ["SUPABASE_DB_URL"] = url
            break


from rating.baseline_leaderboard import (  # noqa: E402
    BaselineLeaderboardEntry,
    BaselineMeta,
    load_baseline_leaderboard_csv,
    utc_now_iso,
    write_baseline_leaderboard_csv,
    write_baseline_meta,
    write_baseline_top_scores_from_rebuild,
)
from rating.constants import (  # noqa: E402
    EX_RATING_BASELINE_META_PATH,
    EX_RATING_BASELINE_PATH,
    EX_RATING_BASELINE_TOP_SCORES_PATH,
    SCORE_SOURCE_SEED,
)
from rating.public_leaderboard import (  # noqa: E402
    load_ex_leaderboard,
    merge_baseline_with_updated_ratings,
    rank_leaderboard_entries,
)
from rating.supabase_leaderboard import (  # noqa: E402
    load_updated_ratings_from_supabase,
    prune_updated_ratings_at_or_before,
    sync_top_scores_payload_to_supabase,
)


def _load_rebuild_baseline(rebuild_dir: Path) -> list[BaselineLeaderboardEntry]:
    path = rebuild_dir / "ex_rating_baseline.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Missing rebuild baseline: {path}")
    entries = load_baseline_leaderboard_csv(path)
    if not entries:
        raise RuntimeError(f"Rebuild baseline is empty: {path}")
    return entries


def _load_top_score_rows(rebuild_dir: Path) -> list[tuple[str, str, str, int]]:
    path = rebuild_dir / "top_1000_player_scores.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing top scores file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str, int]] = []
    for player in payload.get("players") or []:
        player_id = str(player.get("player_id") or "").strip()
        if not player_id:
            continue
        for score in player.get("scores") or []:
            song = str(score.get("song") or "").strip()
            difficulty = str(score.get("difficulty") or "").strip()
            if not song or not difficulty:
                continue
            rows.append((player_id, song, difficulty, int(score["score"])))
    return rows


def promote(
    rebuild_dir: Path,
    *,
    skip_db: bool = False,
    skip_score_seed: bool = False,
    skip_prune: bool = False,
) -> dict:
    _ensure_db_url_from_secrets_toml()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    now = utc_now_iso()
    entries = _load_rebuild_baseline(rebuild_dir)
    stamped = [
        BaselineLeaderboardEntry(
            player_id=entry.player_id,
            display_name=entry.display_name,
            ex_rating=entry.ex_rating,
            last_updated=now,
        )
        for entry in entries
    ]

    write_baseline_leaderboard_csv(stamped, EX_RATING_BASELINE_PATH)
    write_baseline_meta(
        BaselineMeta(
            last_full_rebuild=now,
            player_count=len(stamped),
            source_rebuild_dir=str(rebuild_dir.as_posix()),
        ),
        EX_RATING_BASELINE_META_PATH,
    )
    print(f"Wrote baseline CSV ({len(stamped)} players) -> {EX_RATING_BASELINE_PATH}")
    print(f"Wrote baseline meta last_full_rebuild={now} -> {EX_RATING_BASELINE_META_PATH}")

    top_scores_path = rebuild_dir / "top_1000_player_scores.json"
    baseline_top_players = 0
    if top_scores_path.is_file():
        baseline_top_players = write_baseline_top_scores_from_rebuild(
            top_scores_path,
            EX_RATING_BASELINE_TOP_SCORES_PATH,
        )
        print(
            f"Wrote baseline top scores ({baseline_top_players} players) -> "
            f"{EX_RATING_BASELINE_TOP_SCORES_PATH}"
        )
    else:
        print(f"WARNING: missing {top_scores_path}; skipped baseline top scores export")

    pruned = 0
    seeded = {"players": 0, "scores": 0}
    if not skip_db:
        if not skip_prune:
            pruned = prune_updated_ratings_at_or_before(now)
            print(f"Pruned updated_ratings at_or_before {now}: {pruned} rows")
        else:
            print("Skipped pruning updated_ratings (--skip-prune)")

        if not skip_score_seed:
            score_rows = _load_top_score_rows(rebuild_dir)
            seeded = sync_top_scores_payload_to_supabase(
                score_rows,
                source=SCORE_SOURCE_SEED,
            )
            print(
                f"Re-seeded top scores: players={seeded['players']} "
                f"scores={seeded['scores']} source={SCORE_SOURCE_SEED}"
            )
        else:
            print("Skipped score seed (--skip-score-seed)")
    else:
        print("Skipped Supabase updates (--skip-db)")

    # Sanity: live merge should match baseline for top ranks right after promote
    overrides = {} if skip_db else load_updated_ratings_from_supabase()
    live = rank_leaderboard_entries(
        merge_baseline_with_updated_ratings(stamped, overrides)
    )
    print("\nLive top 5 after promote:")
    for entry in live[:5]:
        print(f"  #{entry.rank}  {entry.player}  {entry.ex_rating:.3f}")

    remaining_overrides = len(overrides)
    print(f"\nRemaining updated_ratings overrides: {remaining_overrides}")

    return {
        "last_full_rebuild": now,
        "player_count": len(stamped),
        "baseline_top_score_players": baseline_top_players,
        "pruned_updated_ratings": pruned,
        "seeded_players": seeded["players"],
        "seeded_scores": seeded["scores"],
        "remaining_overrides": remaining_overrides,
        "baseline_path": str(EX_RATING_BASELINE_PATH),
        "meta_path": str(EX_RATING_BASELINE_META_PATH),
        "top_scores_path": str(EX_RATING_BASELINE_TOP_SCORES_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote EX baseline rebuild to live")
    parser.add_argument(
        "--rebuild-dir",
        type=Path,
        required=True,
        help="Path to resources/ex_rating_rebuild_YYYYMMDD",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Only write baseline CSV/meta/top-scores; do not touch Supabase",
    )
    parser.add_argument(
        "--skip-prune",
        action="store_true",
        help="Keep existing updated_ratings rows (do not prune)",
    )
    parser.add_argument(
        "--skip-score-seed",
        action="store_true",
        help="Do not replace Supabase seed scores",
    )
    args = parser.parse_args()

    rebuild_dir = args.rebuild_dir
    if not rebuild_dir.is_absolute():
        rebuild_dir = PROJECT_ROOT / rebuild_dir
    if not rebuild_dir.is_dir():
        print(f"ERROR: rebuild dir not found: {rebuild_dir}", file=sys.stderr)
        return 1

    summary = promote(
        rebuild_dir,
        skip_db=args.skip_db,
        skip_score_seed=args.skip_score_seed,
        skip_prune=args.skip_prune,
    )
    print("\nPromote summary:")
    print(json.dumps(summary, indent=2))
    print(
        "\nNext: commit/push baseline CSV + meta (+ top scores) so Streamlit Cloud picks them up."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
