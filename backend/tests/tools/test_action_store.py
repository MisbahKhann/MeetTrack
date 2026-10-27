"""Tests for app.tools.action_store."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from app.db.connection import get_conn
from app.db.migrations import run_migrations
from app.tools.action_store import (
    DuplicateFileError,
    InvalidStateError,
    MeetingRecord,
    MemberInput,
    NoChangeError,
    NotFoundError,
    ProposalPayload,
    ValidationError,
    add_meeting,
    commit_proposal,
    correct_action,
    create_action,
    create_cycle,
    decide_proposal,
    finalize_cycle,
    get_current,
    get_history,
    get_meeting_by_hash,
    get_open_actions,
    init_team,
    list_actions,
    list_members,
    new_version,
    next_action_id,
    resolve_member,
    save_proposals,
    set_cycle_state,
)

TEAM_A = "A"
TEAM_B = "B"
MEMBERS_A = [MemberInput(name="Bilal"), MemberInput(name="Amna"), MemberInput(name="Sara")]
MEMBERS_B = [MemberInput(name="Zara")]


def _make_conn(tmp_path: Path, name: str = "test.db") -> sqlite3.Connection:
    conn = get_conn(str(tmp_path / name))
    run_migrations(conn)
    return conn


def _seed_team(
    conn: sqlite3.Connection,
    team_id: str = TEAM_A,
    members: list[MemberInput] | None = None,
) -> None:
    if members is None:
        members = MEMBERS_A
    init_team(conn, team_id=team_id, name=f"Team {team_id}", supervisor=None, members=members)


def _seed_meeting(
    conn: sqlite3.Connection,
    team_id: str = TEAM_A,
    file_hash: str = "abc123",
) -> MeetingRecord:
    return add_meeting(
        conn,
        team_id=team_id,
        meeting_date="2026-10-05",
        file_name="meeting1.txt",
        file_hash=file_hash,
    )


def _seed_action(
    conn: sqlite3.Connection,
    team_id: str = TEAM_A,
    meeting_id: str | None = None,
    owner: str = "Bilal",
    description: str = "Collect leaf images",
    file_hash: str | None = None,
) -> Any:
    if meeting_id is None:
        fh = file_hash or f"hash-{team_id}-{description[:8]}"
        mtg = _seed_meeting(conn, team_id=team_id, file_hash=fh)
        meeting_id = mtg.meeting_id
    return create_action(
        conn,
        team_id=team_id,
        description=description,
        origin_meeting_id=meeting_id,
        owner=owner,
        due_date="2026-10-12",
    )


# ---------------------------------------------------------------------------
# Teams and members
# ---------------------------------------------------------------------------


def test_init_team_idempotent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    r1 = init_team(conn, team_id=TEAM_A, name="Team A", members=MEMBERS_A)
    r2 = init_team(conn, team_id=TEAM_A, name="Team A", members=MEMBERS_A)
    assert r1.team_id == r2.team_id == TEAM_A


def test_init_team_conflicting_name_rejected(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    init_team(conn, team_id=TEAM_A, name="Team A", members=MEMBERS_A)
    with pytest.raises(ValidationError, match="already exists"):
        init_team(conn, team_id=TEAM_A, name="Different", members=MEMBERS_A)


def test_init_team_duplicate_members_rejected(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    dupes = [MemberInput(name="Bilal"), MemberInput(name="bilal")]
    with pytest.raises(ValidationError, match="unique"):
        init_team(conn, team_id=TEAM_A, name="Team A", members=dupes)


def test_resolve_member_case_insensitive(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    assert resolve_member(conn, team_id=TEAM_A, name="bilal") == "Bilal"
    assert resolve_member(conn, team_id=TEAM_A, name="AMNA") == "Amna"
    assert resolve_member(conn, team_id=TEAM_A, name="nobody") is None


def test_list_members_scoped(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn, TEAM_A)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    names_a = {m.name for m in list_members(conn, team_id=TEAM_A)}
    names_b = {m.name for m in list_members(conn, team_id=TEAM_B)}
    assert names_a == {"Bilal", "Amna", "Sara"}
    assert names_b == {"Zara"}
    assert not names_a & names_b


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------


def test_add_meeting_duplicate_hash_same_team(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    _seed_meeting(conn, file_hash="deadbeef")
    with pytest.raises(DuplicateFileError):
        _seed_meeting(conn, file_hash="deadbeef")
    count = conn.execute("SELECT COUNT(*) FROM meetings WHERE team_id = ?", (TEAM_A,)).fetchone()[0]
    assert count == 1


def test_add_meeting_same_hash_different_team_ok(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn, TEAM_A)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    _seed_meeting(conn, TEAM_A, file_hash="shared")
    m = _seed_meeting(conn, TEAM_B, file_hash="shared")
    assert m.team_id == TEAM_B


def test_get_meeting_by_hash(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    added = _seed_meeting(conn, file_hash="findme")
    found = get_meeting_by_hash(conn, team_id=TEAM_A, file_hash="findme")
    assert found is not None
    assert found.meeting_id == added.meeting_id


def test_get_meeting_by_hash_wrong_team_returns_none(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn, TEAM_A)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    _seed_meeting(conn, TEAM_A, file_hash="secret")
    result = get_meeting_by_hash(conn, team_id=TEAM_B, file_hash="secret")
    assert result is None


def test_get_meeting_by_hash_missing(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    assert get_meeting_by_hash(conn, team_id=TEAM_A, file_hash="nope") is None


# ---------------------------------------------------------------------------
# next_action_id
# ---------------------------------------------------------------------------


def test_next_action_id_increments(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn, TEAM_A)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    with conn:
        id1 = next_action_id(conn, team_id=TEAM_A)
        id2 = next_action_id(conn, team_id=TEAM_A)
    with conn:
        idb = next_action_id(conn, team_id=TEAM_B)
    assert id1 == "A-001"
    assert id2 == "A-002"
    assert idb == "B-001"


def test_action_id_rollback_gives_same_code(tmp_path: Path) -> None:
    """A rolled-back allocation does not consume the code."""
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    try:
        with conn:
            next_action_id(conn, team_id=TEAM_A)
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    with conn:
        clean = next_action_id(conn, team_id=TEAM_A)
    assert clean == "A-001"


# ---------------------------------------------------------------------------
# create_action
# ---------------------------------------------------------------------------


def test_create_action_non_member_rejected(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    mtg = _seed_meeting(conn)
    with pytest.raises(ValidationError, match="not a member"):
        create_action(
            conn,
            team_id=TEAM_A,
            description="Task",
            origin_meeting_id=mtg.meeting_id,
            owner="Ghost",
            due_date=None,
        )


def test_create_action_none_owner_forces_clarification(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    mtg = _seed_meeting(conn)
    action = create_action(
        conn,
        team_id=TEAM_A,
        description="Unclear",
        origin_meeting_id=mtg.meeting_id,
        owner=None,
        due_date=None,
    )
    assert action.status == "needs_clarification"


def test_create_action_version_1_current(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    assert a.version_no == 1
    hist = get_history(conn, team_id=TEAM_A, action_id=a.action_id)
    assert len(hist) == 1
    assert hist[0].is_current == 1


# ---------------------------------------------------------------------------
# new_version
# ---------------------------------------------------------------------------


def test_new_version_supersedes_old(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    v2 = new_version(
        conn,
        team_id=TEAM_A,
        action_id=a.action_id,
        changed_by="agent_approved",
        due_date="2026-10-20",
    )
    assert v2.version_no == 2
    hist = get_history(conn, team_id=TEAM_A, action_id=a.action_id)
    assert hist[0].is_current == 0
    assert hist[0].superseded_at is not None
    assert hist[1].is_current == 1


def test_new_version_exactly_one_current(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    new_version(
        conn, team_id=TEAM_A, action_id=a.action_id, changed_by="agent_approved", status="done"
    )
    count = conn.execute(
        "SELECT COUNT(*) FROM action_versions WHERE action_id = ? AND is_current = 1",
        (a.action_id,),
    ).fetchone()[0]
    assert count == 1


def test_new_version_no_change_raises(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    with pytest.raises(NoChangeError):
        new_version(conn, team_id=TEAM_A, action_id=a.action_id, changed_by="agent_approved")


def test_new_version_explicit_none_clears_due_date(tmp_path: Path) -> None:
    """Explicit None clears; UNSET keeps the current value."""
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    assert a.due_date == "2026-10-12"
    v2 = new_version(
        conn, team_id=TEAM_A, action_id=a.action_id, changed_by="agent_approved", due_date=None
    )
    assert v2.due_date is None


def test_new_version_invalid_status_leaves_old_current(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    with pytest.raises(ValidationError):
        new_version(
            conn,
            team_id=TEAM_A,
            action_id=a.action_id,
            changed_by="agent_approved",
            status="invalid_status",
        )
    current = get_current(conn, team_id=TEAM_A, action_id=a.action_id)
    assert current.version_no == 1


def test_get_history_all_versions_ordered(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    new_version(
        conn,
        team_id=TEAM_A,
        action_id=a.action_id,
        changed_by="agent_approved",
        status="blocked",
        blocked_reason="Wait",
    )
    new_version(
        conn,
        team_id=TEAM_A,
        action_id=a.action_id,
        changed_by="user_correction",
        status="open",
        blocked_reason=None,
    )
    hist = get_history(conn, team_id=TEAM_A, action_id=a.action_id)
    assert [h.version_no for h in hist] == [1, 2, 3]


def test_get_open_actions_excludes_done(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a1 = _seed_action(conn, description="Open", file_hash="h1")
    a2 = _seed_action(conn, description="Done task", owner="Amna", file_hash="h2")
    new_version(
        conn, team_id=TEAM_A, action_id=a2.action_id, changed_by="agent_approved", status="done"
    )
    open_ids = {a.action_id for a in get_open_actions(conn, team_id=TEAM_A)}
    assert a1.action_id in open_ids
    assert a2.action_id not in open_ids


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn_name,kwargs_fn",
    [
        ("get_current", lambda aid: {"action_id": aid}),
        ("get_history", lambda aid: {"action_id": aid}),
        (
            "new_version",
            lambda aid: {"action_id": aid, "changed_by": "agent_approved", "status": "done"},
        ),
    ],
)
def test_action_isolation_wrong_team(tmp_path: Path, fn_name: str, kwargs_fn: Any) -> None:
    import app.tools.action_store as store

    conn = _make_conn(tmp_path)
    _seed_team(conn, TEAM_A)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    a = _seed_action(conn, TEAM_A)
    fn = getattr(store, fn_name)
    with pytest.raises(NotFoundError):
        fn(conn, team_id=TEAM_B, **kwargs_fn(a.action_id))


def test_list_actions_team_scoped(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn, TEAM_A)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    _seed_action(conn, TEAM_A)
    assert list_actions(conn, team_id=TEAM_B) == []


# ---------------------------------------------------------------------------
# correct_action
# ---------------------------------------------------------------------------


def test_correct_action_user_correction_version(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    v2 = correct_action(
        conn,
        team_id=TEAM_A,
        action_id=a.action_id,
        field="due_date",
        value="2026-10-30",
        comment="Extended",
    )
    assert v2.due_date == "2026-10-30"
    assert v2.changed_by == "user_correction"


def test_correct_action_rejects_unknown_field(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    with pytest.raises(ValidationError, match="Correctable fields"):
        correct_action(
            conn, team_id=TEAM_A, action_id=a.action_id, field="description", value="Changed"
        )


def test_correct_action_rejects_non_member_owner(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    with pytest.raises(ValidationError, match="not a member"):
        correct_action(conn, team_id=TEAM_A, action_id=a.action_id, field="owner", value="Ghost")


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------


def test_create_cycle_idempotent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    mtg = _seed_meeting(conn)
    c1 = create_cycle(conn, team_id=TEAM_A, meeting_id=mtg.meeting_id, as_of="2026-10-05")
    c2 = create_cycle(conn, team_id=TEAM_A, meeting_id=mtg.meeting_id, as_of="2026-10-05")
    assert c1.cycle_id == c2.cycle_id
    cycle_count = conn.execute(
        "SELECT COUNT(*) FROM cycles WHERE team_id = ?", (TEAM_A,)
    ).fetchone()[0]
    assert cycle_count == 1


def test_cycle_forward_only_transitions(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    mtg = _seed_meeting(conn)
    cycle = create_cycle(conn, team_id=TEAM_A, meeting_id=mtg.meeting_id, as_of="2026-10-05")
    with pytest.raises(InvalidStateError):
        set_cycle_state(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, state="committed")


def test_finalize_blocked_with_pending(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    mtg_id = conn.execute("SELECT id FROM meetings WHERE team_id = ?", (TEAM_A,)).fetchone()["id"]
    cycle = create_cycle(conn, team_id=TEAM_A, meeting_id=mtg_id, as_of="2026-10-05")
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="No update")
    save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    with pytest.raises(InvalidStateError, match="pending"):
        finalize_cycle(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id)


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------


def _setup_cycle(tmp_path: Path) -> tuple[sqlite3.Connection, Any, Any]:
    conn = _make_conn(tmp_path)
    _seed_team(conn)
    a = _seed_action(conn)
    mtg_id = conn.execute("SELECT id FROM meetings WHERE team_id = ?", (TEAM_A,)).fetchone()["id"]
    cycle = create_cycle(conn, team_id=TEAM_A, meeting_id=mtg_id, as_of="2026-10-05")
    return conn, a, cycle


def test_save_proposals_idempotent(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="r")
    p1 = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    p2 = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    assert len(p1) == len(p2) == 1
    assert p1[0].proposal_id == p2[0].proposal_id
    count = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE cycle_id = ?", (cycle.cycle_id,)
    ).fetchone()[0]
    assert count == 1


def test_payload_json_unchanged_after_decide_commit(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="Carry")
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    original_json = proposals[0].payload_json

    decide_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="approve")
    commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)

    row = conn.execute(
        "SELECT payload_json FROM proposals WHERE id = ?", (proposals[0].proposal_id,)
    ).fetchone()
    assert row["payload_json"] == original_json


def test_one_decision_per_proposal(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="r")
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    decide_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="approve")
    with pytest.raises(InvalidStateError):
        decide_proposal(
            conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="reject"
        )


def test_rejected_cannot_commit(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="r")
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    decide_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="reject")
    with pytest.raises(InvalidStateError, match="rejected"):
        commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)


def test_commit_close_with_evidence(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(
        action_id=a.action_id,
        outcome="close_with_evidence",
        evidence_quote="Bilal completed task",
        evidence_line=1,
        reason="Done",
    )
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    decide_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="approve")
    result = commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)
    assert result.already_committed is False
    assert get_current(conn, team_id=TEAM_A, action_id=a.action_id).status == "done"


def test_commit_new_action(tmp_path: Path) -> None:
    conn, _, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(
        outcome="new_action",
        description="Brand new task",
        owner="Bilal",
        due_date="2026-10-20",
        reason="Found",
    )
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    decide_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="approve")
    result = commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)
    assert result.action_id is not None
    act = get_current(conn, team_id=TEAM_A, action_id=result.action_id)
    assert act.description == "Brand new task"


def test_commit_double_is_safe(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="r")
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    decide_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id, decision="approve")
    commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)
    r2 = commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)
    assert r2.already_committed is True


def test_commit_edited_payload_applied(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    orig = ProposalPayload(
        action_id=a.action_id, outcome="carry_over", due_date="2026-10-15", reason="r"
    )
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[orig])
    edited = ProposalPayload(
        action_id=a.action_id, outcome="carry_over", due_date="2026-10-30", reason="r2"
    )
    decide_proposal(
        conn,
        team_id=TEAM_A,
        proposal_id=proposals[0].proposal_id,
        decision="edit",
        edited_payload=edited,
    )
    commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)
    current = get_current(conn, team_id=TEAM_A, action_id=a.action_id)
    assert current.due_date == "2026-10-30"
    # Original payload_json unchanged
    row = conn.execute(
        "SELECT payload_json FROM proposals WHERE id = ?", (proposals[0].proposal_id,)
    ).fetchone()
    saved = ProposalPayload.model_validate_json(row["payload_json"])
    assert saved.due_date == "2026-10-15"


def test_pending_cannot_commit(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="r")
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    with pytest.raises(InvalidStateError, match="pending"):
        commit_proposal(conn, team_id=TEAM_A, proposal_id=proposals[0].proposal_id)


def test_proposal_wrong_team_isolation(tmp_path: Path) -> None:
    conn, a, cycle = _setup_cycle(tmp_path)
    _seed_team(conn, TEAM_B, MEMBERS_B)
    payload = ProposalPayload(action_id=a.action_id, outcome="carry_over", reason="r")
    proposals = save_proposals(conn, team_id=TEAM_A, cycle_id=cycle.cycle_id, payloads=[payload])
    with pytest.raises(NotFoundError):
        decide_proposal(
            conn, team_id=TEAM_B, proposal_id=proposals[0].proposal_id, decision="approve"
        )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_write_logged_after_commit(tmp_path: Path) -> None:
    import app.core.logging_setup as ls

    conn = _make_conn(tmp_path)
    log_file = tmp_path / "store.log"
    ls.configure_logging(str(log_file))
    try:
        _seed_team(conn)
        _seed_action(conn)
    finally:
        logging.getLogger("meettrack").handlers.clear()
        ls._file_logger = None  # type: ignore[assignment]

    lines = [json.loads(ln) for ln in log_file.read_text().strip().splitlines() if ln.strip()]
    write_events = [ev for ev in lines if ev["event"] == "memory_write"]
    assert len(write_events) >= 2


def test_description_truncated_in_log(tmp_path: Path) -> None:
    import app.core.logging_setup as ls

    conn = _make_conn(tmp_path)
    log_file = tmp_path / "trunc.log"
    ls.configure_logging(str(log_file))
    try:
        _seed_team(conn)
        mtg = _seed_meeting(conn)
        create_action(
            conn,
            team_id=TEAM_A,
            description="X" * 200,
            origin_meeting_id=mtg.meeting_id,
            owner="Bilal",
            due_date=None,
        )
    finally:
        logging.getLogger("meettrack").handlers.clear()
        ls._file_logger = None  # type: ignore[assignment]

    lines = [json.loads(ln) for ln in log_file.read_text().strip().splitlines() if ln.strip()]
    action_lines = [ev for ev in lines if ev.get("detail", {}).get("op") == "create_action"]
    assert action_lines
    assert len(action_lines[0]["detail"]["description"]) <= 83


# ---------------------------------------------------------------------------
# End-to-end restart simulation
# ---------------------------------------------------------------------------


def test_restart_simulation(tmp_path: Path) -> None:
    db_path = str(tmp_path / "restart.db")
    conn1 = get_conn(db_path)
    run_migrations(conn1)
    init_team(conn1, team_id="R", name="Restart Team", members=[MemberInput(name="Alice")])
    mtg = add_meeting(
        conn1, team_id="R", meeting_date="2026-10-05", file_name="m.txt", file_hash="rr1"
    )
    a = create_action(
        conn1,
        team_id="R",
        description="Initial",
        origin_meeting_id=mtg.meeting_id,
        owner="Alice",
        due_date="2026-10-20",
    )
    new_version(
        conn1,
        team_id="R",
        action_id=a.action_id,
        changed_by="agent_approved",
        due_date="2026-10-25",
    )
    conn1.close()

    conn2 = get_conn(db_path)
    open_actions = get_open_actions(conn2, team_id="R")
    assert len(open_actions) == 1
    assert open_actions[0].due_date == "2026-10-25"
    hist = get_history(conn2, team_id="R", action_id=a.action_id)
    assert len(hist) == 2
    assert hist[0].due_date == "2026-10-20"
    assert hist[1].due_date == "2026-10-25"
    conn2.close()
