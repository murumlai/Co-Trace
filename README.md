# Co_Trace - Manufacturing Log Dashboard

Co_Trace is a browser-based dashboard for manufacturing test logs. It accepts uploaded
FTRunner-style log folders or files, parses per-unit test results, and presents two
audience-specific views:

- **Engineer view**: Pass/Fail by unit. Failed units show a most-probable root cause,
  suggested solution, and an expandable redacted snippet used for diagnosis.
- **Manager view**: First-pass yield (FPY), yield trend, Pareto of failure reasons,
  station/tester breakdown, and lot-to-lot comparison.

The implementation follows [plan.md](plan.md) and the Neumorphism/Soft UI visual system
defined in [designUI.md](designUI.md).

## Current Status

- FastAPI backend and React frontend are implemented as a login-gated upload, Engineer,
  and Manager dashboard.
- Frontend production build has been verified with `npm run build`.
- The current backend parser extracts FTRunner scan metadata and still uses SIMS `.itf`
  files as the authoritative PASS/FAIL and per-step source.
- Backend parsing has been smoke-tested against the sample `N32828-201` dataset:
  `141` unit runs, `95 PASS`, `36 FAIL`, `10 UNKNOWN`, FPY `78.65%`.
- [pre-process_plan.md](pre-process_plan.md) tracks the next FTRunner-primary,
  DebugLog-aware preprocessing rewrite. That work is planned and not yet wired into the
  API/UI path.
- GitHub Models integration is wired, but if `GITHUB_TOKEN` is not set, analysis uses a
  deterministic offline stub and makes no external LLM calls.

## Key Features

- **Folder or file upload** from the browser. No server-side path browsing is required.
- **Async processing** with job progress polling.
- **Ephemeral storage**: uploaded files and parsed results are job-scoped; no database is
  used.
- **LLM cost control**: passing units never trigger LLM analysis. Failed units are grouped
  by error signature so the app analyzes each unique signature once and applies the result
  to matching units.
- **Manual re-analysis**: engineers can force a fresh diagnosis for an individual failed
  unit.
- **Pre-LLM redaction**: serial numbers, IP addresses, hostnames, usernames, passwords,
  credential-like key/value pairs, and MAC addresses are scrubbed before data can be sent
  to the LLM client.
- **Single-server deployment path**: the FastAPI app serves the built React SPA from
  `frontend/dist`.

## Data Expectations

The current parser is optimized for the observed sample structure:

```text
Log_Files_Folder/
  All_LogFiles_<ProductCode>/
    <UnitRunFolder>/
      ftrunnerlog01.txt
      SIMS!...itf
      optional logs / zip files
```

The implemented parser currently uses:

- `ftrunnerlog*.txt` for scan-block metadata such as serial number, product code, OP ID,
  station ID, host, and timestamps.
- `SIMS!...itf` as the authoritative source for PASS/FAIL, per-step results, test time,
  lot ID, and failing bin/error reason.
- Best-effort `.zip` extraction for archives directly inside discovered run folders so
  nested files can be reached by later parsing work.

`DebugLog.txt` parsing rules are not implemented yet. The architecture keeps
preprocessing behind an interface so the FTRunner-primary, DebugLog-aware rewrite in
[pre-process_plan.md](pre-process_plan.md) can be added without changing the API or UI
contract.

## Security and Privacy

- Do not commit raw manufacturing logs. `Log_Files_Folder/` is ignored by `.gitignore`.
- Do not commit `.env` files or tokens. Runtime settings should come from environment
  variables.
- The backend redacts sensitive fields before invoking the LLM client.
- Placeholder credentials default to `admin / admin`. Change these before shared use.
- Job data is in memory. Restarting the server loses active/completed job results.

## Prerequisites

- Windows PowerShell
- Python 3.14 or another supported Python 3 version
- Node.js and npm

This repository uses Python package versions compatible with Python 3.14. Older pinned
Pydantic versions may try to build from source and require Rust, so keep
`backend/requirements.txt` current.

## Backend Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Compress
```

Expected response without an LLM token:

```json
{"status":"ok","llm":"offline-stub"}
```

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

The Vite dev server runs at http://localhost:5173 and proxies `/api` to the backend on
port `8000`.

If npm registry access requires the Intel proxy, install dependencies with:

```powershell
npm install --proxy=http://proxy-us.intel.com:912 --https-proxy=http://proxy-us.intel.com:912
```

## Single-Server Run

Build the frontend, then run FastAPI. The backend will serve both the API and the built
React app.

```powershell
cd frontend
npm run build

cd ..\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000.

To stop the server, press `Ctrl+C` in the terminal running Uvicorn.

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | empty | GitHub Models token. If unset, failed-unit diagnosis uses the offline stub. |
| `LLM_ENDPOINT` | `https://models.inference.ai.azure.com/chat/completions` | Chat completions endpoint. |
| `LLM_MODEL` | `gpt-4o-mini` | Configurable cost-conscious model default. |
| `LLM_TIMEOUT_S` | `30` | LLM request timeout in seconds. |
| `LLM_MAX_RETRIES` | `2` | Number of retry attempts after an LLM call failure. |
| `APP_USERNAME` | `admin` | Placeholder login username. |
| `APP_PASSWORD` | `admin` | Placeholder login password. |
| `SESSION_TTL_S` | `28800` | Placeholder auth session lifetime in seconds. |
| `WORK_DIR` | `.cotrace_work` under the process working directory | Temporary per-job upload storage. |
| `JOB_TTL_S` | `7200` | In-memory job expiry window in seconds. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed dev frontend origins. |

Example PowerShell configuration:

```powershell
$env:APP_USERNAME = "operator"
$env:APP_PASSWORD = "change-me"
$env:GITHUB_TOKEN = "<set-at-runtime-only>"
```

## Project Layout

```text
backend/app/
  main.py          FastAPI routes and static SPA serving
  auth.py          Pluggable auth provider with SimpleAuth placeholder
  config.py        Environment-driven settings
  models.py        Pydantic API/domain schemas
  preprocessor.py  FTRunner/SIMS parser behind a preprocessor interface
  orchestrator.py  Background job pipeline and progress updates
  job_registry.py  In-memory ephemeral job store
  aggregator.py    Manager metrics: FPY, trend, Pareto, stations, lots
  analyzer.py      Engineer signature deduplication and diagnosis flow
  redaction.py     Pre-LLM sensitive-data scrubbing
  llm_client.py    GitHub Models client with offline stub fallback

frontend/src/
  App.jsx                  Login-gated shell and Home/Engineer/Manager tabs
  api.js                   Fetch wrapper and bearer-token handling
  auth.jsx                 Placeholder auth context
  components/ui.jsx        Neumorphic UI primitives
  pages/Home.jsx           Upload and progress UI
  pages/Engineer.jsx       Unit-level diagnostics
  pages/Manager.jsx        Yield and failure analytics
```

## Useful Commands

```powershell
# Backend smoke test against the sample dataset
.\backend\.venv\Scripts\python.exe -c "import sys, collections; sys.path.insert(0,'backend'); from app.preprocessor import get_preprocessor; from app import aggregator; recs=get_preprocessor().process_folder(r'Log_Files_Folder/All_LogFiles_N32828-201'); mv=aggregator.build_manager_view(recs); print(len(recs)); print(collections.Counter(r.result for r in recs)); print(mv['summary'])"

# Frontend production build
$env:Path = 'C:\Program Files\nodejs;' + $env:Path
cd frontend
npm run build

# Git status including ignored generated/local data
git status --short --ignored
```

## Current Limitations

- **Disk cleanup**: job metadata expires from memory, but per-job upload folders are not
  deleted from disk yet.
- **DebugLog parser**: `.zip` extraction exists, but product-specific `DebugLog.txt`
  extraction rules still need to be defined and implemented.
- **Zip-only discovery**: run folders are discovered by direct FTRunner-log presence. A
  folder containing only a zip with logs inside may not be discovered yet.
- **Docker packaging**: the app is structured to be containerized, but no Dockerfile or
  compose file is included yet.
- **Placeholder auth**: SimpleAuth is intentionally temporary and should be replaced with
  SSO/AD before broader production use.

## Git Hygiene

The repo intentionally ignores generated and sensitive/local content:

```text
Log_Files_Folder/
.cotrace_work/
.vscode/
backend/.venv/
backend/app/__pycache__/
frontend/node_modules/
frontend/dist/
.env
```

Before committing, verify staged files with:

```powershell
git diff --cached --name-only
git diff --cached --check
```
