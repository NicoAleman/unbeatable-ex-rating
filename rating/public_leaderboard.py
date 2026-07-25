from datetime import datetime

from rating.board import competition_ranks_for_values
from rating.baseline_leaderboard import (
    BaselineLeaderboardEntry,
    UpdatedRating,
    load_baseline_leaderboard_csv,
    load_baseline_rebuild_cutoff,
    parse_iso_timestamp,
)
from rating.constants import EX_RATING_BASELINE_PATH
from rating.ex_leaderboard_db import ExLeaderboardEntry
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import load_updated_ratings_from_supabase


def should_apply_updated_rating(
    baseline_rating: float,
    override: UpdatedRating,
    *,
    rebuild_cutoff: datetime | None = None,
) -> bool:
    """Decide whether a Supabase override should replace the baseline rating.

    After a full baseline rebuild:
    - Overrides with last_updated **after** the rebuild timestamp always apply
      (new submissions since the rebuild).
    - Older overrides apply only when they are **strictly greater** than baseline.
      If baseline is greater or equal, the rebuilt baseline wins.
    """
    override_ts = parse_iso_timestamp(override.last_updated)
    if (
        rebuild_cutoff is not None
        and override_ts is not None
        and override_ts > rebuild_cutoff
    ):
        return True
    return override.ex_rating > baseline_rating


def merge_baseline_with_updated_ratings(
    baseline: list[BaselineLeaderboardEntry],
    updated_ratings: dict[str, UpdatedRating],
    *,
    rebuild_cutoff: datetime | None = None,
) -> list[BaselineLeaderboardEntry]:
    if not updated_ratings:
        return baseline

    if rebuild_cutoff is None:
        rebuild_cutoff = load_baseline_rebuild_cutoff()

    merged: list[BaselineLeaderboardEntry] = []
    for entry in baseline:
        override = updated_ratings.get(entry.player_id)
        if override is None or not should_apply_updated_rating(
            entry.ex_rating,
            override,
            rebuild_cutoff=rebuild_cutoff,
        ):
            merged.append(entry)
            continue
        merged.append(
            BaselineLeaderboardEntry(
                player_id=entry.player_id,
                display_name=entry.display_name,
                ex_rating=override.ex_rating,
                last_updated=override.last_updated,
            )
        )
    return merged


def rank_leaderboard_entries(
    entries: list[BaselineLeaderboardEntry],
) -> list[ExLeaderboardEntry]:
    sorted_entries = sorted(
        entries,
        key=lambda entry: (-entry.ex_rating, entry.display_name.casefold()),
    )
    ranks = competition_ranks_for_values([entry.ex_rating for entry in sorted_entries])
    return [
        ExLeaderboardEntry(
            rank=rank,
            player_id=entry.player_id,
            player=entry.display_name,
            ex_rating=entry.ex_rating,
            last_updated=entry.last_updated,
        )
        for rank, entry in zip(ranks, sorted_entries, strict=True)
    ]


def player_rank_on_leaderboard(
    player_id: str,
    *,
    rating_overrides: dict[str, UpdatedRating] | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> int | None:
    """Return a player's competition rank using the same merge/rank pipeline as the UI."""
    baseline = load_baseline_leaderboard_csv(baseline_path)
    if not baseline:
        return None

    overrides = rating_overrides
    if overrides is None:
        overrides = load_updated_ratings_from_supabase() if supabase_configured() else {}

    merged = merge_baseline_with_updated_ratings(baseline, overrides)
    ranked = rank_leaderboard_entries(merged)
    for entry in ranked:
        if entry.player_id == player_id:
            return entry.rank
    return None


SUPABASE_LOAD_ERROR_MESSAGE = (
    "Error: Failed to load latest ratings. Leaderboard may not be up to date."
)


def _load_ex_leaderboard_data(
    *,
    search: str = "",
    limit: int | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> tuple[list[ExLeaderboardEntry], bool]:
    baseline = load_baseline_leaderboard_csv(baseline_path)
    if not baseline:
        return [], False

    updated_ratings: dict[str, UpdatedRating] = {}
    supabase_load_failed = False
    if supabase_configured():
        try:
            updated_ratings = load_updated_ratings_from_supabase()
        except Exception:
            supabase_load_failed = True

    merged = merge_baseline_with_updated_ratings(baseline, updated_ratings)
    ranked = rank_leaderboard_entries(merged)

    trimmed_search = search.strip()
    if trimmed_search:
        needle = trimmed_search.casefold()
        ranked = [entry for entry in ranked if needle in entry.player.casefold()]

    if limit is not None:
        ranked = ranked[:limit]

    return ranked, supabase_load_failed


def load_ex_leaderboard(
    *,
    search: str = "",
    limit: int | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> list[ExLeaderboardEntry]:
    rankings, _ = _load_ex_leaderboard_data(
        search=search,
        limit=limit,
        baseline_path=baseline_path,
    )
    return rankings


def load_ex_leaderboard_with_warning(
    *,
    search: str = "",
    limit: int | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> tuple[list[ExLeaderboardEntry], bool]:
    return _load_ex_leaderboard_data(
        search=search,
        limit=limit,
        baseline_path=baseline_path,
    )


def leaderboard_available(baseline_path=EX_RATING_BASELINE_PATH) -> bool:
    return baseline_path.exists()
