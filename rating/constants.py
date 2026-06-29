from pathlib import Path

TOP_N = 25
COMPLETION_BONUS = 2.0
RATING_DIVISOR = 5625
EX_S_PLUS_THRESHOLD = 98.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_SCORES_PATH = PROJECT_ROOT / "resources" / "ArcadeMaxScores.csv"
LEADERBOARDS_JUNE27_DIR = PROJECT_ROOT / "resources" / "Leaderboards_June27"
CHART_RATING_LEVELS_PATH = PROJECT_ROOT / "resources" / "chart_rating_levels.json"
EX_RATING_LEADERBOARD_DB_PATH = PROJECT_ROOT / "resources" / "ex_rating_leaderboard.sqlite"
RATING_OVERRIDES_PATH = PROJECT_ROOT / "resources" / "rating_overrides.json"
FULL_EX_RATING_LEADERBOARD_PATH = PROJECT_ROOT / "resources" / "full_ex_rating_leaderboard.csv"
SHARED_EX_RANKINGS_PATH = PROJECT_ROOT / "resources" / "shared_ex_rankings.json"
GOOGLE_SHEET_ID = "16fpprBB4ynYxYFgoqnAlqmUCvXiEqRz-LgvivjvK_J0"
GOOGLE_SHEET_APPROVED_TAB = "Approved"
GOOGLE_SHEET_PENDING_TAB = "Pending"
