#!/usr/bin/env python3
"""Deprecated: use sync_top_scores_to_supabase.py for Supabase score uploads."""

import sys

print(
    "This script is deprecated.\n"
    "- Baseline ratings: commit resources/ex_rating_baseline.csv (from build_ex_leaderboard.py)\n"
    "- Top player scores: python sync_top_scores_to_supabase.py",
    file=sys.stderr,
)
raise SystemExit(1)
