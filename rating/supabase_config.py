import os
import re

BINGO_PROOF_BUCKET = "bingo-score-proofs"


def _read_supabase_secret(key: str) -> str | None:
    try:
        import streamlit as st

        secrets = st.secrets.get("supabase", {})
        value = secrets.get(key)
        if value and "YOUR_" not in str(value):
            return str(value).strip()
    except Exception:
        pass
    return None


def get_supabase_db_url() -> str | None:
    """Postgres connection string from Streamlit secrets or environment."""
    url = _read_supabase_secret("db_url")
    if url:
        return url

    for env_name in ("DATABASE_URL", "SUPABASE_DB_URL"):
        url = os.environ.get(env_name)
        if url and "YOUR_" not in url:
            return url.strip()
    return None


def _supabase_url_from_db_url(db_url: str) -> str | None:
    """Derive https://{ref}.supabase.co from a Postgres connection string."""
    pooler_match = re.search(r"postgres(?:ql)?://postgres\.([^:@/]+)", db_url)
    if pooler_match:
        return f"https://{pooler_match.group(1)}.supabase.co"

    direct_match = re.search(r"@db\.([^.]+)\.supabase\.co", db_url)
    if direct_match:
        return f"https://{direct_match.group(1)}.supabase.co"

    return None


def get_supabase_url() -> str | None:
    """Supabase project URL, e.g. https://xyz.supabase.co."""
    url = _read_supabase_secret("url")
    if url:
        return url.rstrip("/")

    url = os.environ.get("SUPABASE_URL")
    if url and "YOUR_" not in url:
        return url.strip().rstrip("/")

    db_url = get_supabase_db_url()
    if db_url:
        return _supabase_url_from_db_url(db_url)

    return None


def get_supabase_service_role_key() -> str | None:
    """Service role key for server-side Storage uploads."""
    key = _read_supabase_secret("service_role_key")
    if key:
        return key

    for env_name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY"):
        key = os.environ.get(env_name)
        if key and "YOUR_" not in key:
            return key.strip()
    return None


def supabase_configured() -> bool:
    return get_supabase_db_url() is not None


def supabase_storage_configured() -> bool:
    return bool(get_supabase_url() and get_supabase_service_role_key())
