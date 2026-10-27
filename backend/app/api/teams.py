"""Teams router: create, retrieve, and delete teams and members."""

import sqlite3

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.tools.action_store import (
    MemberRecord,
    TeamRecord,
    add_member,
    delete_team,
    get_team,
    init_team,
    list_members,
    list_teams,
)

router = APIRouter(prefix="/teams", tags=["teams"])


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1)
    team_id: str | None = None
    supervisor: str | None = None
    members: list[str] = Field(default_factory=list)


class AddMemberRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: str | None = None


@router.post("", response_model=TeamRecord, status_code=status.HTTP_201_CREATED)
def create_team(
    body: CreateTeamRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> TeamRecord:
    """Create a new team and initialize any initial members."""
    return init_team(
        conn,
        team_id=body.team_id,
        name=body.name,
        supervisor=body.supervisor,
        members=body.members,
    )


@router.get("", response_model=list[TeamRecord])
def get_all_teams(conn: sqlite3.Connection = Depends(get_db)) -> list[TeamRecord]:
    """List all registered teams."""
    return list_teams(conn)


@router.get("/{team_id}", response_model=TeamRecord)
def get_team_by_id(
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> TeamRecord:
    """Retrieve details for a single team."""
    return get_team(conn, team_id=team_id)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team_by_id(
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Delete a team and all its associated team-owned records."""
    delete_team(conn, team_id=team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{team_id}/members", response_model=MemberRecord, status_code=status.HTTP_201_CREATED)
def add_team_member(
    team_id: str,
    body: AddMemberRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> MemberRecord:
    """Add a member to an existing team."""
    return add_member(conn, team_id=team_id, name=body.name, email=body.email)


@router.get("/{team_id}/members", response_model=list[MemberRecord])
def get_team_members(
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[MemberRecord]:
    """List all members of a team."""
    return list_members(conn, team_id=team_id)
