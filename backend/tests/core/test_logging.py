"""Tests for app.core.logging_setup."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from app.core.logging_setup import configure_logging, log_event, set_log_context
from app.db.connection import get_conn
from app.db.migrations import run_migrations


@pytest.fixture()
def log_file(tmp_path: Path) -> Path:
    """Configure logging to a temp file and return its path."""
    path = tmp_path / "test.log.jsonl"
    configure_logging(str(path))
    return path


@pytest.fixture()
def log_db(tmp_path: Path) -> sqlite3.Connection:
    """DB connection with migrations applied."""
    conn = get_conn(str(tmp_path / "log_test.db"))
    run_migrations(conn)
    # Seed a team so FK is satisfied.
    conn.execute(
        "INSERT INTO teams (id, name, created_at) VALUES (?, ?, ?)",
        ("t1", "Test", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    return conn


def _read_last_line(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])  # type: ignore[no-any-return]


def _read_first_line(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[0])  # type: ignore[no-any-return]


class TestJsonLine:
    def test_line_has_required_fields(self, log_file: Path) -> None:
        log_event("tool_call", {"tool": "note_reader"})
        line = _read_last_line(log_file)
        assert set(line.keys()) == {"ts", "level", "event", "team_id", "cycle_id", "detail"}

    def test_line_is_valid_json(self, log_file: Path) -> None:
        log_event("llm_call", {"call_name": "extract"})
        raw = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        data = json.loads(raw)
        assert data["event"] == "llm_call"

    def test_default_team_and_cycle_are_empty(self, log_file: Path) -> None:
        log_event("tool_call", {"x": 1})
        line = _read_last_line(log_file)
        assert line["team_id"] == ""
        assert line["cycle_id"] == ""


class TestContextVars:
    def test_context_populates_team_and_cycle(self, log_file: Path) -> None:
        with set_log_context(team_id="team-99", cycle_id="cyc-7"):
            log_event("approval", {"action": "approve"})
        line = _read_last_line(log_file)
        assert line["team_id"] == "team-99"
        assert line["cycle_id"] == "cyc-7"

    def test_context_resets_after_exit(self, log_file: Path) -> None:
        with set_log_context(team_id="team-99"):
            pass
        log_event("tool_call", {"x": 1})
        line = _read_last_line(log_file)
        assert line["team_id"] == ""


class TestRedaction:
    def test_top_level_key_masked(self, log_file: Path) -> None:
        log_event("error", {"api_key": "my-secret", "other": "visible"})
        line = _read_last_line(log_file)
        assert line["detail"]["api_key"] == "***"
        assert line["detail"]["other"] == "visible"

    def test_nested_key_masked(self, log_file: Path) -> None:
        log_event("error", {"outer": {"password": "pw123", "safe": "ok"}})
        line = _read_last_line(log_file)
        assert line["detail"]["outer"]["password"] == "***"
        assert line["detail"]["outer"]["safe"] == "ok"

    def test_token_and_secret_masked(self, log_file: Path) -> None:
        log_event("error", {"token": "tok", "secret": "sec"})
        line = _read_last_line(log_file)
        assert line["detail"]["token"] == "***"
        assert line["detail"]["secret"] == "***"


class TestActionLogSink:
    def test_db_row_written_when_conn_given(
        self, log_file: Path, log_db: sqlite3.Connection
    ) -> None:
        with set_log_context(team_id="t1"):
            log_event("tool_call", {"tool": "reader"}, conn=log_db)
        rows = log_db.execute("SELECT * FROM action_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["event"] == "tool_call"
        assert rows[0]["team_id"] == "t1"

    def test_db_failure_does_not_raise(self, log_file: Path) -> None:
        # Pass a closed connection -- DB write fails but log_event must not raise.
        conn = get_conn(":memory:")
        conn.close()
        log_event("tool_call", {"x": 1}, conn=conn)  # Must not raise.

    def test_file_log_still_written_on_db_failure(self, log_file: Path) -> None:
        conn = get_conn(":memory:")
        conn.close()
        log_event("tool_call", {"x": 99}, conn=conn)
        # tool_call is the first line; a DB-failure error line is appended after.
        line = _read_first_line(log_file)
        assert line["detail"]["x"] == 99


class TestInvalidEvent:
    def test_invalid_event_raises_value_error(self, log_file: Path) -> None:
        with pytest.raises(ValueError, match="Unknown log event"):
            log_event("bad_event", {})
