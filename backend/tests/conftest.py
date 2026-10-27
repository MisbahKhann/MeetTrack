"""Shared pytest fixtures for the MeetTrack backend test suite."""

import sqlite3
from pathlib import Path

import pytest
from app.db.connection import get_conn
from app.db.migrations import run_migrations


@pytest.fixture()
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Return an in-memory-like connection to a temp DB with migrations applied."""
    conn = get_conn(str(tmp_path / "test.db"))
    run_migrations(conn)
    return conn


@pytest.fixture()
def seeded_conn(db_conn: sqlite3.Connection) -> sqlite3.Connection:
    """DB connection with one team, two members, and one meeting pre-inserted."""
    db_conn.execute(
        "INSERT INTO teams (id, name, created_at) VALUES (?, ?, ?)",
        ("team-1", "Alpha Team", "2026-01-01T00:00:00Z"),
    )
    db_conn.execute(
        "INSERT INTO members (id, team_id, name, email, created_at) VALUES (?, ?, ?, ?, ?)",
        ("mem-1", "team-1", "Alice", "alice@example.com", "2026-01-01T00:00:00Z"),
    )
    db_conn.execute(
        "INSERT INTO members (id, team_id, name, email, created_at) VALUES (?, ?, ?, ?, ?)",
        ("mem-2", "team-1", "Bob", "bob@example.com", "2026-01-01T00:00:00Z"),
    )
    db_conn.execute(
        "INSERT INTO meetings (id, team_id, filename, file_hash, as_of_date, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("mtg-1", "team-1", "week01.txt", "abc123", "2026-01-15", "2026-01-15T09:00:00Z"),
    )
    db_conn.execute(
        "INSERT INTO action_counters (team_id, last_number) VALUES (?, ?)",
        ("team-1", 0),
    )
    db_conn.commit()
    return db_conn
