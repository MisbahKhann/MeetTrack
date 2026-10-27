"""Proposals router: list, decide, and commit agent proposals awaiting approval."""

from typing import Any
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agent.orchestrator import commit_approved
from app.api.deps import get_db
from app.tools.action_store import (
    CommitResult,
    DecisionRecord,
    ProposalPayload,
    ProposalRecord,
    decide_proposal,
    list_proposals,
)

router = APIRouter(prefix="/proposals", tags=["proposals"])


class DecideRequest(BaseModel):
    team_id: str = Field(..., min_length=1)
    decision: str = Field(..., min_length=1)
    user_comment: str | None = None
    edited_payload: ProposalPayload | dict[str, Any] | None = None


class CommitRequest(BaseModel):
    team_id: str = Field(..., min_length=1)
    cycle_id: str = Field(..., min_length=1)


@router.get("", response_model=list[ProposalRecord])
def get_cycle_proposals(
    team_id: str,
    cycle_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ProposalRecord]:
    """List proposals awaiting human approval for a given team and cycle."""
    return list_proposals(conn, team_id=team_id, cycle_id=cycle_id)


@router.post("/{proposal_id}/decide", response_model=DecisionRecord)
def make_proposal_decision(
    proposal_id: str,
    body: DecideRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> DecisionRecord:
    """Approve, edit, or reject a proposal. Never commits immediately to memory."""
    return decide_proposal(
        conn,
        team_id=body.team_id,
        proposal_id=proposal_id,
        decision=body.decision,
        comment=body.user_comment,
        edited_payload=body.edited_payload,
    )


@router.post("/commit", response_model=list[CommitResult])
def commit_cycle_proposals(
    body: CommitRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[CommitResult]:
    """Commit only approved or edited proposals to action memory.

    Rejects or pending proposals are never committed.
    """
    return commit_approved(conn, team_id=body.team_id, cycle_id=body.cycle_id)
