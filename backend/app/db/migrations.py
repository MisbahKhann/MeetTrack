"""Migration runner for MeetTrack.

Migrations are numbered .sql files in the migrations/ subdirectory of this
package:  app/db/migrations/NNN_name.sql

Rules:
- Files are applied in ascending numeric order.
- Each file is applied inside its own transaction.
- Applied files are recorded in schema_migrations with their SHA-256 hash.
- Running the runner a second time is a no-op for already-applied files.
- If a previously applied file's content differs from its recorded hash,
  the runner raises MigrationTamperError and refuses to continue.
"""

import hashlib
import re
import sqlite3
from pathlib import Path

from app.db.connection import transaction, utc_now

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class MigrationError(Exception):
    """Raised when a migration cannot be applied."""


class MigrationTamperError(MigrationError):
    """Raised when a previously applied migration file has been modified."""


def _file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _migration_version(filename: str) -> int:
    """Parse the leading integer from a filename like '001_initial.sql'."""
    match = re.match(r"^(\d+)_", filename)
    if not match:
        raise MigrationError(f"Migration filename does not start with a number: {filename}")
    return int(match.group(1))


def _applied_migrations(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """Return a mapping of version -> {name, file_hash} for applied migrations."""
    rows = conn.execute(
        "SELECT version, name, file_hash FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {row["version"]: {"name": row["name"], "file_hash": row["file_hash"]} for row in rows}


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """Create schema_migrations if it does not yet exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT    NOT NULL,
            file_hash  TEXT    NOT NULL,
            applied_at TEXT    NOT NULL
        )
        """
    )
    conn.commit()


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations in order.

    - Already-applied migrations are verified for tamper; any mismatch raises
      MigrationTamperError.
    - New migrations are applied inside individual transactions and recorded.
    - Running twice on the same database is safe (idempotent).
    """
    _ensure_migrations_table(conn)
    applied = _applied_migrations(conn)

    sql_files = sorted(
        (f for f in MIGRATIONS_DIR.glob("*.sql")),
        key=lambda f: _migration_version(f.name),
    )

    for sql_file in sql_files:
        version = _migration_version(sql_file.name)
        digest = _file_sha256(sql_file)

        if version in applied:
            recorded = applied[version]["file_hash"]
            if digest != recorded:
                raise MigrationTamperError(
                    f"Migration {sql_file.name} (version {version}) has been modified "
                    f"after being applied. Expected hash {recorded!r}, got {digest!r}. "
                    "Do not edit applied migration files."
                )
            # Already applied and hash matches -- skip.
            continue

        # New migration: apply inside a transaction.
        sql = sql_file.read_text(encoding="utf-8")
        with transaction(conn):
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, file_hash, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (version, sql_file.name, digest, utc_now()),
            )


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none applied."""
    _ensure_migrations_table(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    result = row["v"]
    return int(result) if result is not None else 0
