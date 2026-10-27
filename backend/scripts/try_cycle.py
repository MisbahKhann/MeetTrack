"""Manual try-out script for tuning prompts by hand.

Usage:
    python -m backend.scripts.try_cycle <notes_file> <as_of> [--db demo.db]

Refuses any database path that does not contain "demo".
"""

import argparse
import sys
from pathlib import Path

from app.agent.llm import FakeLLM, get_llm
from app.agent.orchestrator import ingest_notes
from app.core.config import Settings
from app.core.logging_setup import configure_logging
from app.db.connection import get_conn
from app.db.migrations import run_migrations
from app.tools.action_store import init_team, MemberInput

TEAM_A = "A"


def main() -> None:
    parser = argparse.ArgumentParser(description="Try a cycle against demo data")
    parser.add_argument("notes_file", type=str, help="Path to notes .txt file")
    parser.add_argument("as_of", type=str, help="ISO date yyyy-mm-dd")
    parser.add_argument("--db", type=str, default="demo.db", help="Database path (must contain 'demo')")
    args = parser.parse_args()

    if "demo" not in args.db:
        print("Refusing: database path must contain 'demo'")
        sys.exit(1)

    notes_path = Path(args.notes_file)
    if not notes_path.exists():
        print(f"Notes file not found: {notes_path}")
        sys.exit(1)

    configure_logging("demo_try_cycle.log.jsonl")

    conn = get_conn(args.db)
    run_migrations(conn)

    try:
        init_team(
            conn,
            team_id=TEAM_A,
            name="Team A",
            members=[
                MemberInput(name="Bilal"),
                MemberInput(name="Amna"),
                MemberInput(name="Sara"),
            ],
        )
    except Exception:
        pass

    try:
        settings = Settings()
        llm = get_llm(settings)
    except Exception:
        llm = FakeLLM([{"actions": []}])

    content = notes_path.read_bytes()
    report = ingest_notes(
        conn, llm,
        team_id=TEAM_A,
        file_name=notes_path.name,
        content=content,
        as_of=args.as_of,
    )

    print(f"\nStatus: {report.status}")
    print(f"Cycle: {report.cycle_id}")
    print(f"LLM calls: {report.llm_calls}")
    print(f"As of: {report.as_of}")
    print()

    if report.proposals:
        print(f"{'Outcome':<22} {'Action':<10} {'Owner':<10} {'Due':<12} {'EvLn':<5} {'Reason'}")
        print("-" * 80)
        for p in report.proposals:
            print(
                f"{p.outcome:<22} {str(p.action_id or '-'):<10} "
                f"{str(p.owner or '-'):<10} {str(p.due_date or '-'):<12} "
                f"{str(p.evidence_line or '-'):<5} {p.reason}"
            )
    else:
        print("(no proposals)")

    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  - {w}")

    conn.close()


if __name__ == "__main__":
    main()
