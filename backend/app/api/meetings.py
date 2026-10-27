"""Meetings router: upload, process meeting notes and list meetings."""

from typing import Any
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.agent.llm import LLMClient
from app.agent.orchestrator import CycleReport, ingest_notes
from app.api.deps import get_db, get_llm_client
from app.tools.action_store import MeetingRecord, list_meetings

router = APIRouter(prefix="/meetings", tags=["meetings"])


class IngestNotesRequest(BaseModel):
    team_id: str = Field(..., min_length=1)
    file_name: str = Field(default="notes.txt", min_length=1)
    content: str = Field(..., min_length=1)
    as_of: str | None = None
    memory_enabled: bool = True

    @field_validator("content", mode="before")
    @classmethod
    def coerce_content(cls, v: Any) -> str:
        if isinstance(v, dict) and "value" in v:
            return str(v["value"])
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        return str(v) if v is not None else ""

    @field_validator("team_id", mode="before")
    @classmethod
    def coerce_team_id(cls, v: Any) -> str:
        if isinstance(v, dict) and "value" in v:
            return str(v["value"]).strip()
        return str(v).strip() if v is not None else ""


@router.post("/upload", response_model=CycleReport)
async def upload_meeting_notes(
    request: Request,
    team_id: str | None = None,
    file_name: str | None = None,
    as_of: str | None = None,
    memory_enabled: bool = True,
    conn: sqlite3.Connection = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
) -> CycleReport:
    """Upload plain-text notes via JSON body or raw bytes in request body."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        req_team_id = data.get("team_id") or team_id
        req_file_name = data.get("file_name") or file_name or "notes.txt"
        req_as_of = data.get("as_of", as_of)
        req_memory_enabled = data.get("memory_enabled", memory_enabled)
        content_data = data.get("content", "")
    else:
        req_team_id = team_id
        req_file_name = file_name or "notes.txt"
        req_as_of = as_of
        req_memory_enabled = memory_enabled
        content_data = await request.body()

    if not req_team_id:
        from app.tools.action_store import ValidationError

        raise ValidationError("team_id must be provided in query parameter or JSON body")

    return ingest_notes(
        conn,
        llm,
        team_id=req_team_id,
        file_name=req_file_name,
        content=content_data,
        as_of=req_as_of,
        memory_enabled=req_memory_enabled,
    )


@router.post("/ingest", response_model=CycleReport)
def ingest_meeting_notes(
    body: IngestNotesRequest,
    conn: sqlite3.Connection = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
) -> CycleReport:
    """Ingest plain-text notes directly via JSON payload."""
    return ingest_notes(
        conn,
        llm,
        team_id=body.team_id,
        file_name=body.file_name,
        content=body.content,
        as_of=body.as_of,
        memory_enabled=body.memory_enabled,
    )


@router.get("", response_model=list[MeetingRecord])
def get_meetings(
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[MeetingRecord]:
    """List all ingested meetings for a team."""
    return list_meetings(conn, team_id=team_id)


@router.get("/{team_id}", response_model=list[MeetingRecord])
def get_meetings_for_team(
    team_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[MeetingRecord]:
    """List all ingested meetings for a team by path parameter."""
    return list_meetings(conn, team_id=team_id)
