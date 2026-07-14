"""Bingo feature flags and local configuration."""

# Square-claim scoring: "v1" sums raw chart scores per team; "v2" uses EX Accuracy
# formula + placement bonus per player (see rating/bingo_chart_scoring.py).
BINGO_SCORING_VERSION = "v2"
