import os


def use_sql_leaderboard() -> bool:
    """When false (default), the app reads full_ex_rating_leaderboard.csv."""
    try:
        import streamlit as st

        leaderboard_secrets = st.secrets.get("leaderboard", {})
        if "use_sql" in leaderboard_secrets:
            return bool(leaderboard_secrets["use_sql"])
    except Exception:
        pass

    value = os.environ.get("USE_SQL_LEADERBOARD", "").strip().lower()
    return value in {"1", "true", "yes", "on"}
