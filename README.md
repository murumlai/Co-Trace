# Co_Trace - Manufacturing Log Dashboard

Co_Trace is a browser-based dashboard for manufacturing test logs. It accepts uploaded
FTRunner-style log folders or files, parses per-unit test results, and presents two
audience-specific views:

- **Engineer view**: Pass/Fail by unit, shown as a sortable table (default) or expandable
  cards. Failed units show a most-probable root cause, suggested solution, and an
  expandable redacted snippet used for diagnosis.
- **Manager view**: First-pass yield (FPY), yield trend, Pareto of failure reasons,
  station/tester breakdown, and lot-to-lot comparison.

The implementation follows [plan.md](plan.md) and the Neumorphism/Soft UI visual system
defined in [designUI.md](designUI.md). The preprocessing design is tracked in
[pre-process_plan.md](pre-process_plan.md).

## Current Status

- FastAPI backend and React frontend are implemented as a login-gated upload, Engineer,
  and Manager dashboard.
- Frontend production build has been verified with `npm run build`.
- The preprocessor is **FTRunner-primary**: `ftrunnerlog01.txt` is the single source of
  truth for identity, per-step results, and authoritative PASS/FAIL. SIMS `.itf` reliance
  has been dropped.
- Failed units that have a nested `DebugLog.txt` (motherboard-PAN / HST_ET / Aguila flows)
  get a bounded, redacted `debug_excerpt` selected around the FTRunner-detected failure.
- Each processed batch emits one redacted `<product_code>.json` per product into the
  per-job working directory; this artifact serves both the Engineer and Manager tabs. The
  artifact is minified by default (`schema_version: 2`), omits empty/default fields, and
  can optionally be gzipped — see `PREPROCESSED_JSON_*` below.
- Job state is persisted to disk as `job_state.json` under each per-job working directory,
  restored on backend startup, and automatically deleted after the job TTL expires.
- Failed-unit diagnosis routes through a configurable provider (`LLM_PROVIDER`): GitHub
  Models (default), the GitHub Copilot SDK, or a deterministic offline stub. If the chosen
  provider is unavailable (e.g. no `GITHUB_TOKEN`, or the Copilot SDK is not installed),
  analysis degrades to the offline stub and makes no external calls.

## Key Features

- **Folder, file, or `.zip` upload** from the browser. Large batches can be uploaded as
  one root-level zip archive to avoid browser/API multipart file-count limits.
- **Async processing** with job progress polling.
- **Manual batch stop**: processing continues if the user changes tabs and only stops
  when the user clicks `Stop batch`. Stop requests are honored between processing steps
  and between LLM failure-signature calls.
- **Disk-backed result storage**: completed jobs keep parsed records, warnings, progress,
  and analysis results in `job_state.json`. Uploaded folders, extracted zip contents, and
  preprocessed artifacts are removed after processing by default; the cross-upload LLM
  cache is persisted separately under `.cotrace_work`.
- **Incomplete-folder warnings**: run folders that contain neither `ftrunnerlog01.txt` nor
  a reachable `debuglog.txt` are surfaced as a dismissible UI banner rather than silently
  dropped.
- **LLM cost control**: passing units never trigger LLM analysis. Failed units are grouped
  by error signature so the app analyzes each unique signature once and applies the result
  to matching units.
- **Manual re-analysis**: engineers can force a fresh diagnosis for an individual failed
  unit.
- **Redaction at rest and pre-LLM**: serial numbers, IP addresses, hostnames, usernames,
  passwords, credential-like key/value pairs, and MAC addresses are scrubbed. The at-rest
  per-product JSON keeps the serial number (needed for yield math) while still removing
  every other secret; LLM-bound text scrubs the serial too.
- **Session recovery**: if the bearer token becomes stale (e.g. the backend restarts), the
  frontend clears it and returns the user to the login screen with a clear message.
- **Single-server deployment path**: the FastAPI app serves the built React SPA from
  `frontend/dist`.

## Data Expectations

The parser is optimized for the observed sample structure:

```text
Log_Files_Folder/
  All_LogFiles_<ProductCode>/
    <UnitRunFolder>/
      ftrunnerlog01.txt
      optional summary_*.txt / other logs
      optional <ituff>.zip  (contains Sequencer N/DebugLog.txt for PAN flows)
```

The implemented parser uses:

- `ftrunnerlog01.txt` as the single source of truth:
  - the `scan file content:` block for serial number, product code (= assembly), OP ID,
    station ID, host, and test-program name/version;
  - per-test `******<name> test start/end.******` blocks for per-step PASS/FAIL and
    durations (ANSI codes are stripped, and a tolerant classifier handles `passed.`,
    `TEST PASSED`, `...failed.`, `Copy to STC process failed.`);
  - the authoritative `done file content:` block for `Result`, `EndTime`, `ErrorMsg`, and
    `Errorcode`. Simple TestApp/APSE flows that omit this block on success are treated as
    an implicit PASS when no error-level line is present.
- Recursive, guarded `.zip` traversal to locate a nested `DebugLog.txt` for failed units
  and extract a failure-relevant `debug_excerpt` (zip-slip / zip-bomb / depth caps apply).
  Add-in cards normally have no DebugLog, which is expected and not an error.

## Security and Privacy

- Do not commit raw manufacturing logs. `Log_Files_Folder/` is ignored by `.gitignore`.
- Do not commit `.env` files or tokens. Runtime settings should come from environment
  variables.
- The backend redacts sensitive fields before invoking the LLM client.
- Placeholder credentials default to `admin / admin`. Change these before shared use.
- Job data is persisted in `.cotrace_work/<job_id>/job_state.json`. Completed/error jobs
  survive backend restarts until their TTL expires; jobs interrupted while `running` are
  restored as `error` and should be uploaded again.

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
python run_backend.py
```

Use `python run_backend.py --debug` for verbose request, job, and Copilot-provider
logging. Each backend start rewrites `backendLog.txt` and `frontend_Log.txt` in the
repo root by default.

Backend health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Compress
```

Expected response:

```json
{"status":"ok","llm_provider":"copilot_sdk","debug":false}
```

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

Use `npm run dev -- --debug` (or `npm run dev:debug`) for verbose browser-side API
and navigation logging. The wrapper rewrites `frontend_Log.txt` and mirrors Vite
output into it on each frontend start.

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
.\.venv\Scripts\python.exe run_backend.py
```

Open http://127.0.0.1:8000.

To stop the server, press `Ctrl+C` in the terminal running Uvicorn.

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `copilot_sdk` | Diagnosis provider: `github_models`, `copilot_sdk`, or `offline_stub`. |
| `GITHUB_TOKEN` | empty | GitHub Models token. If unset, failed-unit diagnosis uses the offline stub. |
| `LLM_ENDPOINT` | `https://models.inference.ai.azure.com/chat/completions` | Chat completions endpoint. |
| `LLM_MODEL` | `gpt-5.4-mini` | Configurable GitHub Models default. |
| `LLM_TIMEOUT_S` | `30` | LLM request timeout in seconds. |
| `LLM_MAX_RETRIES` | `2` | Number of retry attempts after an LLM call failure. |
| `COPILOT_MINI_MODEL` | `gpt-5.4-mini` | Copilot SDK model for excerpt summarization/classification. |
| `COPILOT_REASONING_MODEL` | `claude-sonnet-4.6` | Copilot SDK model for final root-cause/solution. |
| `COPILOT_PROXY` | `http://proxy-us.intel.com:912` | Optional `HTTP(S)_PROXY` used by the Copilot SDK subprocess. |
| `COPILOT_TIMEOUT_S` | `60` | Per-call timeout for a Copilot SDK streaming session. |
| `COPILOT_ENABLE_MINI_ENRICH` | `1` | Run the mini summarization pass before the reasoning call. |
| `APP_USERNAME` | `admin` | Placeholder login username. |
| `APP_PASSWORD` | `admin` | Placeholder login password. |
| `SESSION_TTL_S` | `28800` | Placeholder auth session lifetime in seconds. |
| `WORK_DIR` | `.cotrace_work` under the process working directory | Temporary per-job upload storage. |
| `JOB_TTL_S` | `2592000` | Job persistence and auto-delete window in seconds (30 days). |
| `COTRACE_DEBUG` / `APP_DEBUG` | `0` | Enable verbose backend/frontend logging. Set by `run_backend.py --debug`. |
| `LOG_DIR` | current working directory | Directory for default log files. |
| `BACKEND_LOG_FILE` | `<LOG_DIR>/backendLog.txt` | Backend run log; rewritten on backend start. |
| `FRONTEND_LOG_FILE` | `<LOG_DIR>/frontend_Log.txt` | Browser/Vite frontend run log; rewritten on backend/frontend start. |
| `FRONTEND_LOG_MAX_CONTEXT_CHARS` | `4000` | Max context payload retained per frontend log line in debug mode. |
| `UPLOAD_ZIP_MAX_FILES` | `20000` | Max files allowed inside a root-level uploaded `.zip` archive. |
| `UPLOAD_ZIP_MAX_TOTAL_BYTES` | `2147483648` | Max total uncompressed bytes allowed from an uploaded `.zip`. |
| `UPLOAD_ZIP_MAX_FILE_BYTES` | `536870912` | Max uncompressed size for one file inside an uploaded `.zip`. |
| `CLEANUP_JOB_WORKDIR_AFTER_RUN` | `1` | Remove per-job uploaded files/extracted zip contents/preprocessed JSON after terminal job state. |
| `ANALYSIS_CACHE_ENABLED` | `1` | Reuse successful LLM diagnoses across uploads with the same redacted failure context/model settings. |
| `ANALYSIS_CACHE_FILE` | `<WORK_DIR>/analysis_cache.json` | Local disk cache for successful analysis results. |
| `DEBUG_EXCERPT_CHAR_BUDGET` | `6000` | Max characters for a failed unit's DebugLog excerpt. |
| `FTRUNNER_SNIPPET_CHAR_BUDGET` | `2000` | Max characters for a failed unit's FTRunner snippet (compact mode). |
| `ZIP_MAX_TOTAL_BYTES` | `209715200` | Total extraction budget per run folder (zip-bomb guard). |
| `ZIP_MAX_FILE_BYTES` | `104857600` | Max size of a single extracted zip member. |
| `ZIP_MAX_DEPTH` | `3` | Max nested-zip recursion depth for DebugLog discovery. |
| `PREPROCESSED_JSON_FORMAT` | `compact` | `compact` (minified, omits empty fields) or `legacy` (pretty, full shape). |
| `PREPROCESSED_JSON_PRETTY` | `0` | Force indented output for debugging (overrides compact minification). |
| `PREPROCESSED_JSON_GZIP` | `0` | Also write a sibling `<product_code>.json.gz`. |
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
  preprocessor.py  FTRunner-primary parser: scan/step/done blocks, DebugLog discovery,
                   per-product JSON emission, incomplete-folder warnings
  orchestrator.py  Background job pipeline, JSON emission, and progress updates
  job_registry.py  Disk-backed job registry with 30-day TTL cleanup
  aggregator.py    Manager metrics: FPY, trend, Pareto, stations, lots
  analyzer.py      Engineer signature deduplication and diagnosis flow
  redaction.py     Sensitive-data scrubbing (keep_serial mode for at-rest JSON)
  llm_client.py    Provider router (GitHub Models) with offline stub fallback
  copilot_client.py GitHub Copilot SDK provider (two-tier mini + reasoning models)

frontend/src/
  App.jsx                  Login-gated shell, Home/Engineer/Manager tabs, warning banner
  api.js                   Fetch wrapper, bearer-token handling, 401 recovery
  auth.jsx                 Placeholder auth context with session-expiry handling
  components/ui.jsx        Neumorphic UI primitives
  pages/Home.jsx           Upload and progress UI
  pages/Engineer.jsx       Unit-level diagnostics (table / cards views)
  pages/Manager.jsx        Yield and failure analytics
```

## Useful Commands

```powershell
# Backend smoke test against a sample product folder (FTRunner-primary)
.\backend\.venv\Scripts\python.exe -c "import sys, collections; sys.path.insert(0,'backend'); from app.preprocessor import get_preprocessor; from app import aggregator; recs=get_preprocessor().process_folder(r'Log_Files_Folder/All_LogFiles_M95113-001'); mv=aggregator.build_manager_view(recs); print(len(recs)); print(collections.Counter(r.result for r in recs)); print(mv['summary'])"

# Measure preprocessed JSON size (legacy vs compact vs gzip, per-field breakdown)
.\.venv\Scripts\python.exe backend\scripts\measure_preprocessed.py "Log_Files_Folder\All_LogFiles_M95113-001"

# Frontend production build
$env:Path = 'C:\Program Files\nodejs;' + $env:Path
cd frontend
npm run build

# Git status including ignored generated/local data
git status --short --ignored
```

## Current Limitations

- **DebugLog excerpt tuning**: extraction anchors on the FTRunner failure signal with a
  generic-marker fallback; the exact markers and char budget remain a tuning item.
- **Per-product JSON backfill**: in compact mode the preprocessing JSON omits the empty
  `root_cause` / `suggested_solution` placeholders (they are always empty at write time);
  Engineer diagnosis is populated later in persisted job state after the analyzer runs.
  Set `PREPROCESSED_JSON_FORMAT=legacy` to restore the fully-populated shape.
- **Docker packaging**: the app is structured to be containerized, but no Dockerfile or
  compose file is included yet.
- **Placeholder auth**: SimpleAuth is intentionally temporary (in-memory tokens do not
  survive a backend restart) and should be replaced with SSO/AD before broader production
  use.

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
