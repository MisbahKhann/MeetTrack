"""Structured JSON-line logging with an optional SQLite action_log sink.

Usage::

    from app.core.logging_setup import configure_logging, log_event, set_log_context

    configure_logging(log_path="logs/meettrack.log.jsonl")

    with set_log_context(team_id="team-1", cycle_id="cyc-42"):
        log_event("llm_call", {"call_name": "extract", "latency_ms": 142})
        log_event("tool_call", {"tool": "note_reader"}, conn=db_conn)

Each JSON line written to the log file has:
    ts, level, event, team_id, cycle_id, detail

Sensitive keys (api_key, token, secret, password at any depth) are masked before
any line is written.

Logging is best-effort: exceptions inside log_event are caught, printed to stderr,
and never re-raised.
"""

import json
import logging
import sqlite3
import sys
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from app.db.connection import utc_now

_ALLOWED_EVENTS = frozenset(
    {
        "tool_call",
        "memory_read",
        "memory_write",
        "approval",
        "llm_call",
        "error",
    }
)

_SENSITIVE_KEYS = frozenset({"api_key", "token", "secret", "password"})

# Per-request context variables populated by set_log_context().
_ctx_team_id: ContextVar[str] = ContextVar("team_id", default="")
_ctx_cycle_id: ContextVar[str] = ContextVar("cycle_id", default="")

# File logger -- configured by configure_logging().
_file_logger: logging.Logger | None = None


def _redact(obj: Any, depth: int = 0) -> Any:
    """Recursively mask values whose key matches a sensitive name pattern."""
    if depth > 20:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***" if any(s in k.lower() for s in _SENSITIVE_KEYS) else _redact(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item, depth + 1) for item in obj]
    return obj


def configure_logging(log_path: str) -> None:
    """Set up a JSON-line file logger and a stderr handler at WARNING.

    Safe to call multiple times -- re-configures the existing logger.
    """
    global _file_logger

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("meettrack")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # File handler: every event as a raw JSON line.
    file_handler = logging.FileHandler(str(path), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)

    # Stderr handler: WARNING and above only (human-readable).
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(stderr_handler)

    _file_logger = logger


@contextmanager
def set_log_context(team_id: str = "", cycle_id: str = "") -> Generator[None, None, None]:
    """Context manager that sets team_id and cycle_id for all log_event calls inside."""
    tok_t = _ctx_team_id.set(team_id)
    tok_c = _ctx_cycle_id.set(cycle_id)
    try:
        yield
    finally:
        _ctx_team_id.reset(tok_t)
        _ctx_cycle_id.reset(tok_c)


def log_event(
    event: str,
    detail: dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    level: str = "INFO",
) -> None:
    """Write one structured JSON log line and optionally insert into action_log.

    Args:
        event:  One of the allowed event names from the action_log CHECK constraint.
        detail: Arbitrary payload dict. Sensitive keys are auto-redacted.
        conn:   When given, also inserts a row into action_log. Failures here are
                swallowed so the file log is never blocked by a DB problem.
        level:  Log level string (INFO, WARNING, ERROR). Defaults to INFO.

    Raises:
        ValueError: if event is not in the allowed set.
    """
    if event not in _ALLOWED_EVENTS:
        raise ValueError(f"Unknown log event {event!r}. Allowed: {sorted(_ALLOWED_EVENTS)}")

    try:
        ts = utc_now()
        team_id = _ctx_team_id.get()
        cycle_id = _ctx_cycle_id.get()
        safe_detail = _redact(detail)

        line: dict[str, Any] = {
            "ts": ts,
            "level": level,
            "event": event,
            "team_id": team_id,
            "cycle_id": cycle_id,
            "detail": safe_detail,
        }
        json_line = json.dumps(line, ensure_ascii=False)

        if _file_logger is not None:
            _file_logger.info(json_line)
        else:
            print(json_line, file=sys.stderr)

        if conn is not None:
            _write_action_log(conn, ts, team_id or None, cycle_id or None, event, safe_detail)

    except Exception as exc:  # noqa: BLE001
        # Logging must never crash the caller.
        print(f"[meettrack.logging] FAILED to write log: {exc}", file=sys.stderr)


def _write_action_log(
    conn: sqlite3.Connection,
    ts: str,
    team_id: str | None,
    cycle_id: str | None,
    event: str,
    detail: dict[str, Any],
) -> None:
    """Insert one row into action_log. Failures are caught by the caller."""
    try:
        conn.execute(
            "INSERT INTO action_log (id, team_id, cycle_id, event, payload, logged_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                team_id,
                cycle_id,
                event,
                json.dumps(detail, ensure_ascii=False),
                ts,
            ),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        log_event(
            "error",
            {"message": "Failed to write action_log row", "reason": str(exc)},
        )
