# MeetTrack

MeetTrack is an AI-assisted meeting-action management application designed for Final Year Project (FYP) teams and supervisors. It processes plain-text, numbered meeting notes, extracts proposed tasks, maps commitments to registered student owners, tracks deadlines, and maintains a versioned record of all team actions. MeetTrack enforces a strict human-approval gate: AI-extracted proposals never modify persistent records until reviewed and approved by the supervisor.

---

## Key Features

- **Team & Member Management**: Create isolated team workspaces with student members and supervisors. Deleting a team cascades safely without leaving orphaned records or affecting other teams.
- **Meeting-Note Ingestion**: Upload plain-text `.txt` files or paste numbered meeting notes directly.
- **Local AI Action Extraction**: Powered by local Ollama (`qwen2.5:1.5b`), eliminating the requirement for paid cloud API keys.
- **Evidence-Backed Proposals**: Every extracted commitment is anchored to verified line-by-line quotes from meeting notes.
- **Human Approval Gate**: Supervisors inspect, approve, edit, or reject proposals before committing them to persistent memory.
- **Auditable Versioned Memory**: Committed actions are versioned in SQLite (`v1`, `v2`, etc.). Changes never overwrite historical records.
- **Deadline & Overdue Tracking**: Automatically flags overdue commitments and calculates upcoming deadlines.
- **Excel Action Register Export**: Generates `.xlsx` workbooks containing both current action registers and full version-history audit logs.
- **Privacy-First Reminder Drafts**: Generates personalized reminder drafts labeled strictly as **UNSENT**; no emails or messages are ever sent automatically.
- **Modern Interactive Dashboard**: Features full Light and Dark mode theming, contextual workflow guidance, and an interactive 8-step tutorial with Tracky the mascot.

---

## Application Workflow

```text
1. Select Team ➔ 2. Upload Notes ➔ 3. Process with Ollama ➔ 4. Review Proposals ➔ 5. Commit to Memory ➔ 6. Track & Export
```

1. **Create or select a team**: Choose an active group with registered student members.
2. **Upload meeting notes**: Submit numbered meeting notes with speaker attributions (e.g., `1. Bilal: I will collect images by Friday`).
3. **Process notes with Ollama**: The local model extracts commitments, owners, deadlines, and source line quotes.
4. **Review proposals**: Inspect generated proposals in the approval gate. Check owners, due dates, and evidence quotes.
5. **Approve, edit, or reject**: Supervisors make the final call on all suggested changes.
6. **Commit approved decisions**: Persist approved tasks into the SQLite action register.
7. **Track actions & export**: Monitor active or overdue items, download Excel registers, or inspect draft reminders.

> **Why Human Review Matters**: AI models can occasionally misinterpret ambiguous statements or assign incorrect deadlines. Requiring explicit supervisor approval ensures persistent records remain accurate and auditable.

---

## Technology Stack

- **Frontend**: Streamlit (`1.40.2`), Requests (`2.32.3`)
- **Backend / API**: FastAPI (`0.115.5`), Uvicorn (`0.32.1`), Pydantic (`v2`), OpenPyXL (`3.1.5`), HTTPX (`0.28.1`)
- **LLM Integration**: Local Ollama API (default model: `qwen2.5:1.5b`); optional adapters for Gemini and Groq
- **Database & Storage**: SQLite with Write-Ahead Logging (WAL), foreign key constraints, and automatic migration
- **Testing & Quality**: Pytest (`8.3.3`), Ruff (`0.8.3`), Mypy (`1.13.0`)

---

## Project Structure

```text
meettrack/
├── backend/
│   ├── app/
│   │   ├── agent/         # LLM adapters (Ollama, Gemini, Groq) and cycle orchestrator
│   │   ├── api/           # FastAPI routers (teams, meetings, proposals, actions, exports)
│   │   ├── core/          # Application configuration, settings, and logging
│   │   ├── db/            # SQLite connection manager, schema, and migrations
│   │   └── tools/         # Action store, Excel exporter, and database queries
│   ├── tests/             # Backend test suite (API tests, orchestrator tests, fixtures)
│   ├── requirements.txt   # Backend runtime dependencies
│   └── requirements-dev.txt # Backend development and testing dependencies
├── frontend/
│   ├── api_client.py      # HTTP client interface for FastAPI backend
│   ├── app.py             # Streamlit dashboard and user interface
│   └── requirements.txt   # Frontend dependencies (Streamlit, Requests)
├── data/                  # Persistent SQLite database storage (meettrack.db)
├── docs/                  # Architecture and configuration documentation
├── .env.example           # Environment configuration template
└── pyproject.toml         # Python tool configurations (Ruff, Mypy, Pytest)
```

---

## Prerequisites

- **Operating System**: Windows 10/11, macOS, or Linux
- **Python**: Python `3.11` to `3.13` installed and accessible from terminal
- **Ollama**: Local Ollama server (v0.4+) installed
- **Model**: `qwen2.5:1.5b` pulled into Ollama
- **Git**: For source control

---

## Initial Setup on Windows (PowerShell)

Run the following commands in PowerShell from the repository root:

```powershell
# 1. Navigate to the repository root
cd "D:\Agentic AI\MeetTrack\meettrack"

# 2. Create the Python virtual environment (if not already created)
python -m venv .venv

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install backend and frontend dependencies
pip install -r backend\requirements-dev.txt
pip install -r frontend\requirements.txt

# 5. Create your environment configuration file from template
Copy-Item .env.example .env
```

> **Note**: Database initialization happens automatically on the first backend API request. No manual database creation or migration command is required.

---

## Configure Ollama

MeetTrack uses local Ollama by default, requiring no paid cloud API keys.

### 1. Verify Ollama Installation
```powershell
ollama --version
```

### 2. Verify or Download the Model
Check if the required model is installed:
```powershell
ollama list
```
If `qwen2.5:1.5b` is not listed, download it:
```powershell
ollama pull qwen2.5:1.5b
```

### 3. Verify Local Ollama Service
Ensure the Ollama local service is running and reachable:
```powershell
Invoke-RestMethod -Uri "http://localhost:11434/api/tags"
```
*(If Ollama is not running, launch the Ollama desktop application or run `ollama serve` in a background terminal).*

### 4. Environment Variables (`.env`)
The default configuration in `.env` connects to Ollama automatically:
```ini
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:1.5b
LLM_TIMEOUT_SECONDS=120
BACKEND_URL=http://localhost:8000
DB_PATH=data/meettrack.db
```

*(Optional: Cloud providers like Gemini or Groq can be enabled by setting `LLM_PROVIDER=gemini` or `LLM_PROVIDER=groq` and supplying their respective API keys).*

---

## Run the Application

MeetTrack requires two separate PowerShell terminals running concurrently. Both must remain open.

### Terminal 1: Backend Server (FastAPI)

```powershell
cd "D:\Agentic AI\MeetTrack\meettrack\backend"
..\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

- **Health Probe**: [http://localhost:8000/health](http://localhost:8000/health) (returns `{"status":"ok"}`)
- **Interactive OpenAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

### Terminal 2: Frontend Dashboard (Streamlit)

Open a **new** PowerShell window:

```powershell
cd "D:\Agentic AI\MeetTrack\meettrack\frontend"
..\.venv\Scripts\Activate.ps1
streamlit run app.py --server.port 8501
```

- **Dashboard UI**: [http://localhost:8501](http://localhost:8501)

---

## How to Use MeetTrack

- **Top Header**: Switch the active team, view backend connection status, switch between Light and Dark themes, or click **🎓 Guide Me** to open the interactive 8-step tutorial.
- **Dashboard**: View high-level metrics (Active Actions, Overdue Tasks, Pending Review), recent meetings, and urgent upcoming deadlines.
- **Teams**: Create new student groups with registered members, select active teams, or delete teams (with confirmation).
- **Meeting Notes**: Upload `.txt` notes or paste numbered text, choose the meeting date, toggle memory (Persistent vs Dry Run), and click **Process Notes with Local Ollama**.
- **Proposal Review**: Inspect extracted proposals showing owner, due date, agent reason, and verified line quotes. Click **Approve**, **Edit & Approve**, or **Reject**. Once reviewed, click **Commit Approved Decisions to Memory**.
- **Action Register**: Scan current team commitments with status filters, inspect full version history (`v1`, `v2`), or apply audited manual corrections.
- **Exports & Reminders**: Download the two-sheet Excel action register (`.xlsx`) and generate reminder drafts. All reminders remain strictly local drafts and are **never automatically sent**.
- **Tracky Mascot**: Anchored in the bottom-right corner, Tracky offers contextual guidance for each page and opens the interactive tutorial when clicked.

---

## Common Problems and Fixes

### 1. `Backend Unreachable` in Streamlit
- **Cause**: The FastAPI backend server is not running on port 8000.
- **Fix**: Open Terminal 1, navigate to `backend/`, and start Uvicorn:
  ```powershell
  uvicorn app.main:app --reload --port 8000
  ```

### 2. `Port 8000 already in use`
- **Cause**: An existing Uvicorn or Python process is still bound to port 8000.
- **Fix**: Identify and terminate the blocking process:
  ```powershell
  Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
  ```

### 3. Ollama Processing Times Out or Fails
- **Cause**: Ollama is not running, the model is not pulled, or CPU extraction took longer than expected.
- **Fix**:
  1. Confirm Ollama is running: `ollama list`.
  2. Ensure the model exists: `ollama pull qwen2.5:1.5b`.
  3. Ensure `LLM_TIMEOUT_SECONDS=120` is set in `.env` to allow sufficient time for CPU inference.

### 4. `Owner '...' is not a member of team` on Commit
- **Cause**: When editing a proposal, an owner name was entered that is not in the team's registered member list.
- **Fix**: In the **Teams** page, ensure student members are added to the team, or select an existing member name shown in the popover caption.

### 5. PowerShell Script Execution Disabled (`Activate.ps1`)
- **Cause**: Windows PowerShell execution policy restricts script execution.
- **Fix**: Enable local script execution in the current PowerShell session:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
  ```

---

## Limitations and Responsible Use

- **Human Verification Required**: AI action extraction can misinterpret ambiguous speaker notes or complex phrasing. Always review proposals in the approval gate before committing.
- **Inference Latency on CPU**: Running local Ollama on CPU typically takes 30–60 seconds for a full meeting note extraction.
- **Reminders Policy**: Reminder drafts generated by MeetTrack are strictly local text templates. MeetTrack does not integrate with email or messaging APIs and will never send messages automatically.
