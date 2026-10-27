"""Writes UNSENT reminder draft files. Nothing is ever sent.

Enforces:
- Hard rule 5: Nothing is ever sent. There is no send tool. Reminders are UNSENT text drafts.
- Hard rule 8: Scoped by team_id.
- Hard rule 9: Idempotency keys prevent duplicates across retries.
"""

import sqlite3
from datetime import date
from typing import Any

from app.agent.schemas import ExtractedAction
from app.tools.action_store import (
    ActionView,
    NotFoundError,
    ReminderRecord,
    get_current,
    get_open_actions,
    list_proposals,
    list_reminders,
    save_reminder,
)
from app.tools.date_checker import classify_due, parse_as_of


def build_reminder_text(action: ActionView, as_of: str | None = None) -> str:
    """Format polite, clear reminder draft text for an action."""
    due = action.due_date or "No due date specified"
    lines = [
        f"Subject: Reminder: [{action.action_code}] {action.description}",
        "",
        f"Dear {action.owner or 'Team Member'},",
        "",
        f"This is a reminder regarding your action item [{action.action_code}]:",
        f"Description: {action.description}",
        f"Due Date: {due}",
        f"Current Status: {action.status}",
    ]
    if action.blocked_reason:
        lines.append(f"Blocked Reason: {action.blocked_reason}")
    lines.extend(
        [
            "",
            "Please review this item and provide an update at the next meeting.",
            "",
            "Best regards,",
            "MeetTrack",
            "",
            "---",
            "STATUS: UNSENT (Draft only -- no email or notification has been sent)",
        ]
    )
    return "\n".join(lines)


def create_reminder_for_action(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    action_id: str,
    cycle_id: str,
    as_of: str | None = None,
) -> ReminderRecord | None:
    """Create an UNSENT reminder draft for a specific action (idempotent)."""
    try:
        action = get_current(conn, team_id=team_id, action_id=action_id)
    except NotFoundError:
        return None

    if not action.owner or action.status == "done":
        return None

    idempotency_key = f"{team_id}:{cycle_id}:{action.action_id}"
    draft_text = build_reminder_text(action, as_of=as_of)

    return save_reminder(
        conn,
        team_id=team_id,
        action_id=action.action_id,
        cycle_id=cycle_id,
        idempotency_key=idempotency_key,
        recipient_name=action.owner,
        draft_text=draft_text,
    )


def generate_cycle_reminders(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    cycle_id: str,
    as_of: str | None = None,
) -> list[ReminderRecord]:
    """Generate UNSENT reminder drafts for appropriate actions in a cycle.

    Eligible actions:
    1. Approved proposals in this cycle with outcome 'draft_reminder'.
    2. Any overdue action with an assigned owner.
    """
    as_of_date = parse_as_of(as_of) if as_of else date.today()
    created_reminders: list[ReminderRecord] = []
    seen_action_ids: set[str] = set()

    # 1. Check approved proposals requesting reminders
    proposals = list_proposals(conn, team_id=team_id, cycle_id=cycle_id)
    for p in proposals:
        if p.outcome == "draft_reminder" and p.status in ("approved", "edited") and p.action_id:
            rem = create_reminder_for_action(
                conn,
                team_id=team_id,
                action_id=p.action_id,
                cycle_id=cycle_id,
                as_of=as_of,
            )
            if rem:
                created_reminders.append(rem)
                seen_action_ids.add(p.action_id)

    # 2. Check open overdue actions
    open_actions = get_open_actions(conn, team_id=team_id)
    for act in open_actions:
        if act.action_id in seen_action_ids:
            continue
        if not act.owner:
            continue
        due_cls = classify_due(
            date.fromisoformat(act.due_date) if act.due_date else None,
            as_of_date,
            act.status,
        )
        if due_cls == "overdue":
            rem = create_reminder_for_action(
                conn,
                team_id=team_id,
                action_id=act.action_id,
                cycle_id=cycle_id,
                as_of=as_of,
            )
            if rem:
                created_reminders.append(rem)
                seen_action_ids.add(act.action_id)

    return created_reminders


def list_draft_reminders(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    cycle_id: str | None = None,
) -> list[ReminderRecord]:
    """List persistent UNSENT reminder drafts for a team."""
    return list_reminders(conn, team_id=team_id, cycle_id=cycle_id)
