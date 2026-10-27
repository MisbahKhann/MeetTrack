# Database Reference

MeetTrack uses SQLite exclusively. The schema is created by
`backend/app/db/migrations/001_initial.sql` and extended by
`backend/app/db/migrations/002_commit_tracking.sql`. Both are applied by the
migration runner at startup in ascending order.

---

## Tables

| Table | Purpose |
|-------|---------|
| `schema_migrations` | Tracks which migration files have been applied, with SHA-256 hash for tamper detection |
| `teams` | Top-level tenant; every other table is scoped to a team |
| `members` | People who belong to a team; used to validate action owners |
| `meetings` | Uploaded note files; unique per (team_id, file_hash) to prevent re-processing |
| `actions` | One action item across all its versions; holds the human-readable code A-NNN |
| `action_versions` | Immutable audit trail of every state a given action has been in |
| `cycles` | One processing run (extract -> propose -> commit) for a meeting file |
| `proposals` | Agent suggestions, written once, never edited after creation |
| `user_decisions` | Human choices (approve / edit / reject) kept separate from agent suggestions |
| `reminders` | UNSENT text drafts only; idempotency key prevents duplicates |
| `action_log` | Append-only log of every tool call, LLM call, approval, and error |
| `action_counters` | Per-team monotonic counter used to generate A-NNN codes safely |

---

## ER diagram

```mermaid
erDiagram
    teams {
        TEXT id PK
        TEXT name
        TEXT created_at
    }

    members {
        TEXT id PK
        TEXT team_id FK
        TEXT name
        TEXT email
        TEXT created_at
    }

    meetings {
        TEXT id PK
        TEXT team_id FK
        TEXT filename
        TEXT file_hash
        TEXT as_of_date
        TEXT uploaded_at
    }

    actions {
        TEXT    id PK
        TEXT    team_id FK
        TEXT    action_code
        INTEGER source_line
        TEXT    meeting_id FK
        TEXT    created_at
    }

    action_versions {
        TEXT    id PK
        TEXT    action_id FK
        TEXT    team_id FK
        INTEGER version_no
        TEXT    description
        TEXT    owner           -- nullable after migration 002
        TEXT    due_date
        TEXT    status
        INTEGER is_current
        REAL    confidence
        TEXT    valid_from
        TEXT    superseded_at
        TEXT    changed_by
        TEXT    blocked_reason      -- migration 002
        TEXT    source_meeting_id   -- migration 002
        TEXT    proposal_id         -- migration 002
    }

    cycles {
        TEXT id PK
        TEXT team_id FK
        TEXT meeting_id FK
        TEXT state
        TEXT created_at
        TEXT updated_at
    }

    proposals {
        TEXT id PK
        TEXT team_id FK
        TEXT cycle_id FK
        TEXT action_id FK        -- nullable after migration 002
        TEXT outcome
        TEXT rationale
        TEXT evidence_quote
        TEXT status
        TEXT created_at
        TEXT committed_at        -- migration 002
        TEXT payload_json         -- migration 002
    }

    user_decisions {
        TEXT id PK
        TEXT team_id FK
        TEXT proposal_id FK
        TEXT decision
        TEXT edited_owner
        TEXT edited_due_date
        TEXT edited_status
        TEXT decided_at
        TEXT decided_by
        TEXT edited_payload_json -- migration 002
    }

    teams {
        TEXT id PK
        TEXT name
        TEXT created_at
        TEXT supervisor          -- migration 002
    }

    reminders {
        TEXT id PK
        TEXT team_id FK
        TEXT action_id FK
        TEXT cycle_id FK
        TEXT idempotency_key
        TEXT recipient_name
        TEXT draft_text
        TEXT status
        TEXT created_at
    }

    action_log {
        TEXT    id PK
        TEXT    team_id FK
        TEXT    cycle_id FK
        TEXT    event
        TEXT    payload
        TEXT    logged_at
    }

    action_counters {
        TEXT    team_id PK
        INTEGER last_number
    }

    schema_migrations {
        INTEGER version PK
        TEXT    name
        TEXT    file_hash
        TEXT    applied_at
    }

    teams ||--o{ members : "has"
    teams ||--o{ meetings : "uploads"
    teams ||--o{ actions : "owns"
    teams ||--o{ cycles : "runs"
    teams ||--o{ proposals : "receives"
    teams ||--o{ user_decisions : "makes"
    teams ||--o{ reminders : "drafts"
    teams ||--o| action_counters : "tracks"
    meetings ||--o{ actions : "sources"
    meetings ||--o{ cycles : "triggers"
    actions ||--o{ action_versions : "versioned by"
    actions ||--o{ proposals : "subject of"
    actions ||--o{ reminders : "reminds about"
    cycles ||--o{ proposals : "contains"
    cycles ||--o{ reminders : "generates"
    cycles ||--o{ action_log : "logged in"
    proposals ||--o{ user_decisions : "decided by"
```

---

## Which rule is enforced where

| Hard rule | Constraint |
|-----------|------------|
| Rule 1 -- SQLite is the only source of truth | All state written only through parameterised queries to this schema; no in-memory caches between cycles |
| Rule 7 -- Never overwrite old values; corrections create a new version | `CREATE UNIQUE INDEX ux_action_current ON action_versions(action_id) WHERE is_current = 1` -- only one current row per action; the old row must be set `is_current = 0` before a new one is inserted |
| Rule 7 (cont.) -- Immutable audit trail | `UNIQUE (action_id, version_no)` on `action_versions`; rows are never updated except to set `is_current = 0` and `superseded_at` |
| Rule 8 -- Every query scoped by team_id | `team_id` column with a FK on `teams(id)` on every data table; application code always includes `WHERE team_id = ?` |
| Rule 9 -- Same file hash twice creates no duplicates | `UNIQUE (team_id, file_hash)` on `meetings` |
| Rule 9 -- Reminder idempotency | `UNIQUE idempotency_key` on `reminders` |
| Rule 5 -- Nothing is ever sent | `reminders.status CHECK (status IN ('UNSENT'))` -- the only legal value is UNSENT; there is no 'SENT' state in the schema |
| Rule 6 -- Nothing committed until approved | Proposals are written to `proposals` (pending state); `user_decisions` rows must exist before anything is written to `action_versions` |
| Rule 3 -- LLM output validated | `CHECK` constraints on every status, outcome, event and decision column reject values outside the allowed sets before they reach the database |
| Rule 12 -- Log every significant event | `action_log` with `CHECK (event IN (...))` covering tool_call, memory_read, memory_write, approval, llm_call, error |

---

## Migration 002 (commit_tracking)

Never edit migration 001. Migration 002:

1. Rebuilds `action_versions` to make `owner` nullable (unknown owners are valid).
2. Rebuilds `proposals` to make `action_id` nullable (new_action proposals have no existing action).
3. Adds `committed_at`, `payload_json` to `proposals`.
4. Adds `blocked_reason`, `source_meeting_id`, `proposal_id` to `action_versions`.
5. Rebuilds `user_decisions` to add `edited_payload_json`.
6. Adds `supervisor` to `teams`.
7. Adds `as_of` to `cycles`.
8. Creates `ux_version_proposal` and `ux_decision_per_proposal` indexes.

---

## action_store API

| Function | Rule protected |
|----------|---------------|
| `init_team(conn, *, team_id, name, supervisor, members)` | Rule 8: team scope; idempotent |
| `get_team(conn, *, team_id)` | Rule 8: team-scoped read |
| `list_members(conn, *, team_id)` | Rule 8: team-scoped read |
| `resolve_member(conn, *, team_id, name)` | Rule 8: case-insensitive member lookup |
| `file_seen(conn, *, team_id, file_hash)` | Rule 9: duplicate detection |
| `add_meeting(conn, *, team_id, meeting_date, file_name, file_hash)` | Rule 9: duplicate file guard |
| `get_meeting_by_hash(conn, *, team_id, file_hash)` | Rule 9: resume support |
| `next_action_id(conn, *, team_id)` | Rule 8: atomic per-team counter |
| `create_action(conn, *, team_id, description, origin_meeting_id, owner, ...)` | Rule 6: approved only; Rule 8: team scoped |
| `new_version(conn, *, team_id, action_id, changed_by, ...)` | Rule 7: immutable versions; never deletes |
| `get_current(conn, *, team_id, action_id)` | Rule 8: team-scoped read |
| `list_actions(conn, *, team_id, include_done)` | Rule 8: team-scoped list |
| `get_open_actions(conn, *, team_id)` | Rule 8: team-scoped open items |
| `get_history(conn, *, team_id, action_id)` | Rule 7: full audit trail |
| `correct_action(conn, *, team_id, action_id, field, value, comment)` | Rule 7: user correction via new version |
| `create_cycle(conn, *, team_id, meeting_id, as_of)` | Rule 9: idempotent cycle |
| `get_cycle(conn, *, team_id, cycle_id)` | Rule 8: team-scoped read |
| `set_cycle_state(conn, *, team_id, cycle_id, state)` | Rule 6: forward-only transitions |
| `finalize_cycle(conn, *, team_id, cycle_id)` | Rule 6: all proposals resolved first |
| `save_proposals(conn, *, team_id, cycle_id, payloads)` | Rule 6: agent suggestion, immutable |
| `list_proposals(conn, *, team_id, cycle_id, status)` | Rule 8: team-scoped list |
| `decide_proposal(conn, *, team_id, proposal_id, decision, ...)` | Rule 6: approval gate; one decision only |
| `commit_proposal(conn, *, team_id, proposal_id)` | Rule 6: only approved/edited can commit |
