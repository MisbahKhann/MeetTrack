"""action_store -- the memory layer for MeetTrack.



All reads and writes to teams, members, meetings, actions, action_versions,

proposals, user_decisions, cycles and action_log go through this module.



Hard rules enforced here:

- Every query is scoped by team_id (rule 8).

- LLM never writes to the DB; only approved proposals can commit (rule 6).

- Corrections create a new version; old values are never deleted (rule 7).

- Same file hash twice raises DuplicateFileError for the same team (rule 9).

- Logs are written AFTER successful commits, never before (rule 12).

"""



import sqlite3

import uuid

from datetime import date

from typing import Any, Literal



from pydantic import BaseModel, Field, field_validator



from app.core.logging_setup import log_event

from app.db.connection import transaction, utc_now



# ---------------------------------------------------------------------------

# Sentinel for "not supplied" (distinct from None which is a real value)

# ---------------------------------------------------------------------------



_UNSET: Any = object()

UNSET = _UNSET  # exported for callers



_VALID_STATUSES = frozenset({"open", "done", "blocked", "needs_clarification"})

_VALID_OUTCOMES = frozenset(

    {

        "close_with_evidence",

        "carry_over",

        "mark_blocked",

        "ask_question",

        "draft_reminder",

        "new_action",

    }

)

_VALID_CHANGED_BY = frozenset({"agent_approved", "user_correction"})





# ---------------------------------------------------------------------------

# Exceptions

# ---------------------------------------------------------------------------





class StoreError(Exception):

    """Base exception for action_store errors."""





class NotFoundError(StoreError):

    """Entity not found, or belongs to another team."""





class DuplicateFileError(StoreError):

    """Same file hash already ingested for this team."""





class ValidationError(StoreError):

    """Bad owner, date, or field value."""





class InvalidStateError(StoreError):

    """Operation not allowed in the current state."""





class NoChangeError(StoreError):

    """new_version called but nothing would change."""





# ---------------------------------------------------------------------------

# Input models

# ---------------------------------------------------------------------------





class MemberInput(BaseModel, frozen=True, extra="forbid"):

    name: str



    @field_validator("name")

    @classmethod

    def name_not_empty(cls, v: str) -> str:

        if not v.strip():

            raise ValueError("Member name must not be empty")

        return v.strip()





class ProposalPayload(BaseModel, frozen=True, extra="forbid"):

    """Agent suggestion payload."""



    action_id: str | None = None

    outcome: str

    description: str | None = None

    owner: str | None = None

    due_date: str | None = None

    blocked_reason: str | None = None

    question: str | None = None

    source_meeting_id: str | None = None

    source_line: int | None = None

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    evidence_line: int | None = None

    evidence_quote: str | None = None

    reason: str



    @field_validator("outcome")

    @classmethod

    def valid_outcome(cls, v: str) -> str:

        if v not in _VALID_OUTCOMES:

            raise ValueError(f"Invalid outcome {v!r}. Must be one of {sorted(_VALID_OUTCOMES)}")

        return v





# ---------------------------------------------------------------------------

# Return models

# ---------------------------------------------------------------------------





class TeamRecord(BaseModel, frozen=True):

    team_id: str

    name: str

    supervisor: str | None



    @property

    def id(self) -> str:

        return self.team_id





class MemberRecord(BaseModel, frozen=True):

    member_id: str

    team_id: str

    name: str



    @property

    def id(self) -> str:

        return self.member_id





class MeetingRecord(BaseModel, frozen=True):

    meeting_id: str

    team_id: str

    meeting_date: str

    file_name: str

    file_hash: str



    @property

    def id(self) -> str:

        return self.meeting_id





class ActionView(BaseModel, frozen=True):

    action_id: str

    action_code: str

    team_id: str

    description: str

    origin_meeting_id: str

    owner: str | None

    due_date: str | None

    status: str

    blocked_reason: str | None

    version_no: int

    source_meeting_id: str | None

    source_line: int | None

    confidence: float | None

    changed_by: str

    valid_from: str



    @property

    def id(self) -> str:

        return self.action_id





class VersionRecord(ActionView, frozen=True):

    is_current: int

    superseded_at: str | None





class CycleRecord(BaseModel, frozen=True):

    cycle_id: str

    team_id: str

    meeting_id: str

    as_of: str | None

    state: str



    @property

    def id(self) -> str:

        return self.cycle_id





class ProposalRecord(BaseModel, frozen=True):

    proposal_id: str

    cycle_id: str

    team_id: str

    action_id: str | None

    outcome: str

    payload_json: str

    status: str

    committed_at: str | None



    @property

    def id(self) -> str:

        return self.proposal_id





class DecisionRecord(BaseModel, frozen=True):

    decision_id: str

    proposal_id: str

    team_id: str

    decision: str

    edited_payload_json: str | None

    comment: str | None

    decided_at: str



    @property

    def id(self) -> str:

        return self.decision_id





class ReminderRecord(BaseModel, frozen=True):

    reminder_id: str

    team_id: str

    action_id: str

    cycle_id: str

    idempotency_key: str

    recipient_name: str

    draft_text: str

    status: str

    created_at: str



    @property

    def id(self) -> str:

        return self.reminder_id







class CommitResult(BaseModel, frozen=True):

    proposal_id: str

    already_committed: bool

    outcome: str

    action_id: str | None





# ---------------------------------------------------------------------------

# Internal helpers

# ---------------------------------------------------------------------------





def _uid() -> str:

    return str(uuid.uuid4())





def _require_team(conn: sqlite3.Connection, team_id: str) -> None:

    row = conn.execute("SELECT 1 FROM teams WHERE id = ?", (team_id,)).fetchone()

    if row is None:

        raise NotFoundError(f"Team {team_id!r} not found")





def _parse_date(value: str | None, field: str = "due_date") -> None:

    if value is None:

        return

    try:

        date.fromisoformat(value)

    except ValueError as exc:

        raise ValidationError(

            f"{field} must be a valid ISO date (yyyy-mm-dd); got {value!r}"

        ) from exc





def _truncate(s: str, max_len: int = 80) -> str:

    return s[:max_len] + "..." if len(s) > max_len else s





# ---------------------------------------------------------------------------

# Action version query helper

# ---------------------------------------------------------------------------



_AV_SELECT = """

    SELECT

        a.id            AS action_id,

        a.action_code,

        a.team_id,

        v.description,

        a.meeting_id    AS origin_meeting_id,

        v.owner,

        v.due_date,

        v.status,

        v.blocked_reason,

        v.version_no,

        v.source_meeting_id,

        a.source_line,

        v.confidence,

        v.changed_by,

        v.valid_from,

        v.is_current,

        v.superseded_at

    FROM actions a

    JOIN action_versions v ON v.action_id = a.id

"""





def _row_to_action_view(row: sqlite3.Row) -> ActionView:

    return ActionView(

        action_id=row["action_id"],

        action_code=row["action_code"],

        team_id=row["team_id"],

        description=row["description"],

        origin_meeting_id=row["origin_meeting_id"],

        owner=row["owner"],

        due_date=row["due_date"],

        status=row["status"],

        blocked_reason=row["blocked_reason"],

        version_no=row["version_no"],

        source_meeting_id=row["source_meeting_id"],

        source_line=row["source_line"],

        confidence=row["confidence"],

        changed_by=row["changed_by"],

        valid_from=row["valid_from"],

    )





def _row_to_version_record(row: sqlite3.Row) -> VersionRecord:

    return VersionRecord(

        action_id=row["action_id"],

        action_code=row["action_code"],

        team_id=row["team_id"],

        description=row["description"],

        origin_meeting_id=row["origin_meeting_id"],

        owner=row["owner"],

        due_date=row["due_date"],

        status=row["status"],

        blocked_reason=row["blocked_reason"],

        version_no=row["version_no"],

        source_meeting_id=row["source_meeting_id"],

        source_line=row["source_line"],

        confidence=row["confidence"],

        changed_by=row["changed_by"],

        valid_from=row["valid_from"],

        is_current=row["is_current"],

        superseded_at=row["superseded_at"],

    )





# ---------------------------------------------------------------------------

# Teams and members

# ---------------------------------------------------------------------------





def init_team(

    conn: sqlite3.Connection,

    *,

    team_id: str | None = None,

    name: str,

    supervisor: str | None = None,

    members: list[Any],

) -> TeamRecord:

    """Create a team idempotently. Conflicting data raises ValidationError."""

    if team_id is None:

        team_id = _uid()



    existing = conn.execute(

        "SELECT id, name, supervisor FROM teams WHERE id = ?", (team_id,)

    ).fetchone()



    if existing is not None:

        if existing["name"] != name:

            raise ValidationError(f"Team {team_id!r} already exists with name {existing['name']!r}")

        return TeamRecord(

            team_id=existing["id"],

            name=existing["name"],

            supervisor=existing["supervisor"],

        )



    member_inputs: list[MemberInput] = []

    for m in members:

        if isinstance(m, MemberInput):

            member_inputs.append(m)

        elif isinstance(m, str):

            member_inputs.append(MemberInput(name=m))

        elif isinstance(m, dict):

            member_inputs.append(MemberInput(**m))

        else:

            member_inputs.append(MemberInput(name=str(m)))



    lower_names = [m.name.lower() for m in member_inputs]

    if len(lower_names) != len(set(lower_names)):

        raise ValidationError("Member names must be unique within a team (case-insensitive)")



    now = utc_now()

    with transaction(conn):

        conn.execute(

            "INSERT INTO teams (id, name, supervisor, created_at) VALUES (?, ?, ?, ?)",

            (team_id, name, supervisor, now),

        )

        for member in member_inputs:

            conn.execute(

                "INSERT INTO members (id, team_id, name, created_at) VALUES (?, ?, ?, ?)",

                (_uid(), team_id, member.name, now),

            )

        conn.execute(

            "INSERT INTO action_counters (team_id, last_number) VALUES (?, 0)",

            (team_id,),

        )



    log_event("memory_write", {"op": "init_team", "team_id": team_id})

    return TeamRecord(team_id=team_id, name=name, supervisor=supervisor)





def add_member(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    name: str,

    email: str | None = None,

) -> MemberRecord:

    """Add a new member to an existing team."""

    _require_team(conn, team_id)

    clean_name = name.strip()

    if not clean_name:

        raise ValidationError("Member name must not be empty")



    existing = conn.execute(

        "SELECT id FROM members WHERE team_id = ? AND lower(name) = lower(?)",

        (team_id, clean_name),

    ).fetchone()

    if existing is not None:

        raise ValidationError(f"Member {clean_name!r} already exists in team {team_id!r}")



    mid = _uid()

    now = utc_now()

    with transaction(conn):

        conn.execute(

            "INSERT INTO members (id, team_id, name, email, created_at) VALUES (?, ?, ?, ?, ?)",

            (mid, team_id, clean_name, email, now),

        )



    log_event("memory_write", {"op": "add_member", "team_id": team_id, "member_id": mid})

    return MemberRecord(member_id=mid, team_id=team_id, name=clean_name)





def get_team(conn: sqlite3.Connection, *, team_id: str) -> TeamRecord:

    row = conn.execute("SELECT id, name, supervisor FROM teams WHERE id = ?", (team_id,)).fetchone()

    if row is None:

        raise NotFoundError(f"Team {team_id!r} not found")

    log_event("memory_read", {"op": "get_team", "team_id": team_id})

    return TeamRecord(team_id=row["id"], name=row["name"], supervisor=row["supervisor"])





def list_members(conn: sqlite3.Connection, *, team_id: str) -> list[MemberRecord]:

    _require_team(conn, team_id)

    rows = conn.execute(

        "SELECT id, team_id, name FROM members WHERE team_id = ? ORDER BY name",

        (team_id,),

    ).fetchall()

    log_event("memory_read", {"op": "list_members", "team_id": team_id})

    return [MemberRecord(member_id=r["id"], team_id=r["team_id"], name=r["name"]) for r in rows]





def resolve_member(conn: sqlite3.Connection, *, team_id: str, name: str) -> str | None:

    row = conn.execute(

        "SELECT name FROM members WHERE team_id = ? AND lower(name) = lower(?)",

        (team_id, name),

    ).fetchone()

    return row["name"] if row else None





# ---------------------------------------------------------------------------

# Meetings

# ---------------------------------------------------------------------------





def file_seen(conn: sqlite3.Connection, *, team_id: str, file_hash: str) -> bool:

    row = conn.execute(

        "SELECT 1 FROM meetings WHERE team_id = ? AND file_hash = ?",

        (team_id, file_hash),

    ).fetchone()

    log_event("memory_read", {"op": "file_seen", "team_id": team_id})

    return row is not None





def add_meeting(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    meeting_date: str,

    file_name: str,

    file_hash: str,

) -> MeetingRecord:

    """Register a new meeting. Raises DuplicateFileError on duplicate hash."""

    _require_team(conn, team_id)

    _parse_date(meeting_date, "meeting_date")



    if file_seen(conn, team_id=team_id, file_hash=file_hash):

        raise DuplicateFileError(f"File {file_hash[:12]}... already ingested for team {team_id!r}")



    now = utc_now()

    meeting_id = _uid()

    with transaction(conn):

        conn.execute(

            "INSERT INTO meetings (id, team_id, filename, file_hash, as_of_date, uploaded_at) "

            "VALUES (?, ?, ?, ?, ?, ?)",

            (meeting_id, team_id, file_name, file_hash, meeting_date, now),

        )



    log_event(

        "memory_write",

        {"op": "add_meeting", "team_id": team_id, "meeting_id": meeting_id},

    )

    return MeetingRecord(

        meeting_id=meeting_id,

        team_id=team_id,

        meeting_date=meeting_date,

        file_name=file_name,

        file_hash=file_hash,

    )





def get_meeting_by_hash(

    conn: sqlite3.Connection, *, team_id: str, file_hash: str

) -> MeetingRecord | None:

    """Return the meeting for this team+hash, or None if not found."""

    row = conn.execute(

        "SELECT id, team_id, as_of_date, filename, file_hash "

        "FROM meetings WHERE team_id = ? AND file_hash = ?",

        (team_id, file_hash),

    ).fetchone()

    log_event("memory_read", {"op": "get_meeting_by_hash", "team_id": team_id})

    if row is None:

        return None

    return MeetingRecord(

        meeting_id=row["id"],

        team_id=row["team_id"],

        meeting_date=row["as_of_date"],

        file_name=row["filename"],

        file_hash=row["file_hash"],

    )





# ---------------------------------------------------------------------------

# Actions and versions

# ---------------------------------------------------------------------------





def next_action_id(conn: sqlite3.Connection, *, team_id: str) -> str:

    """Atomically allocate the next action_code for this team."""

    row = conn.execute(

        "SELECT last_number FROM action_counters WHERE team_id = ?", (team_id,)

    ).fetchone()

    if row is None:

        raise NotFoundError(f"Team {team_id!r} not found in action_counters")

    new_number = row["last_number"] + 1

    conn.execute(

        "UPDATE action_counters SET last_number = ? WHERE team_id = ?",

        (new_number, team_id),

    )

    return f"{team_id}-{new_number:03d}"





def create_action(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    description: str,

    origin_meeting_id: str,

    owner: str | None,

    due_date: str | None,

    status: str = "open",

    source_line: int | None = None,

    source_meeting_id: str | None = None,

    confidence: float | None = None,

    changed_by: str = "agent_approved",

    proposal_id: str | None = None,

) -> ActionView:

    """Create a new action with version 1."""

    _require_team(conn, team_id)



    if owner is not None:

        canonical = resolve_member(conn, team_id=team_id, name=owner)

        if canonical is None:

            raise ValidationError(f"Owner {owner!r} is not a member of team {team_id!r}")

        owner = canonical

    else:

        status = "needs_clarification"



    _parse_date(due_date)



    if status not in _VALID_STATUSES:

        raise ValidationError(f"Invalid status {status!r}")

    if changed_by not in _VALID_CHANGED_BY:

        raise ValidationError(f"Invalid changed_by {changed_by!r}")



    now = utc_now()

    action_db_id = _uid()

    version_id = _uid()



    with transaction(conn):

        action_code = next_action_id(conn, team_id=team_id)

        conn.execute(

            "INSERT INTO actions (id, team_id, action_code, source_line, meeting_id, created_at)"

            " VALUES (?, ?, ?, ?, ?, ?)",

            (action_db_id, team_id, action_code, source_line or 0, origin_meeting_id, now),

        )

        conn.execute(

            """INSERT INTO action_versions

               (id, action_id, team_id, version_no, description, owner, due_date,

                status, blocked_reason, source_meeting_id, confidence,

                changed_by, is_current, valid_from, superseded_at, proposal_id)

               VALUES (?, ?, ?, 1, ?, ?, ?, ?, NULL, ?, ?, ?, 1, ?, NULL, ?)""",

            (

                version_id,

                action_db_id,

                team_id,

                description,

                owner,

                due_date,

                status,

                source_meeting_id,

                confidence,

                changed_by,

                now,

                proposal_id,

            ),

        )



    log_event(

        "memory_write",

        {

            "op": "create_action",

            "team_id": team_id,

            "action_id": action_db_id,

            "description": _truncate(description),

        },

    )

    return get_current(conn, team_id=team_id, action_id=action_db_id)





def _get_current_raw(conn: sqlite3.Connection, *, team_id: str, action_id: str) -> sqlite3.Row:

    row = conn.execute(

        _AV_SELECT + " WHERE a.id = ? AND a.team_id = ? AND v.is_current = 1",

        (action_id, team_id),

    ).fetchone()

    if row is None:

        raise NotFoundError(f"Action {action_id!r} not found for team {team_id!r}")

    return row





def get_current(conn: sqlite3.Connection, *, team_id: str, action_id: str) -> ActionView:

    row = _get_current_raw(conn, team_id=team_id, action_id=action_id)

    log_event("memory_read", {"op": "get_current", "team_id": team_id, "action_id": action_id})

    return _row_to_action_view(row)





def new_version(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    action_id: str,

    changed_by: str,

    owner: Any = _UNSET,

    due_date: Any = _UNSET,

    status: Any = _UNSET,

    blocked_reason: Any = _UNSET,

    source_meeting_id: Any = _UNSET,

    confidence: Any = _UNSET,

    proposal_id: str | None = None,

) -> ActionView:

    """Create a new version, superseding the current one."""

    current = _get_current_raw(conn, team_id=team_id, action_id=action_id)



    if changed_by not in _VALID_CHANGED_BY:

        raise ValidationError(f"Invalid changed_by {changed_by!r}")



    new_owner = current["owner"] if owner is _UNSET else owner

    new_due = current["due_date"] if due_date is _UNSET else due_date

    new_status = current["status"] if status is _UNSET else status

    new_blocked = current["blocked_reason"] if blocked_reason is _UNSET else blocked_reason

    new_src_mtg = current["source_meeting_id"] if source_meeting_id is _UNSET else source_meeting_id

    new_conf = current["confidence"] if confidence is _UNSET else confidence



    if (

        new_owner == current["owner"]

        and new_due == current["due_date"]

        and new_status == current["status"]

        and new_blocked == current["blocked_reason"]

        and new_src_mtg == current["source_meeting_id"]

        and new_conf == current["confidence"]

    ):

        raise NoChangeError(f"No fields changed for action {action_id!r}")



    if new_owner is not None:

        canonical = resolve_member(conn, team_id=team_id, name=new_owner)

        if canonical is None:

            raise ValidationError(f"Owner {new_owner!r} is not a member of team {team_id!r}")

        new_owner = canonical



    _parse_date(new_due)



    if new_status not in _VALID_STATUSES:

        raise ValidationError(f"Invalid status {new_status!r}")



    new_version_no = current["version_no"] + 1

    now = utc_now()

    version_id = _uid()



    with transaction(conn):

        conn.execute(

            "UPDATE action_versions SET is_current = 0, superseded_at = ? "

            "WHERE action_id = ? AND team_id = ? AND is_current = 1",

            (now, action_id, team_id),

        )

        conn.execute(

            """INSERT INTO action_versions

               (id, action_id, team_id, version_no, description, owner, due_date,

                status, blocked_reason, source_meeting_id, confidence,

                changed_by, is_current, valid_from, superseded_at, proposal_id)

               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, ?)""",

            (

                version_id,

                action_id,

                team_id,

                new_version_no,

                current["description"],

                new_owner,

                new_due,

                new_status,

                new_blocked,

                new_src_mtg,

                new_conf,

                changed_by,

                now,

                proposal_id,

            ),

        )



    log_event(

        "memory_write",

        {

            "op": "new_version",

            "team_id": team_id,

            "action_id": action_id,

            "version_no": new_version_no,

        },

    )

    return get_current(conn, team_id=team_id, action_id=action_id)





def list_actions(

    conn: sqlite3.Connection, *, team_id: str, include_done: bool = True

) -> list[ActionView]:

    _require_team(conn, team_id)

    if include_done:

        rows = conn.execute(

            _AV_SELECT + " WHERE a.team_id = ? AND v.is_current = 1 ORDER BY a.action_code",

            (team_id,),

        ).fetchall()

    else:

        rows = conn.execute(

            _AV_SELECT + " WHERE a.team_id = ? AND v.is_current = 1 AND v.status != 'done'"

            " ORDER BY a.action_code",

            (team_id,),

        ).fetchall()

    log_event("memory_read", {"op": "list_actions", "team_id": team_id, "count": len(rows)})

    return [_row_to_action_view(r) for r in rows]





def get_open_actions(conn: sqlite3.Connection, *, team_id: str) -> list[ActionView]:

    _require_team(conn, team_id)

    rows = conn.execute(

        _AV_SELECT + " WHERE a.team_id = ? AND v.is_current = 1 AND v.status != 'done'"

        " ORDER BY a.action_code",

        (team_id,),

    ).fetchall()

    log_event("memory_read", {"op": "get_open_actions", "team_id": team_id, "count": len(rows)})

    return [_row_to_action_view(r) for r in rows]





def get_history(conn: sqlite3.Connection, *, team_id: str, action_id: str) -> list[VersionRecord]:

    _get_current_raw(conn, team_id=team_id, action_id=action_id)  # ownership check

    rows = conn.execute(

        _AV_SELECT + " WHERE a.id = ? AND a.team_id = ? ORDER BY v.version_no ASC",

        (action_id, team_id),

    ).fetchall()

    log_event("memory_read", {"op": "get_history", "team_id": team_id, "action_id": action_id})

    return [_row_to_version_record(r) for r in rows]





def correct_action(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    action_id: str,

    field: str,

    value: Any,

    comment: str | None = None,

) -> ActionView:

    allowed_fields = {"owner", "due_date", "status"}

    if field not in allowed_fields:

        raise ValidationError(f"Correctable fields are {sorted(allowed_fields)}; got {field!r}")

    kwargs: dict[str, Any] = {field: value, "changed_by": "user_correction"}

    result = new_version(conn, team_id=team_id, action_id=action_id, **kwargs)

    log_event(

        "approval",

        {

            "op": "correct_action",

            "team_id": team_id,

            "action_id": action_id,

            "field": field,

            "comment": comment,

        },

    )

    return result





# ---------------------------------------------------------------------------

# Cycles

# ---------------------------------------------------------------------------





def create_cycle(

    conn: sqlite3.Connection, *, team_id: str, meeting_id: str, as_of: str

) -> CycleRecord:

    """Create or return existing cycle for this meeting (idempotent)."""

    _require_team(conn, team_id)

    cycle_id = f"{team_id}-{meeting_id}"



    existing = conn.execute(

        "SELECT id, team_id, meeting_id, as_of, state FROM cycles " "WHERE id = ? AND team_id = ?",

        (cycle_id, team_id),

    ).fetchone()

    if existing is not None:

        return CycleRecord(

            cycle_id=existing["id"],

            team_id=existing["team_id"],

            meeting_id=existing["meeting_id"],

            as_of=existing["as_of"],

            state=existing["state"],

        )



    now = utc_now()

    with transaction(conn):

        conn.execute(

            "INSERT INTO cycles (id, team_id, meeting_id, as_of, state, created_at, updated_at)"

            " VALUES (?, ?, ?, ?, 'extracted', ?, ?)",

            (cycle_id, team_id, meeting_id, as_of, now, now),

        )



    log_event(

        "memory_write",

        {"op": "create_cycle", "team_id": team_id, "cycle_id": cycle_id},

    )

    return CycleRecord(

        cycle_id=cycle_id, team_id=team_id, meeting_id=meeting_id, as_of=as_of, state="extracted"

    )





def get_cycle(conn: sqlite3.Connection, *, team_id: str, cycle_id: str) -> CycleRecord:

    row = conn.execute(

        "SELECT id, team_id, meeting_id, as_of, state FROM cycles " "WHERE id = ? AND team_id = ?",

        (cycle_id, team_id),

    ).fetchone()

    if row is None:

        raise NotFoundError(f"Cycle {cycle_id!r} not found for team {team_id!r}")

    log_event("memory_read", {"op": "get_cycle", "team_id": team_id, "cycle_id": cycle_id})

    return CycleRecord(

        cycle_id=row["id"],

        team_id=row["team_id"],

        meeting_id=row["meeting_id"],

        as_of=row["as_of"],

        state=row["state"],

    )





_CYCLE_TRANSITIONS = {"extracted": "proposed", "proposed": "committed"}





def set_cycle_state(

    conn: sqlite3.Connection, *, team_id: str, cycle_id: str, state: str

) -> CycleRecord:

    cycle = get_cycle(conn, team_id=team_id, cycle_id=cycle_id)

    expected = _CYCLE_TRANSITIONS.get(cycle.state)

    if expected != state:

        raise InvalidStateError(

            f"Cycle {cycle_id!r} is in state {cycle.state!r}; " f"cannot transition to {state!r}"

        )

    now = utc_now()

    with transaction(conn):

        conn.execute(

            "UPDATE cycles SET state = ?, updated_at = ? WHERE id = ? AND team_id = ?",

            (state, now, cycle_id, team_id),

        )

    log_event(

        "memory_write",

        {"op": "set_cycle_state", "team_id": team_id, "cycle_id": cycle_id, "state": state},

    )

    return get_cycle(conn, team_id=team_id, cycle_id=cycle_id)





def finalize_cycle(conn: sqlite3.Connection, *, team_id: str, cycle_id: str) -> CycleRecord:

    pending = conn.execute(

        "SELECT COUNT(*) FROM proposals WHERE cycle_id = ? AND team_id = ? AND status = 'pending'",

        (cycle_id, team_id),

    ).fetchone()[0]

    if pending > 0:

        raise InvalidStateError(

            f"Cycle {cycle_id!r} has {pending} pending proposal(s); cannot finalize"

        )

    return set_cycle_state(conn, team_id=team_id, cycle_id=cycle_id, state="committed")





# ---------------------------------------------------------------------------

# Proposals and approvals

# ---------------------------------------------------------------------------





def save_proposals(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    cycle_id: str,

    payloads: list[ProposalPayload],

) -> list[ProposalRecord]:

    """Save proposals idempotently. Second call returns existing rows unchanged."""

    cycle = get_cycle(conn, team_id=team_id, cycle_id=cycle_id)



    existing = conn.execute(

        "SELECT id, cycle_id, team_id, action_id, outcome, payload_json, status, committed_at "

        "FROM proposals WHERE cycle_id = ? AND team_id = ?",

        (cycle_id, team_id),

    ).fetchall()

    if existing:

        return [

            ProposalRecord(

                proposal_id=r["id"],

                cycle_id=r["cycle_id"],

                team_id=r["team_id"],

                action_id=r["action_id"],

                outcome=r["outcome"],

                payload_json=r["payload_json"],

                status=r["status"],

                committed_at=r["committed_at"],

            )

            for r in existing

        ]



    if cycle.state != "extracted":

        raise InvalidStateError(

            f"Cycle {cycle_id!r} is in state {cycle.state!r}; "

            "proposals can only be saved in 'extracted' state"

        )



    records: list[ProposalRecord] = []

    now = utc_now()

    with transaction(conn):

        for payload in payloads:

            pid = _uid()

            payload_json = payload.model_dump_json()

            conn.execute(

                "INSERT INTO proposals "

                "(id, cycle_id, team_id, action_id, outcome, payload_json,"

                " rationale, evidence_quote, status, created_at) "

                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",

                (

                    pid,

                    cycle_id,

                    team_id,

                    payload.action_id,

                    payload.outcome,

                    payload_json,

                    payload.reason,

                    payload.evidence_quote,

                    now,

                ),

            )

            records.append(

                ProposalRecord(

                    proposal_id=pid,

                    cycle_id=cycle_id,

                    team_id=team_id,

                    action_id=payload.action_id,

                    outcome=payload.outcome,

                    payload_json=payload_json,

                    status="pending",

                    committed_at=None,

                )

            )

        conn.execute(

            "UPDATE cycles SET state = 'proposed', updated_at = ? " "WHERE id = ? AND team_id = ?",

            (now, cycle_id, team_id),

        )



    log_event(

        "memory_write",

        {

            "op": "save_proposals",

            "team_id": team_id,

            "cycle_id": cycle_id,

            "count": len(records),

        },

    )

    return records





def list_proposals(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    cycle_id: str,

    status: str | None = None,

) -> list[ProposalRecord]:

    query = (

        "SELECT id, cycle_id, team_id, action_id, outcome, payload_json, status, committed_at "

        "FROM proposals WHERE cycle_id = ? AND team_id = ?"

    )

    params: list[Any] = [cycle_id, team_id]

    if status is not None:

        query += " AND status = ?"

        params.append(status)

    rows = conn.execute(query, params).fetchall()

    log_event("memory_read", {"op": "list_proposals", "team_id": team_id, "cycle_id": cycle_id})

    return [

        ProposalRecord(

            proposal_id=r["id"],

            cycle_id=r["cycle_id"],

            team_id=r["team_id"],

            action_id=r["action_id"],

            outcome=r["outcome"],

            payload_json=r["payload_json"],

            status=r["status"],

            committed_at=r["committed_at"],

        )

        for r in rows

    ]





def _get_proposal(conn: sqlite3.Connection, *, team_id: str, proposal_id: str) -> sqlite3.Row:

    row = conn.execute(

        "SELECT id, cycle_id, team_id, action_id, outcome, "

        "payload_json, status, committed_at "

        "FROM proposals WHERE id = ? AND team_id = ?",

        (proposal_id, team_id),

    ).fetchone()

    if row is None:

        raise NotFoundError(f"Proposal {proposal_id!r} not found for team {team_id!r}")

    return row





def decide_proposal(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    proposal_id: str,

    decision: Literal["approve", "edit", "reject"],

    edited_payload: ProposalPayload | None = None,

    comment: str | None = None,

) -> DecisionRecord:

    proposal = _get_proposal(conn, team_id=team_id, proposal_id=proposal_id)



    if proposal["status"] != "pending":

        raise InvalidStateError(

            f"Proposal {proposal_id!r} already has status {proposal['status']!r}"

        )



    existing = conn.execute(

        "SELECT 1 FROM user_decisions WHERE proposal_id = ?", (proposal_id,)

    ).fetchone()

    if existing is not None:

        raise InvalidStateError(f"A decision already exists for proposal {proposal_id!r}")



    if decision == "edit" and edited_payload is None:

        raise ValidationError("An edited_payload is required when decision is 'edit'")



    if isinstance(edited_payload, dict):
        edited_payload = ProposalPayload.model_validate(edited_payload)

    edited_json = edited_payload.model_dump_json() if edited_payload is not None else None

    now = utc_now()

    canonical_map = {

        "approve": "approve",

        "approved": "approve",

        "edit": "edit",

        "edited": "edit",

        "reject": "reject",

        "rejected": "reject",

    }

    if decision not in canonical_map:

        raise ValidationError(f"Invalid decision {decision!r}")

    canonical_decision = canonical_map[decision]



    status_map = {"approve": "approved", "edit": "edited", "reject": "rejected"}

    new_status = status_map[canonical_decision]

    did = _uid()



    with transaction(conn):

        conn.execute(

            "INSERT INTO user_decisions "

            "(id, proposal_id, team_id, decision, edited_payload_json, "

            " decided_at, decided_by) "

            "VALUES (?, ?, ?, ?, ?, ?, 'user')",

            (did, proposal_id, team_id, canonical_decision, edited_json, now),

        )

        conn.execute(

            "UPDATE proposals SET status = ? WHERE id = ? AND team_id = ?",

            (new_status, proposal_id, team_id),

        )



    log_event(

        "approval",

        {

            "op": "decide_proposal",

            "team_id": team_id,

            "proposal_id": proposal_id,

            "decision": canonical_decision,

        },

    )

    return DecisionRecord(

        decision_id=did,

        proposal_id=proposal_id,

        team_id=team_id,

        decision=canonical_decision,

        edited_payload_json=edited_json,

        comment=comment,

        decided_at=now,

    )





def commit_proposal(conn: sqlite3.Connection, *, team_id: str, proposal_id: str) -> CommitResult:

    proposal = _get_proposal(conn, team_id=team_id, proposal_id=proposal_id)



    if proposal["committed_at"] is not None:

        return CommitResult(

            proposal_id=proposal_id,

            already_committed=True,

            outcome=proposal["outcome"],

            action_id=proposal["action_id"],

        )



    if proposal["status"] not in ("approved", "edited"):

        raise InvalidStateError(

            f"Proposal {proposal_id!r} has status {proposal['status']!r}; "

            "only approved or edited proposals can be committed"

        )



    dec_row = conn.execute(

        "SELECT edited_payload_json FROM user_decisions WHERE proposal_id = ?",

        (proposal_id,),

    ).fetchone()

    if dec_row and dec_row["edited_payload_json"]:

        effective = ProposalPayload.model_validate_json(dec_row["edited_payload_json"])

    else:

        effective = ProposalPayload.model_validate_json(proposal["payload_json"])



    outcome = effective.outcome

    action_id: str | None = proposal["action_id"]

    now = utc_now()



    with transaction(conn):

        if outcome == "new_action":

            if effective.description is None:

                raise ValidationError("new_action requires description in payload")

            cycle_row = conn.execute(

                "SELECT meeting_id FROM cycles WHERE id = "

                "(SELECT cycle_id FROM proposals WHERE id = ?)",

                (proposal_id,),

            ).fetchone()

            new_act = create_action(

                conn,

                team_id=team_id,

                description=effective.description,

                origin_meeting_id=cycle_row["meeting_id"],

                owner=effective.owner,

                due_date=effective.due_date,

                source_line=effective.source_line,

                source_meeting_id=effective.source_meeting_id,

                confidence=effective.confidence,

                changed_by="agent_approved",

                proposal_id=proposal_id,

            )

            action_id = new_act.action_id



        elif outcome == "close_with_evidence":

            try:

                new_version(

                    conn,

                    team_id=team_id,

                    action_id=action_id,  # type: ignore[arg-type]

                    changed_by="agent_approved",

                    status="done",

                    proposal_id=proposal_id,

                )

            except NoChangeError:

                pass



        elif outcome == "mark_blocked":

            if effective.blocked_reason is None:

                raise ValidationError("mark_blocked requires blocked_reason in payload")

            try:

                new_version(

                    conn,

                    team_id=team_id,

                    action_id=action_id,  # type: ignore[arg-type]

                    changed_by="agent_approved",

                    status="blocked",

                    blocked_reason=effective.blocked_reason,

                    proposal_id=proposal_id,

                )

            except NoChangeError:

                pass



        elif outcome == "ask_question":

            try:

                new_version(

                    conn,

                    team_id=team_id,

                    action_id=action_id,  # type: ignore[arg-type]

                    changed_by="agent_approved",

                    status="needs_clarification",

                    proposal_id=proposal_id,

                )

            except NoChangeError:

                pass



        elif outcome == "carry_over":

            carry_kw: dict[str, Any] = {

                "changed_by": "agent_approved",

                "proposal_id": proposal_id,

            }

            if effective.owner is not None:

                carry_kw["owner"] = effective.owner

            if effective.due_date is not None:

                carry_kw["due_date"] = effective.due_date

            try:

                new_version(conn, team_id=team_id, action_id=action_id, **carry_kw)  # type: ignore[arg-type]

            except NoChangeError:

                pass



        elif outcome == "draft_reminder":

            pass  # reminder drafts created in Step 9



        conn.execute(

            "UPDATE proposals SET committed_at = ? WHERE id = ? AND team_id = ?",

            (now, proposal_id, team_id),

        )



    log_event(

        "memory_write",

        {

            "op": "commit_proposal",

            "team_id": team_id,

            "proposal_id": proposal_id,

            "outcome": outcome,

        },

    )

    return CommitResult(

        proposal_id=proposal_id,

        already_committed=False,

        outcome=outcome,

        action_id=action_id,

    )





# ---------------------------------------------------------------------------

# Teams and Meetings listings

# ---------------------------------------------------------------------------





def list_teams(conn: sqlite3.Connection) -> list[TeamRecord]:

    rows = conn.execute("SELECT id, name, supervisor FROM teams ORDER BY name").fetchall()

    return [TeamRecord(team_id=r["id"], name=r["name"], supervisor=r["supervisor"]) for r in rows]





def get_team(conn: sqlite3.Connection, *, team_id: str) -> TeamRecord:

    _require_team(conn, team_id)

    row = conn.execute("SELECT id, name, supervisor FROM teams WHERE id = ?", (team_id,)).fetchone()

    return TeamRecord(team_id=row["id"], name=row["name"], supervisor=row["supervisor"])





def delete_team(conn: sqlite3.Connection, *, team_id: str) -> None:
    """Delete a team and all its team-owned records cleanly.

    Raises:
        NotFoundError: If the team does not exist.
    """
    _require_team(conn, team_id)

    with transaction(conn):
        conn.execute("DELETE FROM user_decisions WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM reminders WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM action_versions WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM proposals WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM actions WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM cycles WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM meetings WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM members WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM action_counters WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM action_log WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    log_event(
        "memory_write",
        {"op": "delete_team", "team_id": team_id},
    )


def list_meetings(conn: sqlite3.Connection, *, team_id: str) -> list[MeetingRecord]:

    _require_team(conn, team_id)

    rows = conn.execute(

        "SELECT id, team_id, as_of_date, filename, file_hash FROM meetings "

        "WHERE team_id = ? ORDER BY as_of_date DESC, uploaded_at DESC",

        (team_id,),

    ).fetchall()

    return [

        MeetingRecord(

            meeting_id=r["id"],

            team_id=r["team_id"],

            meeting_date=r["as_of_date"] or "",

            file_name=r["filename"],

            file_hash=r["file_hash"],

        )

        for r in rows

    ]





# ---------------------------------------------------------------------------

# Reminders

# ---------------------------------------------------------------------------





def save_reminder(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    action_id: str,

    cycle_id: str,

    idempotency_key: str,

    recipient_name: str,

    draft_text: str,

) -> ReminderRecord:

    _require_team(conn, team_id)

    existing = conn.execute(

        "SELECT id, team_id, action_id, cycle_id, idempotency_key, recipient_name, draft_text, status, created_at "

        "FROM reminders WHERE idempotency_key = ?",

        (idempotency_key,),

    ).fetchone()

    if existing is not None:

        return ReminderRecord(

            reminder_id=existing["id"],

            team_id=existing["team_id"],

            action_id=existing["action_id"],

            cycle_id=existing["cycle_id"],

            idempotency_key=existing["idempotency_key"],

            recipient_name=existing["recipient_name"],

            draft_text=existing["draft_text"],

            status=existing["status"],

            created_at=existing["created_at"],

        )



    rid = _uid()

    now = utc_now()

    with transaction(conn):

        conn.execute(

            "INSERT INTO reminders "

            "(id, team_id, action_id, cycle_id, idempotency_key, recipient_name, draft_text, status, created_at) "

            "VALUES (?, ?, ?, ?, ?, ?, ?, 'UNSENT', ?)",

            (rid, team_id, action_id, cycle_id, idempotency_key, recipient_name, draft_text, now),

        )



    log_event(

        "memory_write",

        {

            "op": "save_reminder",

            "team_id": team_id,

            "action_id": action_id,

            "cycle_id": cycle_id,

            "reminder_id": rid,

        },

    )

    return ReminderRecord(

        reminder_id=rid,

        team_id=team_id,

        action_id=action_id,

        cycle_id=cycle_id,

        idempotency_key=idempotency_key,

        recipient_name=recipient_name,

        draft_text=draft_text,

        status="UNSENT",

        created_at=now,

    )





def list_reminders(

    conn: sqlite3.Connection,

    *,

    team_id: str,

    cycle_id: str | None = None,

) -> list[ReminderRecord]:

    _require_team(conn, team_id)

    query = (

        "SELECT id, team_id, action_id, cycle_id, idempotency_key, recipient_name, draft_text, status, created_at "

        "FROM reminders WHERE team_id = ?"

    )

    params: list[Any] = [team_id]

    if cycle_id is not None:

        query += " AND cycle_id = ?"

        params.append(cycle_id)

    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()

    log_event("memory_read", {"op": "list_reminders", "team_id": team_id, "count": len(rows)})

    return [

        ReminderRecord(

            reminder_id=r["id"],

            team_id=r["team_id"],

            action_id=r["action_id"],

            cycle_id=r["cycle_id"],

            idempotency_key=r["idempotency_key"],

            recipient_name=r["recipient_name"],

            draft_text=r["draft_text"],

            status=r["status"],

            created_at=r["created_at"],

        )

        for r in rows

    ]

