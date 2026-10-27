"""Actions router: read action list, version history, and manual corrections."""

from typing import Any
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.tools.action_store import (
    ActionView,
    VersionRecord,
    correct_action,
    get_current,
    get_history,
    list_actions,
)

router = APIRouter(prefix="/actions", tags=["actions"])


class CorrectRequest(BaseModel):
    team_id: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)
    value: Any
    comment: str | None = None


@router.get("", response_model=list[ActionView])
def get_team_actions(
    team_id: str,
    include_done: bool = True,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ActionView]:
    """List current action items for a team."""
    return list_actions(conn, team_id=team_id, include_done=include_done)


@router.get("/{action_id}", response_model=ActionView)
def get_action_detail(
    action_id: str,
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> ActionView:
    """Retrieve current details of a single action item."""
    return get_current(conn, team_id=team_id, action_id=action_id)


@router.get("/{action_id}/history", response_model=list[VersionRecord])
def get_action_version_history(
    action_id: str,
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[VersionRecord]:
    """Retrieve full version history for an action item (showing superseded versions)."""
    return get_history(conn, team_id=team_id, action_id=action_id)


@router.post("/{action_id}/correct", response_model=ActionView)
def apply_action_correction(
    action_id: str,
    body: CorrectRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> ActionView:
    """Apply a user correction creating a new version and superseding the previous one."""
    return correct_action(
        conn,
        team_id=body.team_id,
        action_id=action_id,
        field=body.field,
        value=body.value,
        comment=body.comment,
    )
