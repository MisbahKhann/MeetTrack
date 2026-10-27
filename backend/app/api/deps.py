"""FastAPI dependencies for MeetTrack API.

Provides:
- get_db: SQLite connection dependency with proper closing and auto-migration.
- get_llm_client: LLMClient dependency based on current settings.
"""

from collections.abc import Generator
import os
import sqlite3

from app.agent.llm import LLMClient, get_llm
from app.core.config import get_settings
from app.db.connection import get_conn
from app.db.migrations import run_migrations


def _resolve_db_path() -> str:
    try:
        return get_settings().db_path
    except Exception:
        return os.environ.get("DB_PATH", "data/meettrack.db")


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Provide a database connection that closes after the request completes."""
    db_path = _resolve_db_path()
    conn = get_conn(db_path)
    try:
        run_migrations(conn)
        yield conn
    finally:
        conn.close()


def get_llm_client() -> LLMClient:
    """Provide configured LLM client instance."""
    settings = get_settings()
    return get_llm(settings)
