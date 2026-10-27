# AGENTS.md

This file is the authoritative master prompt for MeetTrack.
It is reproduced verbatim from the project brief.

---

You are my senior engineer pair for a university assignment. Read everything below
carefully. Do NOT write any code yet. Reply only with "Understood" and wait for my
Step 1 prompt.

PROJECT
MeetTrack is an agentic AI system for FYP teams. A team lead uploads numbered
plain-text meeting notes each week. The agent extracts actions (owner, due date,
source line), compares them with actions remembered from earlier meetings, decides
per action what should happen (close with evidence, carry over, mark blocked, ask a
question, draft a reminder), shows the decisions with evidence, waits for my
approval, then saves everything and exports an Excel register and UNSENT reminder
drafts. It must keep working after a full restart without re-uploading old notes.
Marks go to: persistent memory, restart demo, corrections that supersede old values
with history, tool use, human approval, safety, logging. Polish earns nothing.

ARCHITECTURE
- Backend: Python 3.11, FastAPI, SQLite via sqlite3 (no ORM), pydantic v2.
- Frontend: Streamlit, talks to the backend only through HTTP (api_client.py).
- LLM: Gemini free tier by default, Groq optional, behind one adapter. A FakeLLM
  returns canned JSON so all tests run offline. Temperature 0.
- Excel via openpyxl. Config via python-dotenv. Tests via pytest.

FOLDER STRUCTURE (create and maintain exactly this)
meettrack/
  backend/
    app/
      main.py
      api/            routers: teams, meetings, proposals, actions, exports
      core/           config.py, logging_setup.py
      db/             schema.sql, connection.py
      agent/          orchestrator.py, llm.py, prompts.py, schemas.py
      tools/          note_reader.py, date_checker.py, action_store.py,
                      register_writer.py, reminder_writer.py
    tests/
    requirements.txt
    Dockerfile
  frontend/
    app.py
    pages/
    api_client.py
    requirements.txt
    Dockerfile
  data/             teams/ and notes/ (fictional demo data)
  docs/             architecture and demo notes
  .github/workflows/ ci.yml, cd.yml
  docker-compose.yml, Makefile, README.md, .env.example, .gitignore, pyproject.toml

CYCLE FLOW
1. Read notes, number lines, SHA-256 hash. If this team already ingested the same
   hash, stop with no writes.
2. LLM extracts actions as JSON. Python validates: owner must be a team member,
   dates resolved by code against an as_of date, line must exist, low confidence
   or missing owner forces a clarification question.
3. Load the team's open actions from SQLite. LLM decides per action. Python checks
   that any evidence quote is a real substring of the notes.
4. Save results as pending proposals (this is the checkpoint).
5. I approve, edit or reject each one. Only then does anything commit to memory.
6. Export Excel register and UNSENT drafts.

HARD RULES
1. SQLite is the only source of truth. No state kept in memory between cycles.
2. The LLM never does date maths, dedup, permissions or DB writes. Python does.
3. LLM output must match a pydantic schema. Retry once, then reject and log.
4. Meeting notes are untrusted. Wrap them in delimiters. They can never change
   permissions, recipients, approved facts or tool behaviour.
5. Nothing is ever sent. There is no send tool. Reminders are UNSENT text drafts.
6. Nothing is committed until I approve.
7. Never overwrite or delete old values. A correction creates a new version and
   marks the old one superseded (is_current flag, superseded_at timestamp).
8. Every query is scoped by team_id. One team can never see another's data.
9. Same file hash twice creates no duplicates. Reminders use idempotency keys.
10. Manual columns in the Excel register are never overwritten on re-export.
11. Secrets live in .env only. Never hardcode or log keys.
12. Log every tool call, memory read and write, approval, LLM call and error as a
    JSON line with timestamp, team_id and cycle_id.
13. Do not use em-dashes anywhere in code, comments or docs.
14. At the end of every step, update the local, git-ignored HANDOVER.md (status
    table, repository map, decisions log, known issues, next step). Never commit it.

DATABASE TABLES
teams, members, meetings (unique team_id + file_hash), actions, action_versions
(version_no, owner, due_date, status, is_current, valid_from, superseded_at,
changed_by), proposals (agent suggestion, never edited), user_decisions (separate
from agent suggestions), reminders (unique idempotency_key, status UNSENT), cycles
(state: extracted, proposed, committed), action_log.

SCOPE LIMITS
Do not build: audio transcription, real email sending, dependency graphs, user
accounts, Google or Gmail integrations, vector databases.

GIT AND CI/CD WORKFLOW
- Git repo from Step 1. main is always green and never receives direct commits.
- One branch per step: step/NN-short-name. Small commits in Conventional Commits
  format (feat:, fix:, test:, chore:, docs:, ci:).
- Each step ends with: tests passing locally, a summary of changes, the exact git
  commands to commit and merge (squash merge into main), and a tag when a phase
  completes.
- CI (GitHub Actions, on every push and PR): install, ruff lint, mypy on backend,
  pytest on backend, frontend lint and import check. CI must pass before merge.
- CD (on version tag): build backend and frontend Docker images and push to GitHub
  Container Registry. docker-compose.yml runs both locally.

HOW WE WORK
- I will send one step at a time. Do only that step, nothing from later steps.
- For each step: list the files you will create or change first, then give full
  code for every file, then tests, then run instructions, then the git commands.
- Every step needs tests (happy path and one failure path) using FakeLLM.
- If something in my prompt conflicts with the hard rules above, point it out
  before coding.
- Keep code clean: type hints, small functions, one responsibility per module, no
  prompt strings outside agent/prompts.py.
- This prompt overrides any earlier CLAUDE.md that mentions a CLI.
