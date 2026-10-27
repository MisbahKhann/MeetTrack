"""Exports router: download Excel register and retrieve/generate UNSENT reminder drafts."""

import sqlite3

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.tools.action_store import ReminderRecord
from app.tools.register_writer import export_register
from app.tools.reminder_writer import generate_cycle_reminders, list_draft_reminders

router = APIRouter(prefix="/exports", tags=["exports"])

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class GenerateRemindersRequest(BaseModel):
    team_id: str = Field(..., min_length=1)
    cycle_id: str = Field(..., min_length=1)
    as_of: str | None = None


@router.get("/register")
def download_action_register(
    team_id: str,
    as_of: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Export the Excel action register with Action Register and History sheets."""
    data = export_register(conn, team_id=team_id, as_of=as_of)
    filename = f"action_register_{team_id}.xlsx"
    return Response(
        content=data,
        media_type=EXCEL_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/register")
async def update_action_register(
    request: Request,
    team_id: str,
    as_of: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Re-export Excel register preserving manual columns from the uploaded existing register in request body."""
    body_bytes = await request.body()
    existing_bytes = body_bytes if body_bytes else None
    data = export_register(conn, team_id=team_id, as_of=as_of, existing_bytes=existing_bytes)
    filename = f"action_register_{team_id}.xlsx"
    return Response(
        content=data,
        media_type=EXCEL_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reminders", response_model=list[ReminderRecord])
def get_draft_reminders(
    team_id: str,
    cycle_id: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ReminderRecord]:
    """Retrieve persistent UNSENT reminder drafts for a team (nothing is ever sent)."""
    return list_draft_reminders(conn, team_id=team_id, cycle_id=cycle_id)


@router.post("/reminders/generate", response_model=list[ReminderRecord])
def create_cycle_reminders(
    body: GenerateRemindersRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ReminderRecord]:
    """Generate and persistently store UNSENT reminder drafts for approved proposals and overdue actions."""
    return generate_cycle_reminders(
        conn,
        team_id=body.team_id,
        cycle_id=body.cycle_id,
        as_of=body.as_of,
    )
