"""Tests for the database schema, migrations, and constraint enforcement.

All tests use pytest's tmp_path fixture and never touch a real database.
"""

import sqlite3
from pathlib import Path

import pytest
from app.db.connection import get_conn, transaction
from app.db.migrations import (
    MigrationTamperError,
    get_schema_version,
    run_migrations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "schema_migrations",
    "teams",
    "members",
    "meetings",
    "actions",
    "action_versions",
    "cycles",
    "proposals",
    "user_decisions",
    "reminders",
    "action_log",
    "action_counters",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_creates_all_tables(db_conn: sqlite3.Connection) -> None:
    """After migrations, all 12 expected tables must exist."""
    tables = _table_names(db_conn)
    assert (
        EXPECTED_TABLES == tables
    ), f"Missing: {EXPECTED_TABLES - tables}  Extra: {tables - EXPECTED_TABLES}"


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def test_migrations_idempotent(tmp_path: Path) -> None:
    """Running run_migrations twice stays at version 2 with no errors."""
    conn = get_conn(str(tmp_path / "idem.db"))
    run_migrations(conn)
    assert get_schema_version(conn) == 2
    run_migrations(conn)  # second run must be a no-op
    assert get_schema_version(conn) == 2
    conn.close()


def test_migration_tamper_detected(tmp_path: Path) -> None:
    """Modifying an applied migration's hash record raises MigrationTamperError."""
    conn = get_conn(str(tmp_path / "tamper.db"))
    run_migrations(conn)

    # Corrupt the stored hash for migration 1.
    conn.execute(
        "UPDATE schema_migrations SET file_hash = ? WHERE version = 1",
        ("0000000000000000000000000000000000000000000000000000000000000000",),
    )
    conn.commit()

    with pytest.raises(MigrationTamperError, match="has been modified"):
        run_migrations(conn)

    conn.close()


def test_get_schema_version_zero_on_empty(tmp_path: Path) -> None:
    """get_schema_version returns 0 when no migrations have been applied."""
    conn = get_conn(str(tmp_path / "empty.db"))
    assert get_schema_version(conn) == 0
    conn.close()


# ---------------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------------


def test_foreign_keys_enforced(db_conn: sqlite3.Connection) -> None:
    """Inserting an action with a non-existent team_id must raise IntegrityError."""
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("act-x", "no-such-team", "A-001", 1, "no-such-meeting", "2026-01-15T09:00:00Z"),
        )
        db_conn.commit()


# ---------------------------------------------------------------------------
# Unique constraints
# ---------------------------------------------------------------------------


def test_duplicate_file_hash_same_team_rejected(seeded_conn: sqlite3.Connection) -> None:
    """Uploading the same hash twice for the same team must fail."""
    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            "INSERT INTO meetings (id, team_id, filename, file_hash, as_of_date, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mtg-2", "team-1", "week01_copy.txt", "abc123", "2026-01-15", "2026-01-15T10:00:00Z"),
        )
        seeded_conn.commit()


def test_duplicate_file_hash_different_team_allowed(seeded_conn: sqlite3.Connection) -> None:
    """The same hash under a different team must succeed (scoped uniqueness)."""
    seeded_conn.execute(
        "INSERT INTO teams (id, name, created_at) VALUES (?, ?, ?)",
        ("team-2", "Beta Team", "2026-01-01T00:00:00Z"),
    )
    seeded_conn.execute(
        "INSERT INTO meetings (id, team_id, filename, file_hash, as_of_date, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("mtg-3", "team-2", "week01.txt", "abc123", "2026-01-15", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.commit()
    row = seeded_conn.execute("SELECT id FROM meetings WHERE team_id = 'team-2'").fetchone()
    assert row is not None


def test_single_current_version_enforced(seeded_conn: sqlite3.Connection) -> None:
    """Two is_current=1 rows for the same action must fail (partial unique index)."""
    # Create a meeting and action first.
    seeded_conn.execute(
        "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("act-1", "team-1", "A-001", 3, "mtg-1", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.execute(
        "INSERT INTO action_versions "
        "(id, action_id, team_id, version_no, description, owner, status, "
        " is_current, valid_from, changed_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "av-1",
            "act-1",
            "team-1",
            1,
            "Write report",
            "Alice",
            "open",
            1,
            "2026-01-15T09:00:00Z",
            "agent_approved",
        ),
    )
    seeded_conn.commit()

    # Inserting a second is_current=1 row for the same action must fail.
    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            "INSERT INTO action_versions "
            "(id, action_id, team_id, version_no, description, owner, status, "
            " is_current, valid_from, changed_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "av-2",
                "act-1",
                "team-1",
                2,
                "Write report v2",
                "Alice",
                "open",
                1,
                "2026-01-15T10:00:00Z",
                "user_correction",
            ),
        )
        seeded_conn.commit()


def test_two_versions_allowed_when_first_superseded(seeded_conn: sqlite3.Connection) -> None:
    """Setting is_current=0 on the old version then inserting a new one must succeed."""
    seeded_conn.execute(
        "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("act-2", "team-1", "A-002", 5, "mtg-1", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.execute(
        "INSERT INTO action_versions "
        "(id, action_id, team_id, version_no, description, owner, status, "
        " is_current, valid_from, changed_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "av-3",
            "act-2",
            "team-1",
            1,
            "Review code",
            "Bob",
            "open",
            1,
            "2026-01-15T09:00:00Z",
            "agent_approved",
        ),
    )
    seeded_conn.commit()

    # Mark old version superseded, then insert the new current version.
    seeded_conn.execute(
        "UPDATE action_versions SET is_current = 0, superseded_at = ? WHERE id = ?",
        ("2026-01-22T09:00:00Z", "av-3"),
    )
    seeded_conn.execute(
        "INSERT INTO action_versions "
        "(id, action_id, team_id, version_no, description, owner, status, "
        " is_current, valid_from, changed_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "av-4",
            "act-2",
            "team-1",
            2,
            "Review code (updated)",
            "Bob",
            "done",
            1,
            "2026-01-22T09:00:00Z",
            "user_correction",
        ),
    )
    seeded_conn.commit()

    row = seeded_conn.execute(
        "SELECT version_no FROM action_versions WHERE action_id = 'act-2' AND is_current = 1"
    ).fetchone()
    assert row["version_no"] == 2


# ---------------------------------------------------------------------------
# CHECK constraints
# ---------------------------------------------------------------------------


def test_check_constraint_invalid_action_status(seeded_conn: sqlite3.Connection) -> None:
    """An invalid action_versions.status value must be rejected."""
    seeded_conn.execute(
        "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("act-bad", "team-1", "A-003", 7, "mtg-1", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            "INSERT INTO action_versions "
            "(id, action_id, team_id, version_no, description, owner, status, "
            " is_current, valid_from, changed_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "av-bad",
                "act-bad",
                "team-1",
                1,
                "Task",
                "Alice",
                "INVALID_STATUS",
                1,
                "2026-01-15T09:00:00Z",
                "agent_approved",
            ),
        )
        seeded_conn.commit()


def test_check_constraint_invalid_proposal_outcome(seeded_conn: sqlite3.Connection) -> None:
    """An invalid proposals.outcome value must be rejected."""
    seeded_conn.execute(
        "INSERT INTO cycles (id, team_id, meeting_id, state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cyc-1", "team-1", "mtg-1", "extracted", "2026-01-15T09:00:00Z", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.execute(
        "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("act-p", "team-1", "A-004", 2, "mtg-1", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            "INSERT INTO proposals "
            "(id, team_id, cycle_id, action_id, outcome, rationale, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "prop-bad",
                "team-1",
                "cyc-1",
                "act-p",
                "do_something_weird",
                "rationale",
                "pending",
                "2026-01-15T09:00:00Z",
            ),
        )
        seeded_conn.commit()


def test_check_constraint_reminder_status_must_be_unsent(seeded_conn: sqlite3.Connection) -> None:
    """A reminder.status other than UNSENT must be rejected."""
    seeded_conn.execute(
        "INSERT INTO cycles (id, team_id, meeting_id, state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cyc-2", "team-1", "mtg-1", "extracted", "2026-01-15T09:00:00Z", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.execute(
        "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("act-r", "team-1", "A-005", 9, "mtg-1", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            "INSERT INTO reminders "
            "(id, team_id, action_id, cycle_id, idempotency_key, recipient_name, "
            " draft_text, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "rem-bad",
                "team-1",
                "act-r",
                "cyc-2",
                "key-bad",
                "Alice",
                "Hi Alice",
                "SENT",
                "2026-01-15T09:00:00Z",
            ),
        )
        seeded_conn.commit()


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------


def test_reminder_idempotency_key_unique(seeded_conn: sqlite3.Connection) -> None:
    """Two reminders with the same idempotency_key must fail."""
    seeded_conn.execute(
        "INSERT INTO cycles (id, team_id, meeting_id, state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cyc-3", "team-1", "mtg-1", "extracted", "2026-01-15T09:00:00Z", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.execute(
        "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("act-idem", "team-1", "A-006", 11, "mtg-1", "2026-01-15T09:00:00Z"),
    )
    seeded_conn.commit()

    seeded_conn.execute(
        "INSERT INTO reminders "
        "(id, team_id, action_id, cycle_id, idempotency_key, recipient_name, "
        " draft_text, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rem-1",
            "team-1",
            "act-idem",
            "cyc-3",
            "idem-key-1",
            "Alice",
            "Hello",
            "UNSENT",
            "2026-01-15T09:00:00Z",
        ),
    )
    seeded_conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            "INSERT INTO reminders "
            "(id, team_id, action_id, cycle_id, idempotency_key, recipient_name, "
            " draft_text, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "rem-2",
                "team-1",
                "act-idem",
                "cyc-3",
                "idem-key-1",
                "Bob",
                "Hello again",
                "UNSENT",
                "2026-01-15T09:00:00Z",
            ),
        )
        seeded_conn.commit()


# ---------------------------------------------------------------------------
# transaction() context manager
# ---------------------------------------------------------------------------


def test_transaction_rollback_on_exception(db_conn: sqlite3.Connection) -> None:
    """An exception inside transaction() must leave the database unchanged."""
    db_conn.execute(
        "INSERT INTO teams (id, name, created_at) VALUES (?, ?, ?)",
        ("team-rb", "Rollback Team", "2026-01-01T00:00:00Z"),
    )
    db_conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        with transaction(db_conn):
            # This insert is fine.
            db_conn.execute(
                "INSERT INTO members (id, team_id, name, created_at) " "VALUES (?, ?, ?, ?)",
                ("mem-rb", "team-rb", "Charlie", "2026-01-01T00:00:00Z"),
            )
            # This violates FK -- should trigger rollback.
            db_conn.execute(
                "INSERT INTO actions "
                "(id, team_id, action_code, source_line, meeting_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("act-rb", "team-rb", "A-001", 1, "no-such-meeting", "2026-01-01T00:00:00Z"),
            )

    # The member insert must have been rolled back.
    row = db_conn.execute("SELECT id FROM members WHERE id = 'mem-rb'").fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# reset-demo protection
# ---------------------------------------------------------------------------


def test_reset_demo_refuses_non_demo_path(tmp_path: Path) -> None:
    """reset-demo must refuse any path whose filename does not contain 'demo'."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "app.db", "reset-demo", "--path", "data/meettrack.db"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),  # backend/
    )
    assert result.returncode != 0
    assert "demo" in result.stderr.lower() or "refused" in result.stderr.lower()
