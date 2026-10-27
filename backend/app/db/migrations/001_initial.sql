-- Migration 001: initial schema
-- All timestamps are UTC ISO 8601 text (e.g. 2026-01-15T09:30:00Z).
-- Foreign keys are enforced at connection time (PRAGMA foreign_keys = ON).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- schema_migrations: tracks which migration files have been applied.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    file_hash   TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- teams: top-level tenant. Every other table is scoped by team_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- members: people who belong to a team.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS members (
    id          TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL REFERENCES teams(id),
    name        TEXT NOT NULL,
    email       TEXT,
    created_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- meetings: an uploaded set of notes. File hash deduplicates re-uploads.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meetings (
    id          TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL REFERENCES teams(id),
    filename    TEXT NOT NULL,
    file_hash   TEXT NOT NULL,
    as_of_date  TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    UNIQUE (team_id, file_hash)
);

-- ---------------------------------------------------------------------------
-- actions: one action item, across all its versions.
-- action_id is a human-readable code like A-001, unique within a team.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actions (
    id          TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL REFERENCES teams(id),
    action_code TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    meeting_id  TEXT NOT NULL REFERENCES meetings(id),
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_actions_team ON actions(team_id);

-- ---------------------------------------------------------------------------
-- action_versions: immutable audit trail. Only one row per action may have
-- is_current = 1 at any time (enforced by the partial unique index below).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_versions (
    id              TEXT    PRIMARY KEY,
    action_id       TEXT    NOT NULL REFERENCES actions(id),
    team_id         TEXT    NOT NULL REFERENCES teams(id),
    version_no      INTEGER NOT NULL,
    description     TEXT    NOT NULL,
    owner           TEXT    NOT NULL,
    due_date        TEXT,
    status          TEXT    NOT NULL CHECK (status IN (
                        'open', 'done', 'blocked', 'needs_clarification'
                    )),
    is_current      INTEGER NOT NULL DEFAULT 1
                        CHECK (is_current IN (0, 1)),
    confidence      REAL    CHECK (confidence IS NULL OR
                        (confidence >= 0.0 AND confidence <= 1.0)),
    valid_from      TEXT    NOT NULL,
    superseded_at   TEXT,
    changed_by      TEXT    NOT NULL CHECK (changed_by IN (
                        'agent_approved', 'user_correction'
                    )),
    UNIQUE (action_id, version_no)
);

-- Only one current version per action (hard rule 7).
CREATE UNIQUE INDEX IF NOT EXISTS ux_action_current
    ON action_versions(action_id)
    WHERE is_current = 1;

CREATE INDEX IF NOT EXISTS ix_action_versions_team_current
    ON action_versions(team_id, is_current);

-- ---------------------------------------------------------------------------
-- cycles: one processing run for a meeting file.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cycles (
    id          TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL REFERENCES teams(id),
    meeting_id  TEXT NOT NULL REFERENCES meetings(id),
    state       TEXT NOT NULL CHECK (state IN (
                    'extracted', 'proposed', 'committed'
                )),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- proposals: agent suggestions, written once, never edited.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proposals (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL REFERENCES teams(id),
    cycle_id        TEXT NOT NULL REFERENCES cycles(id),
    action_id       TEXT NOT NULL REFERENCES actions(id),
    outcome         TEXT NOT NULL CHECK (outcome IN (
                        'close_with_evidence',
                        'carry_over',
                        'mark_blocked',
                        'ask_question',
                        'draft_reminder',
                        'new_action'
                    )),
    rationale       TEXT NOT NULL,
    evidence_quote  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'approved', 'edited', 'rejected'
                    )),
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_proposals_team_cycle_status
    ON proposals(team_id, cycle_id, status);

-- ---------------------------------------------------------------------------
-- user_decisions: what the human chose for each proposal. Separate from the
-- agent suggestion so the two are never conflated.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_decisions (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL REFERENCES teams(id),
    proposal_id     TEXT NOT NULL REFERENCES proposals(id),
    decision        TEXT NOT NULL CHECK (decision IN (
                        'approve', 'edit', 'reject'
                    )),
    edited_owner    TEXT,
    edited_due_date TEXT,
    edited_status   TEXT,
    decided_at      TEXT NOT NULL,
    decided_by      TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- reminders: UNSENT text drafts. Nothing is ever sent (hard rule 5).
-- idempotency_key prevents duplicates across retries (hard rule 9).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reminders (
    id                TEXT PRIMARY KEY,
    team_id           TEXT NOT NULL REFERENCES teams(id),
    action_id         TEXT NOT NULL REFERENCES actions(id),
    cycle_id          TEXT NOT NULL REFERENCES cycles(id),
    idempotency_key   TEXT NOT NULL UNIQUE,
    recipient_name    TEXT NOT NULL,
    draft_text        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'UNSENT' CHECK (status IN ('UNSENT')),
    created_at        TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- action_log: append-only audit log for every significant event.
-- team_id is nullable because some events (e.g. startup) have no team context.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_log (
    id          TEXT    PRIMARY KEY,
    team_id     TEXT    REFERENCES teams(id),
    cycle_id    TEXT    REFERENCES cycles(id),
    event       TEXT    NOT NULL CHECK (event IN (
                    'tool_call', 'memory_read', 'memory_write',
                    'approval', 'llm_call', 'error'
                )),
    payload     TEXT    NOT NULL,
    logged_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_action_log_team_cycle
    ON action_log(team_id, cycle_id);

-- ---------------------------------------------------------------------------
-- action_counters: monotonic per-team counter for generating A-NNN codes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_counters (
    team_id     TEXT    PRIMARY KEY REFERENCES teams(id),
    last_number INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_meetings_team ON meetings(team_id);
