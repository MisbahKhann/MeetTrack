"""SQLite connection helpers.

Responsibilities:
- Open a connection with the required PRAGMAs.
- Provide a context-manager transaction() for safe commit/rollback.
- Expose utc_now() as the single source of UTC timestamps so tests can
  monkeypatch it without touching the standard library directly.

This module does NOT read environment variables. The caller passes db_path.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string.

    This is the only place timestamps are generated in the database layer.
    Monkeypatch this function in tests that need deterministic timestamps.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn(db_path: str) -> sqlite3.Connection:
    """Open (and if necessary create) a SQLite database at *db_path*.

    The parent directory is created if it does not exist.
    Every connection has:
    - row_factory = sqlite3.Row  (access columns by name)
    - foreign_keys = ON
    - journal_mode = WAL         (better concurrency)
    - busy_timeout = 5000 ms
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[None, None, None]:
    """Context manager that commits on clean exit and rolls back on exception.

    Usage::

        with transaction(conn):
            conn.execute("INSERT INTO teams ...")

    The exception is always re-raised after rollback so the caller can handle it.
    """
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
