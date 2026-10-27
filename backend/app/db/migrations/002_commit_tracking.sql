-- Migration 002: add columns needed by the action store and approval gate.
-- Relaxes NOT NULL on action_versions.owner and proposals.action_id so that
-- unknown-owner actions and new_action proposals can be stored legally.
-- Never edit migration 001.

-- ---------------------------------------------------------------------------
-- Rebuild action_versions: make owner nullable
-- ---------------------------------------------------------------------------
CREATE TABLE action_versions_new (
    id              TEXT    PRIMARY KEY,
    action_id       TEXT    NOT NULL REFERENCES actions(id),
    team_id         TEXT    NOT NULL REFERENCES teams(id),
    version_no      INTEGER NOT NULL,
    description     TEXT    NOT NULL,
    owner           TEXT,                 -- nullable: unknown owner
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
    -- new columns added by this migration:
    blocked_reason      TEXT,
    source_meeting_id   TEXT REFERENCES meetings(id),
    proposal_id         TEXT,             -- FK added after proposals rebuild below
    UNIQUE (action_id, version_no)
);

INSERT INTO action_versions_new
    (id, action_id, team_id, version_no, description, owner, due_date, status,
     is_current, confidence, valid_from, superseded_at, changed_by)
SELECT id, action_id, team_id, version_no, description, owner, due_date, status,
       is_current, confidence, valid_from, superseded_at, changed_by
FROM action_versions;

DROP TABLE action_versions;
ALTER TABLE action_versions_new RENAME TO action_versions;

-- Recreate indexes from migration 001
CREATE UNIQUE INDEX IF NOT EXISTS ux_action_current
    ON action_versions(action_id)
    WHERE is_current = 1;

CREATE INDEX IF NOT EXISTS ix_action_versions_team_current
    ON action_versions(team_id, is_current);

-- ---------------------------------------------------------------------------
-- Rebuild proposals: make action_id nullable (for new_action outcome)
-- ---------------------------------------------------------------------------
CREATE TABLE proposals_new (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL REFERENCES teams(id),
    cycle_id        TEXT NOT NULL REFERENCES cycles(id),
    action_id       TEXT REFERENCES actions(id),   -- nullable for new_action
    outcome         TEXT NOT NULL CHECK (outcome IN (
                        'close_with_evidence',
                        'carry_over',
                        'mark_blocked',
                        'ask_question',
                        'draft_reminder',
                        'new_action'
                    )),
    rationale       TEXT NOT NULL DEFAULT '',
    evidence_quote  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'approved', 'edited', 'rejected'
                    )),
    created_at      TEXT NOT NULL,
    -- new columns:
    committed_at    TEXT,
    payload_json    TEXT
);

INSERT INTO proposals_new
    (id, team_id, cycle_id, action_id, outcome, rationale,
     evidence_quote, status, created_at)
SELECT id, team_id, cycle_id, action_id, outcome, rationale,
       evidence_quote, status, created_at
FROM proposals;

DROP TABLE proposals;
ALTER TABLE proposals_new RENAME TO proposals;

-- Recreate index from migration 001
CREATE INDEX IF NOT EXISTS ix_proposals_team_cycle_status
    ON proposals(team_id, cycle_id, status);

-- ---------------------------------------------------------------------------
-- Rebuild user_decisions: add edited_payload_json
-- ---------------------------------------------------------------------------
CREATE TABLE user_decisions_new (
    id                  TEXT PRIMARY KEY,
    team_id             TEXT NOT NULL REFERENCES teams(id),
    proposal_id         TEXT NOT NULL REFERENCES proposals(id),
    decision            TEXT NOT NULL CHECK (decision IN (
                            'approve', 'edit', 'reject'
                        )),
    edited_owner        TEXT,
    edited_due_date     TEXT,
    edited_status       TEXT,
    decided_at          TEXT NOT NULL,
    decided_by          TEXT NOT NULL,
    -- new columns:
    edited_payload_json TEXT
);

INSERT INTO user_decisions_new
    (id, team_id, proposal_id, decision, edited_owner, edited_due_date,
     edited_status, decided_at, decided_by)
SELECT id, team_id, proposal_id, decision, edited_owner, edited_due_date,
       edited_status, decided_at, decided_by
FROM user_decisions;

DROP TABLE user_decisions;
ALTER TABLE user_decisions_new RENAME TO user_decisions;

-- ---------------------------------------------------------------------------
-- Add as_of to cycles and supervisor to teams
-- ---------------------------------------------------------------------------
ALTER TABLE teams    ADD COLUMN supervisor TEXT;
ALTER TABLE cycles   ADD COLUMN as_of      TEXT;

-- ---------------------------------------------------------------------------
-- Cross-table indexes for the new FK relationships
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX ux_version_proposal
    ON action_versions(proposal_id)
    WHERE proposal_id IS NOT NULL;

CREATE UNIQUE INDEX ux_decision_per_proposal
    ON user_decisions(proposal_id);
