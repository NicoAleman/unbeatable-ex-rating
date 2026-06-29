from rating.board import competition_ranks_for_values
from rating.baseline_leaderboard import BaselineLeaderboardEntry, UpdatedRating, load_baseline_leaderboard_csv
from rating.constants import EX_RATING_BASELINE_PATH
from rating.ex_leaderboard_db import ExLeaderboardEntry
from rating.supabase_config import supabase_configured
from rating.supabase_leaderboard import load_updated_ratings_from_supabase


def merge_baseline_with_updated_ratings(
    baseline: list[BaselineLeaderboardEntry],
    updated_ratings: dict[str, UpdatedRating],
) -> list[BaselineLeaderboardEntry]:
    if not updated_ratings:
        return baseline

    merged: list[BaselineLeaderboardEntry] = []
    for entry in baseline:
        override = updated_ratings.get(entry.player_id)
        if override is None:
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


def load_ex_leaderboard(
    *,
    search: str = "",
    limit: int | None = None,
    baseline_path=EX_RATING_BASELINE_PATH,
) -> list[ExLeaderboardEntry]:
    baseline = load_baseline_leaderboard_csv(baseline_path)
    if not baseline:
        return []

    updated_ratings: dict[str, UpdatedRating] = {}
    if supabase_configured():
        updated_ratings = load_updated_ratings_from_supabase()

    merged = merge_baseline_with_updated_ratings(baseline, updated_ratings)
    ranked = rank_leaderboard_entries(merged)

    trimmed_search = search.strip()
    if trimmed_search:
        needle = trimmed_search.casefold()
        ranked = [entry for entry in ranked if needle in entry.player.casefold()]

    if limit is not None:
        ranked = ranked[:limit]

    return ranked


def leaderboard_available(baseline_path=EX_RATING_BASELINE_PATH) -> bool:
    return baseline_path.exists()
