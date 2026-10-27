"""Targeted tests for Excel register export and reminder writer."""

import io
import sqlite3
from pathlib import Path

import openpyxl
import pytest

from app.tools.action_store import (
    create_action,
    create_cycle,
    init_team,
    new_version,
    save_proposals,
    ProposalPayload,
)
from app.tools.register_writer import export_register
from app.tools.reminder_writer import (
    build_reminder_text,
    create_reminder_for_action,
    generate_cycle_reminders,
    list_draft_reminders,
)


@pytest.fixture()
def setup_team(seeded_conn: sqlite3.Connection) -> sqlite3.Connection:
    """Fixture with actions and versions pre-created."""
    # Create action 1: open and overdue
    act1 = create_action(
        seeded_conn,
        team_id="team-1",
        description="Write architecture specification",
        origin_meeting_id="mtg-1",
        owner="Alice",
        due_date="2026-01-10",
        source_line=10,
        changed_by="agent_approved",
    )
    # Update action 1 to create version history
    new_version(
        seeded_conn,
        team_id="team-1",
        action_id=act1.action_id,
        due_date="2026-01-12",
        changed_by="user_correction",
    )

    # Create action 2: blocked
    create_action(
        seeded_conn,
        team_id="team-1",
        description="Set up CI pipeline",
        origin_meeting_id="mtg-1",
        owner="Bob",
        due_date="2026-02-01",
        source_line=15,
        changed_by="agent_approved",
    )
    return seeded_conn


def test_excel_export_creates_sheets_and_history(setup_team: sqlite3.Connection) -> None:
    """Export creates Action Register and History sheets with expected rows."""
    excel_bytes = export_register(setup_team, team_id="team-1", as_of="2026-01-20")
    assert excel_bytes is not None
    assert len(excel_bytes) > 0

    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    assert "Action Register" in wb.sheetnames
    assert "History" in wb.sheetnames

    # Check Action Register sheet
    ws_actions = wb["Action Register"]
    header = [cell.value for cell in ws_actions[1]]
    assert "Action Code" in header
    assert "Description" in header
    assert "Owner" in header
    assert "Overdue Days" in header
    assert "Decision" in header
    assert "Comments" in header

    rows = list(ws_actions.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 2
    # Action 1 due 2026-01-12, as_of 2026-01-20 -> 8 days overdue
    act1_row = next(r for r in rows if r[header.index("Owner")] == "Alice")
    assert act1_row[header.index("Overdue Days")] == 8

    # Check History sheet
    ws_history = wb["History"]
    hist_header = [cell.value for cell in ws_history[1]]
    assert "Version No" in hist_header
    assert "Superseded At" in hist_header

    hist_rows = list(ws_history.iter_rows(min_row=2, values_only=True))
    # Action 1 has 2 versions, Action 2 has 1 version -> total 3 rows
    assert len(hist_rows) == 3


def test_excel_preserves_user_manual_columns(setup_team: sqlite3.Connection) -> None:
    """Re-export preserves manual Decision and Comments columns matched by Action Code."""
    # First export
    first_bytes = export_register(setup_team, team_id="team-1", as_of="2026-01-20")

    # Simulate user adding manual notes in Excel
    wb = openpyxl.load_workbook(io.BytesIO(first_bytes))
    ws = wb["Action Register"]
    header = [cell.value for cell in ws[1]]
    decision_col = header.index("Decision") + 1
    comments_col = header.index("Comments") + 1

    # Add manual comments to row 2
    ws.cell(row=2, column=decision_col, value="Approved by Lead")
    ws.cell(row=2, column=comments_col, value="High priority FYP requirement")

    edited_buf = io.BytesIO()
    wb.save(edited_buf)
    edited_bytes = edited_buf.getvalue()

    # Re-export with preserved bytes
    second_bytes = export_register(
        setup_team,
        team_id="team-1",
        as_of="2026-01-20",
        existing_bytes=edited_bytes,
    )

    wb2 = openpyxl.load_workbook(io.BytesIO(second_bytes))
    ws2 = wb2["Action Register"]
    header2 = [cell.value for cell in ws2[1]]
    rows2 = list(ws2.iter_rows(min_row=2, values_only=True))

    row2_vals = rows2[0]
    assert row2_vals[header2.index("Decision")] == "Approved by Lead"
    assert row2_vals[header2.index("Comments")] == "High priority FYP requirement"


def test_reminder_writer_creates_unsent_drafts_idempotently(setup_team: sqlite3.Connection) -> None:
    """Reminders are marked UNSENT, persistently stored, and idempotent."""
    cycle = create_cycle(setup_team, team_id="team-1", meeting_id="mtg-1", as_of="2026-01-20")

    # Action 1 is overdue for Alice -> should generate reminder
    reminders = generate_cycle_reminders(
        setup_team,
        team_id="team-1",
        cycle_id=cycle.cycle_id,
        as_of="2026-01-20",
    )
    assert len(reminders) == 1
    rem = reminders[0]
    assert rem.recipient_name == "Alice"
    assert rem.status == "UNSENT"
    assert "STATUS: UNSENT" in rem.draft_text
    assert "Alice" in rem.draft_text

    # Second run should return existing reminder without duplicate insertion
    reminders_retry = generate_cycle_reminders(
        setup_team,
        team_id="team-1",
        cycle_id=cycle.cycle_id,
        as_of="2026-01-20",
    )
    assert len(reminders_retry) == 1
    assert reminders_retry[0].reminder_id == rem.reminder_id

    # List drafts
    drafts = list_draft_reminders(setup_team, team_id="team-1", cycle_id=cycle.cycle_id)
    assert len(drafts) == 1
    assert drafts[0].reminder_id == rem.reminder_id
