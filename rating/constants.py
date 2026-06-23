from pathlib import Path

TOP_N = 25
COMPLETION_BONUS = 2.0
RATING_DIVISOR = 5625
EX_S_PLUS_THRESHOLD = 98.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_SCORES_PATH = PROJECT_ROOT / "resources" / "ArcadeMaxScores.csv"
SHARED_EX_RANKINGS_PATH = PROJECT_ROOT / "resources" / "shared_ex_rankings.json"
