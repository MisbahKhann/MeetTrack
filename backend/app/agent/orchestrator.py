"""Cycle orchestrator: runs a full cycle from raw notes to saved proposals.

The LLM suggests, Python validates and decides what is allowed. No LLM output
is applied directly; every change goes through validation and the store's
approval gate.
"""

import sqlite3
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.agent.guards import (
    evidence_is_relevant,
    find_suspicious_lines,
    is_grounded,
    withhold_lines,
)
from app.agent.llm import LLMClient, LLMError
from app.agent.prompts import (
    DECIDE_SYSTEM,
    EXTRACT_SYSTEM,
    PROMPT_VERSION,
    build_decide_user,
    build_extract_user,
)
from app.agent.schemas import Decision, DecisionResult, ExtractedAction, ExtractionResult
from app.core.logging_setup import log_event
from app.tools.action_store import (
    CommitResult,
    NotFoundError,
    ProposalPayload,
    add_meeting,
    commit_proposal,
    create_cycle,
    finalize_cycle,
    get_cycle,
    get_meeting_by_hash,
    get_open_actions,
    list_proposals,
    resolve_member,
    save_proposals,
    set_cycle_state,
)
from app.tools.date_checker import classify_due, days_overdue, parse_as_of, resolve_due
from app.tools.note_reader import NoteDocument, parse_notes, render_for_prompt, verify_quote

MAX_EXTRACTED_ITEMS = 30


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ProposalView(BaseModel, frozen=True):
    outcome: str
    action_id: str | None
    description: str | None
    owner: str | None
    due_date: str | None
    evidence_line: int | None
    reason: str


class CycleReport(BaseModel, frozen=True):
    status: str  # "proposed", "already_processed", "dry_run"
    cycle_id: str | None
    meeting_id: str | None
    as_of: str
    proposals: list[ProposalView]
    warnings: list[str]
    llm_calls: int


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CycleError(Exception):
    """Base exception for orchestrator errors."""


class CycleFailedError(CycleError):
    """An LLM call or validation failed during the cycle."""

    def __init__(
        self,
        cycle_id: str | None,
        state: str,
        cause: str,
    ) -> None:
        self.cycle_id = cycle_id
        self.state = state
        self.cause = cause
        super().__init__(f"Cycle {cycle_id} failed in state {state}: {cause}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _set_log_context(team_id: str, cycle_id: str | None = None) -> None:
    """Set context for log events (best-effort)."""
    try:
        from app.core.logging_setup import set_log_context

        set_log_context(team_id=team_id, cycle_id=cycle_id)
    except Exception:  # noqa: BLE001
        pass


def _follow_up_first_key(action: Any) -> tuple[int, str]:
    """Sort key: blocked/needs_clarification/overdue first, then action_id."""
    status = getattr(action, "status", "open")
    due_date_str = getattr(action, "due_date", None)
    as_of_date = date.today()

    priority = 0
    if status in ("blocked", "needs_clarification"):
        priority = 0
    elif due_date_str:
        try:
            due = date.fromisoformat(due_date_str)
            if due < as_of_date:
                priority = 0
        except ValueError:
            priority = 1
    else:
        priority = 1

    action_id = getattr(action, "action_id", "")
    return (priority, action_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_notes(
    conn: sqlite3.Connection,
    llm: LLMClient,
    *,
    team_id: str,
    file_name: str,
    content: bytes | str,
    as_of: str | None = None,
    memory_enabled: bool = True,
) -> CycleReport:
    """Run a full cycle from raw notes to saved pending proposals.

    Returns a CycleReport with status "proposed", "already_processed" or "dry_run".
    """
    warnings: list[str] = []
    llm_calls = 0

    # 1. Parse notes
    doc = parse_notes(content, file_name)

    if as_of is None:
        if doc.header is not None:
            as_of = doc.header.meeting_date.isoformat()
        else:
            raise CycleError("No as_of provided and no header date in notes")

    as_of_date = parse_as_of(as_of)

    _set_log_context(team_id=team_id)
    log_event(
        "tool_call", {"step": "parse_notes", "team_id": team_id, "line_count": len(doc.lines)}
    )

    # 2. Memory OFF = dry run
    if not memory_enabled:
        # Skip duplicate check, skip open actions
        rendered = render_for_prompt(doc)
        member_names = [m.name for m in _list_members_safe(conn, team_id)]

        # Extract
        suspicious = find_suspicious_lines(doc)
        prompt_doc = doc
        if suspicious:
            prompt_doc = withhold_lines(doc, set(suspicious.keys()))
            for ln, pat in suspicious.items():
                warnings.append(f"Line {ln} withheld: {pat}")
        rendered = render_for_prompt(prompt_doc)

        extract_user = build_extract_user(rendered, member_names, as_of)
        try:
            result = llm.generate_structured(
                EXTRACT_SYSTEM,
                extract_user,
                ExtractionResult,
                call_name=f"extract.{PROMPT_VERSION}",
            )
            llm_calls += 1
        except LLMError as exc:
            log_event(
                "error",
                {"step": "extract_dry_run", "team_id": team_id, "error": str(exc)},
            )
            raise CycleFailedError(None, "dry_run", str(exc)) from exc

        extracted = _validate_extracted(
            conn, result.actions, doc, suspicious, team_id, as_of_date, warnings
        )
        proposals = _make_new_action_proposals(extracted)
        return CycleReport(
            status="dry_run",
            cycle_id=None,
            meeting_id=None,
            as_of=as_of,
            proposals=proposals,
            warnings=warnings,
            llm_calls=llm_calls,
        )

    # 3. Duplicate and resume (memory ON)
    existing_meeting = get_meeting_by_hash(conn, team_id=team_id, file_hash=doc.sha256)
    if existing_meeting is not None:
        cycle = _get_cycle_safe(conn, team_id, existing_meeting.meeting_id)
        if cycle is not None and cycle.state in ("proposed", "committed"):
            # Already processed
            proposals = list_proposals(conn, team_id=team_id, cycle_id=cycle.cycle_id)
            views = [_proposal_to_view(p) for p in proposals]
            return CycleReport(
                status="already_processed",
                cycle_id=cycle.cycle_id,
                meeting_id=existing_meeting.meeting_id,
                as_of=as_of,
                proposals=views,
                warnings=[],
                llm_calls=0,
            )
        # Cycle in "extracted" state = resume
        meeting_id = existing_meeting.meeting_id
        if cycle is None:
            cycle = create_cycle(conn, team_id=team_id, meeting_id=meeting_id, as_of=as_of)
        cycle_id = cycle.cycle_id
    else:
        meeting = add_meeting(
            conn,
            team_id=team_id,
            meeting_date=as_of,
            file_name=file_name,
            file_hash=doc.sha256,
        )
        meeting_id = meeting.meeting_id
        cycle = create_cycle(conn, team_id=team_id, meeting_id=meeting_id, as_of=as_of)
        cycle_id = cycle.cycle_id

    _set_log_context(team_id=team_id, cycle_id=cycle_id)
    log_event("tool_call", {"step": "cycle_created", "team_id": team_id, "cycle_id": cycle_id})

    # 4. Withhold suspicious lines
    suspicious = find_suspicious_lines(doc)
    prompt_doc = doc
    if suspicious:
        prompt_doc = withhold_lines(doc, set(suspicious.keys()))
        for ln, pat in suspicious.items():
            warnings.append(f"Line {ln} withheld: {pat}")

    # 5. LLM call 1 (extract)
    try:
        rendered = render_for_prompt(prompt_doc)
        member_names = [m.name for m in _list_members_safe(conn, team_id)]
        extract_user = build_extract_user(rendered, member_names, as_of)
        result = llm.generate_structured(
            EXTRACT_SYSTEM,
            extract_user,
            ExtractionResult,
            call_name=f"extract.{PROMPT_VERSION}",
        )
        llm_calls += 1
    except LLMError as exc:
        log_event(
            "error",
            {"step": "extract", "team_id": team_id, "cycle_id": cycle_id, "error": str(exc)},
        )
        raise CycleFailedError(cycle_id, "extracted", str(exc)) from exc

    extracted = _validate_extracted(
        conn, result.actions, doc, suspicious, team_id, as_of_date, warnings
    )

    # 6. Load open actions
    open_actions = get_open_actions(conn, team_id=team_id)
    open_action_ids = {a.action_id for a in open_actions}

    # 7. LLM call 2 (decide) only when there are open actions
    decisions: list[Decision] = []
    if open_actions:
        try:
            extracted_items = [
                (
                    i,
                    e["description"],
                    e["owner"],
                    e["due_text"],
                    e.get("due_date"),
                    e["source_line"],
                )
                for i, e in enumerate(extracted)
            ]
            open_action_tuples = [
                (
                    a.action_id,
                    a.description,
                    a.owner,
                    a.due_date,
                    a.status,
                    a.blocked_reason,
                    classify_due(
                        date.fromisoformat(a.due_date) if a.due_date else None,
                        as_of_date,
                        a.status,
                    ),
                    days_overdue(
                        date.fromisoformat(a.due_date) if a.due_date else None,
                        as_of_date,
                        a.status,
                    ),
                )
                for a in open_actions
            ]
            decide_user = build_decide_user(rendered, extracted_items, open_action_tuples, as_of)
            decide_result = llm.generate_structured(
                DECIDE_SYSTEM,
                decide_user,
                DecisionResult,
                call_name=f"decide.{PROMPT_VERSION}",
            )
            llm_calls += 1
            decisions = decide_result.decisions
        except LLMError as exc:
            log_event(
                "error",
                {"step": "decide", "team_id": team_id, "cycle_id": cycle_id, "error": str(exc)},
            )
            raise CycleFailedError(cycle_id, "extracted", str(exc)) from exc

    # 8. Validate decisions
    valid_decisions, unassigned_extracts = _validate_decisions(
        decisions,
        extracted,
        open_actions,
        open_action_ids,
        doc,
        suspicious,
        warnings,
    )

    # Add carry_over for unmentioned open actions
    decided_ids = {d["action_id"] for d in valid_decisions if d["action_id"]}
    for action in open_actions:
        if action.action_id not in decided_ids:
            due_class = classify_due(
                date.fromisoformat(action.due_date) if action.due_date else None,
                as_of_date,
                action.status,
            )
            outcome = "carry_over"
            if action.owner and due_class == "overdue":
                outcome = "draft_reminder"
            valid_decisions.append(
                {
                    "action_id": action.action_id,
                    "outcome": outcome,
                    "extracted_index": None,
                    "evidence_line": None,
                    "evidence_quote": None,
                    "reason": "Not mentioned in this meeting",
                    "question": None,
                }
            )

    # Add new_action for unassigned extracts
    for idx in unassigned_extracts:
        valid_decisions.append(
            {
                "action_id": None,
                "outcome": "new_action",
                "extracted_index": idx,
                "evidence_line": None,
                "evidence_quote": None,
                "reason": extracted[idx]["description"],
                "question": None,
            }
        )

    # 9. Build ProposalPayload values
    payloads = _build_payloads(valid_decisions, extracted, open_actions, warnings)

    # 10. Save proposals
    if payloads:
        save_proposals(conn, team_id=team_id, cycle_id=cycle_id, payloads=payloads)
    else:
        # Move cycle forward even with zero proposals
        try:
            set_cycle_state(conn, team_id=team_id, cycle_id=cycle_id, state="proposed")
        except Exception:  # noqa: BLE001
            pass

    # Build views
    views = [_payload_to_view(p) for p in payloads]

    log_event(
        "tool_call",
        {
            "step": "proposals_saved",
            "team_id": team_id,
            "cycle_id": cycle_id,
            "count": len(payloads),
        },
    )

    return CycleReport(
        status="proposed",
        cycle_id=cycle_id,
        meeting_id=meeting_id,
        as_of=as_of,
        proposals=views,
        warnings=warnings,
        llm_calls=llm_calls,
    )


def commit_approved(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    cycle_id: str,
) -> list[CommitResult]:
    """Commit every approved or edited proposal, then finalize if possible."""
    proposals = list_proposals(conn, team_id=team_id, cycle_id=cycle_id)
    results: list[CommitResult] = []
    for p in proposals:
        if p.status in ("approved", "edited") and p.committed_at is None:
            result = commit_proposal(conn, team_id=team_id, proposal_id=p.proposal_id)
            results.append(result)
    # Try to finalize
    try:
        finalize_cycle(conn, team_id=team_id, cycle_id=cycle_id)
    except Exception:  # noqa: BLE001
        pass
    return results


# ---------------------------------------------------------------------------
# Internal functions
# ---------------------------------------------------------------------------


def _list_members_safe(conn: sqlite3.Connection, team_id: str) -> list[Any]:
    from app.tools.action_store import list_members

    try:
        return list_members(conn, team_id=team_id)
    except NotFoundError:
        raise
    except Exception:  # noqa: BLE001
        return []


def _get_cycle_safe(conn: sqlite3.Connection, team_id: str, meeting_id: str) -> Any:
    cycle_id = f"{team_id}-{meeting_id}"
    try:
        return get_cycle(conn, team_id=team_id, cycle_id=cycle_id)
    except NotFoundError:
        return None


def _validate_extracted(
    conn: sqlite3.Connection,
    actions: list[ExtractedAction],
    doc: NoteDocument,
    suspicious: dict[int, str],
    team_id: str,
    as_of: date,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Validate and filter extracted actions. Returns list of dicts."""
    result: list[dict[str, Any]] = []
    for i, action in enumerate(actions):
        if len(result) >= MAX_EXTRACTED_ITEMS:
            warnings.append(f"Extracted item {i} dropped: max {MAX_EXTRACTED_ITEMS} items reached")
            continue

        # Check source_line exists and is not suspicious
        if action.source_line in suspicious:
            warnings.append(
                f"Extracted item {i} dropped: source line {action.source_line} is suspicious"
            )
            continue
        line = None
        for ln in doc.lines:
            if ln.number == action.source_line:
                line = ln
                break
        if line is None:
            warnings.append(
                f"Extracted item {i} dropped: source line {action.source_line} not found"
            )
            continue

        # Check grounding
        if not is_grounded(action.description, line.text):
            warnings.append(f"Extracted item {i} dropped: not grounded in source line")
            continue

        # Resolve owner
        owner = action.owner
        needs_clarification = action.needs_clarification
        question = action.clarification_question

        if owner is not None:
            canonical = resolve_member(conn, team_id=team_id, name=owner)
            if canonical is None:
                owner = None
                needs_clarification = True
                question = f"Owner '{action.owner}' is not a team member. Who is responsible?"
        else:
            needs_clarification = True
            if not question:
                question = "No owner specified. Who is responsible?"

        # Check confidence
        if action.confidence < 0.6:
            needs_clarification = True
            if not question:
                question = "Low confidence extraction. Please confirm."

        # Resolve due date
        due_text = action.due_text
        due_date_str: str | None = None
        due_res = resolve_due(due_text, as_of) if due_text else None
        if due_res:
            if due_res.status == "unparseable":
                needs_clarification = True
                if not question:
                    question = f"Due date '{due_text}' could not be parsed."
            elif due_res.status == "approximate":
                due_date_str = due_res.due_date.isoformat() if due_res.due_date else None
                warnings.append(f"Due date for item {i} is approximate: {due_date_str}")
            elif due_res.status == "resolved":
                due_date_str = due_res.due_date.isoformat() if due_res.due_date else None
            # status "none" -> due_date stays None

        result.append(
            {
                "index": i,
                "description": action.description,
                "owner": owner,
                "needs_clarification": needs_clarification,
                "question": question,
                "due_text": due_text,
                "due_date": due_date_str,
                "source_line": action.source_line,
            }
        )

    return result


def _validate_decisions(
    decisions: list[Decision],
    extracted: list[dict[str, Any]],
    open_actions: list[Any],
    open_action_ids: set[str],
    doc: NoteDocument,
    suspicious: dict[int, str],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], set[int]]:
    """Validate LLM decisions. Returns (valid_decisions, unassigned_extract_indices)."""
    valid: list[dict[str, Any]] = []
    seen_action_ids: set[str] = set()
    assigned_extracts: set[int] = set()
    code_to_id = {
        getattr(a, "action_code", ""): a.action_id
        for a in open_actions
        if getattr(a, "action_code", None)
    }

    for d in decisions:
        # Check action_id (support both canonical UUID and human-readable action_code)
        canonical_action_id = None
        if d.action_id is not None:
            if d.action_id in open_action_ids:
                canonical_action_id = d.action_id
            elif d.action_id in code_to_id:
                canonical_action_id = code_to_id[d.action_id]
            else:
                warnings.append(f"Decision dropped: action_id {d.action_id} not in open actions")
                continue
            if canonical_action_id in seen_action_ids:
                warnings.append(f"Decision dropped: duplicate for action_id {d.action_id}")
                continue
            seen_action_ids.add(canonical_action_id)

        # Check extracted_index
        if d.extracted_index is not None:
            if d.extracted_index < 0 or d.extracted_index >= len(extracted):
                warnings.append(
                    f"Decision dropped: extracted_index {d.extracted_index} out of range"
                )
                continue

        # new_action must have no action_id
        if d.outcome == "new_action":
            if d.action_id is not None:
                warnings.append("Decision dropped: new_action should not have action_id")
                continue
            if d.extracted_index is None:
                warnings.append("Decision dropped: new_action requires extracted_index")
                continue
            assigned_extracts.add(d.extracted_index)

        # Every other outcome needs action_id
        if d.outcome != "new_action" and d.action_id is None:
            warnings.append(f"Decision dropped: outcome {d.outcome} requires action_id")
            continue

        # Validate evidence for close_with_evidence and mark_blocked
        if d.outcome in ("close_with_evidence", "mark_blocked"):
            if d.evidence_line is None or d.evidence_quote is None:
                warnings.append(
                    f"Decision downgraded: {d.outcome} requires evidence_line and evidence_quote"
                )
                valid.append(
                    {
                        "action_id": canonical_action_id,
                        "outcome": "ask_question",
                        "extracted_index": d.extracted_index,
                        "evidence_line": None,
                        "evidence_quote": None,
                        "reason": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                        "question": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                    }
                )
                continue

            # Check evidence_line is not suspicious
            if d.evidence_line in suspicious:
                warnings.append(
                    f"Decision downgraded: evidence line {d.evidence_line} is suspicious"
                )
                valid.append(
                    {
                        "action_id": canonical_action_id,
                        "outcome": "ask_question",
                        "extracted_index": d.extracted_index,
                        "evidence_line": None,
                        "evidence_quote": None,
                        "reason": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                        "question": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                    }
                )
                continue

            # Verify quote on ORIGINAL doc
            if not verify_quote(doc, d.evidence_quote, d.evidence_line):
                warnings.append("Decision downgraded: evidence quote not found in notes")
                valid.append(
                    {
                        "action_id": canonical_action_id,
                        "outcome": "ask_question",
                        "extracted_index": d.extracted_index,
                        "evidence_line": None,
                        "evidence_quote": None,
                        "reason": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                        "question": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                    }
                )
                continue

            # Check evidence relevance
            action_desc = ""
            if d.extracted_index is not None and d.extracted_index < len(extracted):
                action_desc = extracted[d.extracted_index]["description"]
            elif d.action_id:
                for a in open_actions:
                    if a.action_id == d.action_id:
                        action_desc = a.description
                        break

            line_text = ""
            for ln in doc.lines:
                if ln.number == d.evidence_line:
                    line_text = ln.text
                    break

            if not evidence_is_relevant(action_desc, line_text):
                warnings.append("Decision downgraded: evidence not relevant to action")
                valid.append(
                    {
                        "action_id": canonical_action_id,
                        "outcome": "ask_question",
                        "extracted_index": d.extracted_index,
                        "evidence_line": None,
                        "evidence_quote": None,
                        "reason": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                        "question": "Evidence for this action could not be verified, is it done or blocked?",  # noqa: E501
                    }
                )
                continue

        # For other outcomes, clear bad evidence
        evidence_line = d.evidence_line
        evidence_quote = d.evidence_quote
        if d.outcome not in ("close_with_evidence", "mark_blocked"):
            if evidence_quote is not None and not verify_quote(doc, evidence_quote, evidence_line):
                evidence_quote = None
                evidence_line = None

        if d.extracted_index is not None and d.outcome != "new_action":
            assigned_extracts.add(d.extracted_index)

        valid.append(
            {
                "action_id": canonical_action_id,
                "outcome": d.outcome,
                "extracted_index": d.extracted_index,
                "evidence_line": evidence_line,
                "evidence_quote": evidence_quote,
                "reason": d.reason,
                "question": d.question,
            }
        )

    unassigned = set(range(len(extracted))) - assigned_extracts
    return valid, unassigned


def _build_payloads(
    decisions: list[dict[str, Any]],
    extracted: list[dict[str, Any]],
    open_actions: list[Any],
    warnings: list[str],
) -> list[ProposalPayload]:
    """Build ProposalPayload values from validated decisions."""
    action_map = {a.action_id: a for a in open_actions}
    payloads: list[ProposalPayload] = []

    for d in decisions:
        idx = d.get("extracted_index")
        action_id = d.get("action_id")

        # Determine owner and due_date
        owner: str | None = None
        due_date: str | None = None
        description: str | None = None
        source_line: int | None = None
        reason = d["reason"]

        if idx is not None and idx < len(extracted):
            ext = extracted[idx]
            description = ext["description"]
            owner = ext.get("owner")
            due_date = ext.get("due_date")
            source_line = ext.get("source_line")

            # Don't replace existing value with None
            if action_id and action_id in action_map:
                current = action_map[action_id]
                if owner is None and current.owner:
                    owner = current.owner
                if due_date is None and current.due_date:
                    due_date = current.due_date
                # Track changes in reason
                if current.owner and owner and owner != current.owner:
                    reason = f"owner changed; {reason}"
                if current.due_date and due_date and due_date != current.due_date:
                    reason = f"due date changed; {reason}"
        elif action_id and action_id in action_map:
            current = action_map[action_id]
            description = current.description
            owner = current.owner
            due_date = current.due_date

        blocked_reason: str | None = None
        if d["outcome"] == "mark_blocked":
            blocked_reason = reason

        payload = ProposalPayload(
            action_id=action_id,
            outcome=d["outcome"],
            description=description,
            owner=owner,
            due_date=due_date,
            blocked_reason=blocked_reason,
            question=d.get("question"),
            source_line=source_line,
            confidence=None,
            evidence_line=d.get("evidence_line"),
            evidence_quote=d.get("evidence_quote"),
            reason=reason,
        )
        payloads.append(payload)

    return payloads


def _make_new_action_proposals(extracted: list[dict[str, Any]]) -> list[ProposalView]:
    """Convert extracted items to ProposalView for dry-run mode."""
    views: list[ProposalView] = []
    for e in extracted:
        views.append(
            ProposalView(
                outcome="new_action",
                action_id=None,
                description=e["description"],
                owner=e.get("owner"),
                due_date=e.get("due_date"),
                evidence_line=None,
                reason=e.get("description", ""),
            )
        )
    return views


def _proposal_to_view(p: Any) -> ProposalView:
    """Convert a ProposalRecord to a ProposalView."""
    import json

    payload_json = getattr(p, "payload_json", "{}")
    try:
        data = json.loads(payload_json) if isinstance(payload_json, str) else {}
    except (json.JSONDecodeError, TypeError):
        data = {}

    return ProposalView(
        outcome=getattr(p, "outcome", data.get("outcome", "")),
        action_id=getattr(p, "action_id", None),
        description=data.get("description"),
        owner=data.get("owner"),
        due_date=data.get("due_date"),
        evidence_line=data.get("evidence_line"),
        reason=data.get("reason", ""),
    )


def _payload_to_view(p: ProposalPayload) -> ProposalView:
    """Convert a ProposalPayload to a ProposalView."""
    return ProposalView(
        outcome=p.outcome,
        action_id=p.action_id,
        description=p.description,
        owner=p.owner,
        due_date=p.due_date,
        evidence_line=p.evidence_line,
        reason=p.reason,
    )
