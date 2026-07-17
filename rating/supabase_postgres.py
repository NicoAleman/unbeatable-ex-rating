"""Shared Supabase Postgres access: transaction-mode URL + small process pool."""

from __future__ import annotations

import random
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

import psycopg2
from psycopg2 import OperationalError
from psycopg2.pool import PoolError, ThreadedConnectionPool

from rating.supabase_config import get_supabase_db_url

# Keep this low: Streamlit is one process serving many viewers; Supabase session
# pools are tiny, and even transaction mode shares limited backend slots.
_POOL_MINCONN = 1
_POOL_MAXCONN = 4
_CONNECT_MAX_ATTEMPTS = 5
_GETCONN_TIMEOUT_SECONDS = 45.0

_POOL_LOCK = threading.Lock()
_POOLS: dict[str, ThreadedConnectionPool] = {}


def prefer_transaction_pooler(db_url: str) -> str:
    """Rewrite Supabase session-pooler URIs (port 5432) to transaction mode (6543).

    Session mode holds one backend slot for the whole client session and often
    caps around pool_size=15 across all apps — too small for multi-user Streamlit.
    Transaction mode returns slots after each transaction.
    """
    if "pooler.supabase.com" not in db_url.lower():
        return db_url
    return re.sub(
        r"(pooler\.supabase\.com):5432\b",
        r"\1:6543",
        db_url,
        count=1,
        flags=re.IGNORECASE,
    )


def resolve_supabase_db_url(db_url: str | None = None) -> str:
    url = prefer_transaction_pooler(db_url or get_supabase_db_url() or "")
    if not url:
        raise RuntimeError(
            "Supabase is not configured. Set supabase.db_url in .streamlit/secrets.toml "
            "or SUPABASE_DB_URL in the environment."
        )
    return url


def _is_pool_exhausted_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "emaxconnsession" in message
        or "max clients reached" in message
        or "maxclientsessions" in message
        or "too many clients" in message
        or "connection pool exhausted" in message
    )


def _get_pool(db_url: str) -> ThreadedConnectionPool:
    with _POOL_LOCK:
        pool = _POOLS.get(db_url)
        if pool is not None and not pool.closed:
            return pool
        pool = ThreadedConnectionPool(
            minconn=_POOL_MINCONN,
            maxconn=_POOL_MAXCONN,
            dsn=db_url,
        )
        _POOLS[db_url] = pool
        return pool


class PooledConnection:
    """psycopg2 connection wrapper that returns to the pool on close / with-exit."""

    def __init__(self, pool: ThreadedConnectionPool, conn: Any) -> None:
        self._pool = pool
        self._conn = conn
        self._returned = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __enter__(self) -> PooledConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self.close()
        return False

    def close(self) -> None:
        if self._returned:
            return
        self._returned = True
        conn = self._conn
        try:
            if not conn.closed:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self._pool.putconn(conn)
        except Exception:
            try:
                self._pool.putconn(conn, close=True)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass


def acquire_postgres_connection(db_url: str | None = None) -> PooledConnection:
    """Borrow a pooled connection. Always call ``.close()`` (or use as context manager)."""
    url = resolve_supabase_db_url(db_url)
    last_error: BaseException | None = None

    for attempt in range(_CONNECT_MAX_ATTEMPTS):
        pool = _get_pool(url)
        deadline = time.monotonic() + _GETCONN_TIMEOUT_SECONDS
        conn = None
        while conn is None:
            try:
                conn = pool.getconn()
            except PoolError as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting for a free Supabase database connection. "
                        "Too many pages are loading at once."
                    ) from exc
                time.sleep(0.05)

        try:
            if conn.closed:
                pool.putconn(conn, close=True)
                conn = None
                continue
            # Cheap liveness check; replace dead sockets left by pooler churn.
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()
            return PooledConnection(pool, conn)
        except OperationalError as exc:
            last_error = exc
            try:
                pool.putconn(conn, close=True)
            except Exception:
                pass
            message = str(exc).lower()
            if not _is_pool_exhausted_error(exc) and "server closed" not in message:
                with _POOL_LOCK:
                    stale = _POOLS.pop(url, None)
                if stale is not None:
                    try:
                        stale.closeall()
                    except Exception:
                        pass
            if attempt + 1 >= _CONNECT_MAX_ATTEMPTS:
                raise
            time.sleep(0.35 * (2**attempt) + random.uniform(0.0, 0.25))
        except Exception:
            try:
                pool.putconn(conn, close=True)
            except Exception:
                pass
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to open Supabase database connection.")


@contextmanager
def postgres_connection(db_url: str | None = None) -> Iterator[PooledConnection]:
    """Borrow a pooled connection for the duration of the ``with`` block."""
    conn = acquire_postgres_connection(db_url)
    try:
        yield conn
    finally:
        conn.close()


def describe_db_target(db_url: str | None = None) -> str:
    """Short host:port label for logs (no password)."""
    try:
        url = resolve_supabase_db_url(db_url)
    except RuntimeError:
        return "unconfigured"
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = parsed.port or "?"
    return f"{host}:{port}"
