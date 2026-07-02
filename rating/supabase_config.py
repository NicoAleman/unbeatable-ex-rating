import os


def get_supabase_db_url() -> str | None:
    """Postgres connection string from Streamlit secrets or environment."""
    try:
        import streamlit as st

        secrets = st.secrets.get("supabase", {})
        url = secrets.get("db_url")
        if url and "YOUR_" not in str(url):
            return str(url).strip()
    except Exception:
        pass

    for env_name in ("DATABASE_URL", "SUPABASE_DB_URL"):
        url = os.environ.get(env_name)
        if url and "YOUR_" not in url:
            return url.strip()
    return None


def supabase_configured() -> bool:
    return get_supabase_db_url() is not None
