"""Targeted end-to-end tests for MeetTrack FastAPI routers."""

import io
import sqlite3
from typing import Generator

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.agent.llm import FakeLLM, LLMClient
from app.api.deps import get_db, get_llm_client
from app.main import app
from app.tools.action_store import (
    create_action,
    create_cycle,
    new_version,
    save_proposals,
    ProposalPayload,
)


@pytest.fixture()
def client(seeded_conn: sqlite3.Connection) -> Generator[TestClient, None, None]:
    """TestClient with seeded DB and canned FakeLLM injected via dependency overrides."""
    fake_llm = FakeLLM(
        responses=[
            # Extraction response
            {
                "actions": [
                    {
                        "description": "Design database schema",
                        "owner": "Alice",
                        "due_text": "next Friday",
                        "source_line": 2,
                        "confidence": 0.95,
                        "needs_clarification": False,
                        "clarification_question": None,
                    }
                ]
            },
        ]
    )

    def override_get_db() -> Generator[sqlite3.Connection, None, None]:
        yield seeded_conn

    def override_get_llm() -> LLMClient:
        return fake_llm

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_client] = override_get_llm

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Teams Tests
# ---------------------------------------------------------------------------


def test_teams_crud(client: TestClient) -> None:
    # 1. Create team
    res = client.post(
        "/api/v1/teams",
        json={"name": "Beta Team", "members": ["Charlie", "Dana"]},
    )
    assert res.status_code == 201
    created = res.json()
    assert created["name"] == "Beta Team"
    team_id = created["team_id"]

    # 2. List teams
    res = client.get("/api/v1/teams")
    assert res.status_code == 200
    teams = res.json()
    assert any(t["team_id"] == team_id for t in teams)

    # 3. Get team
    res = client.get(f"/api/v1/teams/{team_id}")
    assert res.status_code == 200
    assert res.json()["name"] == "Beta Team"

    # 4. List members
    res = client.get(f"/api/v1/teams/{team_id}/members")
    assert res.status_code == 200
    members = res.json()
    names = [m["name"] for m in members]
    assert "Charlie" in names
    assert "Dana" in names

    # 5. Add new member
    res = client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"name": "Eve", "email": "eve@example.com"},
    )
    assert res.status_code == 201
    assert res.json()["name"] == "Eve"


def test_team_not_found(client: TestClient) -> None:
    res = client.get("/api/v1/teams/non-existent-team")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

def test_delete_team(client: TestClient) -> None:
    # 1. Create team
    res = client.post(
        "/api/v1/teams",
        json={"name": "Delete Me Team", "members": ["Member1"]},
    )
    assert res.status_code == 201
    team_id = res.json()["team_id"]

    # 2. Delete team
    del_res = client.delete(f"/api/v1/teams/{team_id}")
    assert del_res.status_code == 204

    # 3. Verify it is gone
    get_res = client.get(f"/api/v1/teams/{team_id}")
    assert get_res.status_code == 404

    # 4. Deleting again returns 404
    del_res_again = client.delete(f"/api/v1/teams/{team_id}")
    assert del_res_again.status_code == 404


# ---------------------------------------------------------------------------
# Meetings & Ingestion Tests
# ---------------------------------------------------------------------------


def test_meeting_ingest_and_list(client: TestClient) -> None:
    notes_text = (
        "Meeting 2 | Alpha Team | 2026-01-16\n"
        "1. Team met to discuss the database architecture.\n"
        "2. Alice will design database schema by next Friday.\n"
    )

    # Ingest notes
    res = client.post(
        "/api/v1/meetings/ingest",
        json={
            "team_id": "team-1",
            "file_name": "meeting_02.txt",
            "content": notes_text,
            "as_of": "2026-01-16",
        },
    )
    assert res.status_code == 200
    report = res.json()
    assert report["status"] == "proposed"
    assert report["cycle_id"] is not None
    assert len(report["proposals"]) >= 1

    # List meetings
    res = client.get("/api/v1/meetings?team_id=team-1")
    assert res.status_code == 200
    meetings = res.json()
    assert len(meetings) >= 1
    assert any(m["file_name"] == "meeting_02.txt" for m in meetings)


# ---------------------------------------------------------------------------
# Proposals Lifecycle Tests (List -> Decide -> Commit)
# ---------------------------------------------------------------------------


def test_proposals_lifecycle(client: TestClient, seeded_conn: sqlite3.Connection) -> None:
    cycle = create_cycle(seeded_conn, team_id="team-1", meeting_id="mtg-1", as_of="2026-01-15")
    # Save a pending proposal
    payload = ProposalPayload(
        outcome="new_action",
        description="Set up test harness",
        owner="Alice",
        due_date="2026-01-25",
        source_line=1,
        reason="Test action",
    )
    saved = save_proposals(seeded_conn, team_id="team-1", cycle_id=cycle.cycle_id, payloads=[payload])
    proposal_id = saved[0].proposal_id

    # 1. List proposals
    res = client.get(f"/api/v1/proposals?team_id=team-1&cycle_id={cycle.cycle_id}")
    assert res.status_code == 200
    props = res.json()
    assert len(props) == 1
    assert props[0]["proposal_id"] == proposal_id
    assert props[0]["status"] == "pending"

    # 2. Decide: Approve
    res = client.post(
        f"/api/v1/proposals/{proposal_id}/decide",
        json={
            "team_id": "team-1",
            "decision": "approve",
            "user_comment": "Looks good, proceed",
        },
    )
    assert res.status_code == 200
    dec = res.json()
    assert dec["decision"] == "approve"

    # 3. Commit approved
    res = client.post(
        "/api/v1/proposals/commit",
        json={"team_id": "team-1", "cycle_id": cycle.cycle_id},
    )
    assert res.status_code == 200
    commit_results = res.json()
    assert len(commit_results) == 1
    assert commit_results[0]["outcome"] == "new_action"

    # Verify action now exists in actions
    res = client.get("/api/v1/actions?team_id=team-1")
    assert res.status_code == 200
    actions = res.json()
    assert any(a["description"] == "Set up test harness" for a in actions)


def test_proposals_edit_and_approve(client: TestClient, seeded_conn: sqlite3.Connection) -> None:
    cycle = create_cycle(seeded_conn, team_id="team-1", meeting_id="mtg-1", as_of="2026-01-15")
    payload = ProposalPayload(
        outcome="new_action",
        description="Original description",
        owner="Alice",
        due_date="2026-01-25",
        source_line=1,
        reason="Test action",
    )
    saved = save_proposals(seeded_conn, team_id="team-1", cycle_id=cycle.cycle_id, payloads=[payload])
    proposal_id = saved[0].proposal_id

    # 1. Decide: Edit with dictionary payload (as sent by frontend clients)
    res = client.post(
        f"/api/v1/proposals/{proposal_id}/decide",
        json={
            "team_id": "team-1",
            "decision": "edit",
            "user_comment": "date exceeded",
            "edited_payload": {
                "outcome": "new_action",
                "description": "Collect 500 more leaf images by Sunday",
                "owner": "Alice",
                "due_date": "2026-10-09",
                "reason": "Edited by supervisor",
            },
        },
    )
    assert res.status_code == 200
    dec = res.json()
    assert dec["decision"] == "edit"
    assert "Alice" in dec["edited_payload_json"]

    # 2. Commit approved edits
    res = client.post(
        "/api/v1/proposals/commit",
        json={"team_id": "team-1", "cycle_id": cycle.cycle_id},
    )
    assert res.status_code == 200
    committed = res.json()
    assert len(committed) == 1
    assert committed[0]["outcome"] == "new_action"

    # Verify action registered with edited owner and description
    res = client.get("/api/v1/actions?team_id=team-1")
    assert res.status_code == 200
    actions = res.json()
    matched = [a for a in actions if a["action_id"] == committed[0]["action_id"]]
    assert len(matched) == 1
    assert matched[0]["owner"] == "Alice"
    assert matched[0]["description"] == "Collect 500 more leaf images by Sunday"


def test_rejected_proposals_are_never_committed(client: TestClient, seeded_conn: sqlite3.Connection) -> None:
    cycle = create_cycle(seeded_conn, team_id="team-1", meeting_id="mtg-1", as_of="2026-01-15")
    payload = ProposalPayload(
        outcome="new_action",
        description="Out of scope feature",
        owner="Bob",
        due_date="2026-01-25",
        source_line=1,
        reason="Out of scope",
    )
    saved = save_proposals(seeded_conn, team_id="team-1", cycle_id=cycle.cycle_id, payloads=[payload])
    proposal_id = saved[0].proposal_id

    # Reject proposal
    res = client.post(
        f"/api/v1/proposals/{proposal_id}/decide",
        json={"team_id": "team-1", "decision": "reject", "user_comment": "Rejected by supervisor"},
    )
    assert res.status_code == 200

    # Attempt commit
    res = client.post(
        "/api/v1/proposals/commit",
        json={"team_id": "team-1", "cycle_id": cycle.cycle_id},
    )
    assert res.status_code == 200
    commit_results = res.json()
    # Rejected proposal must NOT be committed
    assert len(commit_results) == 0

    # Verify action does NOT exist
    res = client.get("/api/v1/actions?team_id=team-1")
    actions = res.json()
    assert not any(a["description"] == "Out of scope feature" for a in actions)


# ---------------------------------------------------------------------------
# Actions & Version History Tests
# ---------------------------------------------------------------------------


def test_actions_and_history(client: TestClient, seeded_conn: sqlite3.Connection) -> None:
    act = create_action(
        seeded_conn,
        team_id="team-1",
        description="Action to correct",
        origin_meeting_id="mtg-1",
        owner="Alice",
        due_date="2026-01-20",
        source_line=5,
        changed_by="agent_approved",
    )

    # 1. Get action detail
    res = client.get(f"/api/v1/actions/{act.action_id}?team_id=team-1")
    assert res.status_code == 200
    assert res.json()["action_code"] == act.action_code

    # 2. Correct action
    res = client.post(
        f"/api/v1/actions/{act.action_id}/correct",
        json={
            "team_id": "team-1",
            "field": "owner",
            "value": "Bob",
            "comment": "Reassigned to Bob",
        },
    )
    assert res.status_code == 200
    assert res.json()["owner"] == "Bob"
    assert res.json()["version_no"] == 2

    # 3. Retrieve history
    res = client.get(f"/api/v1/actions/{act.action_id}/history?team_id=team-1")
    assert res.status_code == 200
    history = res.json()
    assert len(history) == 2
    v1 = history[0]
    v2 = history[1]
    assert v1["owner"] == "Alice"
    assert v1["is_current"] == 0
    assert v1["superseded_at"] is not None
    assert v2["owner"] == "Bob"
    assert v2["is_current"] == 1


# ---------------------------------------------------------------------------
# Exports Tests
# ---------------------------------------------------------------------------


def test_exports_endpoints(client: TestClient, seeded_conn: sqlite3.Connection) -> None:
    create_action(
        seeded_conn,
        team_id="team-1",
        description="Prepare final report",
        origin_meeting_id="mtg-1",
        owner="Alice",
        due_date="2026-01-05",  # overdue
        source_line=8,
        changed_by="agent_approved",
    )
    cycle = create_cycle(seeded_conn, team_id="team-1", meeting_id="mtg-1", as_of="2026-01-20")

    # 1. Download Excel register
    res = client.get("/api/v1/exports/register?team_id=team-1&as_of=2026-01-20")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert "Action Register" in wb.sheetnames
    assert "History" in wb.sheetnames

    # 2. Generate reminders
    res = client.post(
        "/api/v1/exports/reminders/generate",
        json={"team_id": "team-1", "cycle_id": cycle.cycle_id, "as_of": "2026-01-20"},
    )
    assert res.status_code == 200
    reminders = res.json()
    assert len(reminders) == 1
    assert reminders[0]["status"] == "UNSENT"

    # 3. List reminders
    res = client.get(f"/api/v1/exports/reminders?team_id=team-1&cycle_id={cycle.cycle_id}")
    assert res.status_code == 200
    drafts = res.json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "UNSENT"
