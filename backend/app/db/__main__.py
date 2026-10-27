"""CLI entry point for the database layer.

Usage (run from backend/):
    python -m app.db init --path data/meettrack.db
    python -m app.db reset-demo --path data/meettrack_demo.db

The reset-demo subcommand only accepts paths whose filename contains "demo".
This guards against accidentally wiping a production database.
"""

import argparse
import sys
from pathlib import Path

from app.db.connection import get_conn
from app.db.migrations import get_schema_version, run_migrations


def cmd_init(db_path: str) -> None:
    """Create the database (if it does not exist) and apply all migrations."""
    conn = get_conn(db_path)
    try:
        run_migrations(conn)
        version = get_schema_version(conn)
        print(f"Database ready: {db_path}")
        print(f"Schema version: {version}")
    finally:
        conn.close()


def cmd_reset_demo(db_path: str) -> None:
    """Delete and recreate the database. Only allowed when filename contains 'demo'."""
    stem = Path(db_path).name
    if "demo" not in stem:
        print(
            f"ERROR: reset-demo refused for '{db_path}'.\n"
            "The file name must contain 'demo' to prevent accidental data loss.\n"
            "Use a path like 'data/meettrack_demo.db'.",
            file=sys.stderr,
        )
        sys.exit(1)

    target = Path(db_path)
    if target.exists():
        target.unlink()
        print(f"Deleted existing database: {db_path}")

    conn = get_conn(db_path)
    try:
        run_migrations(conn)
        version = get_schema_version(conn)
        print(f"Demo database created: {db_path}")
        print(f"Schema version: {version}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.db",
        description="MeetTrack database management commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create DB and apply migrations.")
    init_parser.add_argument("--path", required=True, help="Path to the SQLite file.")

    reset_parser = subparsers.add_parser("reset-demo", help="Delete and recreate a demo database.")
    reset_parser.add_argument("--path", required=True, help="Path to the SQLite file.")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args.path)
    elif args.command == "reset-demo":
        cmd_reset_demo(args.path)


if __name__ == "__main__":
    main()
