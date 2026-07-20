"""Compute EX rating gains and rank changes for Bingo participants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rating.baseline_leaderboard import UpdatedRating, load_baseline_leaderboard_csv
from rating.bingo import TEAM_ORDER, load_bingo_settings, load_bingo_teams_by_ex_rating
from rating.leaderboard_activity import LeaderboardActivityEntry
from rating.public_leaderboard import merge_baseline_with_updated_ratings, rank_leaderboard_entries
from rating.supabase_leaderboard import _connect_postgres


def load_all_activity(db_url: str | None = None) -> list[LeaderboardActivityEntry]:
    conn = _connect_postgres(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT player_id, prev_rating, new_rating, prev_rank, new_rank,
                       created_at, submission_source
                FROM leaderboard_activity
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    entries: list[LeaderboardActivityEntry] = []
    for row in rows:
        created_raw = row[5]
        if isinstance(created_raw, datetime):
            created_at = (
                created_raw
                if created_raw.tzinfo
                else created_raw.replace(tzinfo=timezone.utc)
            )
        else:
            created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))

        entries.append(
            LeaderboardActivityEntry(
                player_id=str(row[0]),
                display_name=str(row[0]),
                prev_rating=float(row[1]),
                new_rating=float(row[2]),
                prev_rank=int(row[3]),
                new_rank=int(row[4]),
                created_at=created_at,
                submission_source=str(row[6]) if row[6] is not None else None,
            )
        )
    return entries


def ratings_at_time(
    baseline_ratings: dict[str, float],
    activity: list[LeaderboardActivityEntry],
    moment: datetime,
) -> dict[str, float]:
    ratings = dict(baseline_ratings)
    for entry in activity:
        if entry.created_at <= moment:
            ratings[entry.player_id] = entry.new_rating
        else:
            break
    return ratings


def rank_map(
    baseline,
    ratings: dict[str, float],
) -> dict[str, int]:
    baseline_by_id = {entry.player_id: entry for entry in baseline}
    overrides: dict[str, UpdatedRating] = {}
    for player_id, rating in ratings.items():
        baseline_entry = baseline_by_id.get(player_id)
        if baseline_entry is None:
            continue
        if abs(rating - baseline_entry.ex_rating) > 1e-9:
            overrides[player_id] = UpdatedRating(ex_rating=rating, last_updated="")

    merged = merge_baseline_with_updated_ratings(baseline, overrides)
    ranked = rank_leaderboard_entries(merged)
    return {entry.player_id: entry.rank for entry in ranked}


def main() -> None:
    settings = load_bingo_settings()
    if settings is None or settings.start_time is None:
        raise RuntimeError("Bingo settings are not configured.")

    start = settings.start_time
    end = start + timedelta(days=int(settings.day_count or 7))

    baseline = load_baseline_leaderboard_csv()
    baseline_ratings = {entry.player_id: entry.ex_rating for entry in baseline}
    baseline_by_id = {entry.player_id: entry for entry in baseline}
    activity = load_all_activity()
    teams = load_bingo_teams_by_ex_rating()

    roster: list[tuple[str, str, str]] = []
    for team in TEAM_ORDER:
        for player in teams.get(team, []):
            roster.append((player.player_id, player.display_name, team))

    start_ratings = ratings_at_time(baseline_ratings, activity, start)
    end_ratings = ratings_at_time(baseline_ratings, activity, end)

    start_ranks = rank_map(baseline, start_ratings)
    end_ranks = rank_map(baseline, end_ratings)

    rows: list[dict[str, object]] = []
    for player_id, display_name, team in roster:
        start_rating = start_ratings.get(
            player_id,
            baseline_by_id[player_id].ex_rating if player_id in baseline_by_id else 0.0,
        )
        end_rating = end_ratings.get(player_id, start_rating)
        start_rank = start_ranks.get(player_id)
        end_rank = end_ranks.get(player_id)
        rank_change = (start_rank - end_rank) if start_rank and end_rank else None
        bingo_updates = [
            entry
            for entry in activity
            if entry.player_id == player_id and start <= entry.created_at <= end
        ]

        rows.append(
            {
                "name": display_name,
                "team": team,
                "start_rating": start_rating,
                "end_rating": end_rating,
                "gain": end_rating - start_rating,
                "start_rank": start_rank,
                "end_rank": end_rank,
                "rank_change": rank_change,
                "updates": len(bingo_updates),
            }
        )

    rows.sort(
        key=lambda row: (
            int(row["end_rank"]) if row["end_rank"] is not None else 10**9,
            str(row["name"]).casefold(),
        )
    )

    print(f"Bingo window: {start.isoformat()} -> {end.isoformat()}")
    print(f"Activity rows (all time): {len(activity)}")
    print()
    header = (
        f"{'Name':<24} {'Team':<6} {'Start':>10} {'End':>10} {'Gain':>9} "
        f"{'Start Rank':>11} {'End Rank':>9} {'Rank Change':>12}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        rank_change = row["rank_change"]
        if rank_change is None:
            rank_text = "n/a"
        elif rank_change == 0:
            rank_text = "-"
        else:
            rank_text = f"{rank_change:+d}"
        start_rank = int(row["start_rank"] or 0)
        end_rank = int(row["end_rank"] or 0)
        print(
            f"{str(row['name'])[:23]:<24} {row['team']:<6} "
            f"{float(row['start_rating']):10.3f} {float(row['end_rating']):10.3f} "
            f"{float(row['gain']):+9.3f} {f'#{start_rank}':>11} {f'#{end_rank}':>9} "
            f"{rank_text:>12}"
        )

    print()
    total_gain = sum(float(row["gain"]) for row in rows)
    improved = sum(1 for row in rows if float(row["gain"]) > 0.001)
    print(f"Total EX gain (all {len(rows)} players): {total_gain:+.2f}")
    print(f"Players with EX gain > 0: {improved}")


if __name__ == "__main__":
    main()
