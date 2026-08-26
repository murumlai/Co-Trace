# Co-Trace

Co-Trace is a browser-based dashboard for manufacturing FTRunner logs. It parses uploaded log folders, files, or root-level zip archives and presents two views:

- **Engineer**: latest result per serial, retry history, failed-unit evidence, AI root cause/solution, and re-analysis.
- **Manager**: first-pass yield, yield trend, failure-reason Pareto, station/tester breakdown, and lot comparison.

Related planning docs: [plan.md](plan.md), [hybrid_UI.md](hybrid_UI.md), [pre-process_plan.md](pre-process_plan.md), [user_authentication_plan.md](user_authentication_plan.md), and [production_flow.md](production_flow.md).

## Current State

- `ftrunnerlog01.txt` is the source of truth for identity, timing, PASS/FAIL, `ErrorMsg`, `Errorcode` (SIMS `.itf` no longer authoritative).
- Failed runs may attach a bounded, redacted `DebugLog.txt` excerpt from nested zips; each batch writes one redacted `<product_code>.json` per product before cleanup.
- Diagnosis uses `LLM_PROVIDER` (`copilot_sdk` default, `github_models`, `offline_stub`); passing units never call the LLM.
- GitHub OAuth is required; jobs are owned by the signer, and knowledge/cache deletes are admin-only. A local `ADMIN_USERNAME`/`ADMIN_PASSWORD` sign-in also grants admin for maintenance.
- Successful diagnoses are cached and reused across uploads unless force-refreshed or the product/acronym context changes the cache key.

## Preprocessing Rules

Expected input shape:

```text
Log_Files_Folder/
  All_LogFiles_<ProductCode>/
    <UnitRunFolder>/
      ftrunnerlog01.txt
      optional logs
      optional zip containing Sequencer N/DebugLog.txt
```

The parser reads scan metadata (serial, product code, OP ID, station, host, program), per-step PASS/FAIL and durations, and the done-block result. Folders with no `ftrunnerlog01.txt` or reachable `DebugLog.txt` surface as UI warnings. Runs without a done block are classified by mode: **TestApp** treats no-done + no-ERR as PASS; **APSE** marks a no-done run FAIL when its time is below `max(5 s, avg_pass_time * 5%)` for that `(product_code, op_id)`.

## Quick Start

Backend from the repo root:

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --proxy=http://proxy-us.intel.com:912 -r backend\requirements.txt

$env:HTTPS_PROXY = "http://proxy-us.intel.com:912"
$env:HTTP_PROXY = "http://proxy-us.intel.com:912"
$env:NO_PROXY = "localhost,127.0.0.1"

# Default LLM_PROVIDER=copilot_sdk uses Copilot CLI authentication.
# You can use either `copilot auth login` or COPILOT_GITHUB_TOKEN.
copilot auth login

$env:GITHUB_CLIENT_ID = "<github.com OAuth app client id>"
$env:GITHUB_CLIENT_SECRET = "<github.com OAuth app client secret>"
$env:JWT_SECRET = "<long random session secret>"
$env:FRONTEND_URL = "http://localhost:5173"
$env:GITHUB_CALLBACK_URL = "http://localhost:8000/api/auth/github/callback"
$env:COOKIE_SECURE = "false"
$env:GITHUB_ADMIN_USERS = "<comma-separated GitHub usernames>"

.\.venv\Scripts\python.exe backend\run_backend.py
```

Frontend dev server:

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd install --proxy=http://proxy-us.intel.com:912 --https-proxy=http://proxy-us.intel.com:912
npm.cmd run dev -- --host localhost
```

Open http://localhost:5173 for Vite development. Use `localhost` consistently for the OAuth browser flow; the frontend proxies `/api` to the backend on port `8000`.

Register the local OAuth app at <https://github.com/settings/developers> with:

```text
Homepage URL: http://localhost:5173
Authorization callback URL: http://localhost:8000/api/auth/github/callback
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Compress
```

Expected shape:

```json
{"status":"ok","llm_provider":"copilot_sdk","debug":false}
```

## Single-Server Run

Build the React app, then start FastAPI. The backend serves both API routes and `frontend/dist`.

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd run build

Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe backend\run_backend.py
```

For single-server OAuth, set `FRONTEND_URL` to `http://localhost:8000` and open http://localhost:8000.

## Useful Commands

```powershell
# Backend tests
Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe -m pytest backend\tests\ -q

# Frontend build
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd run build

# Backend debug mode
Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe backend\run_backend.py --debug

# Measure preprocessed JSON size
.\.venv\Scripts\python.exe backend\scripts\measure_preprocessed.py "Log_Files_Folder\All_LogFiles_M95113-001"

# Rebuild the product-knowledge pack from source docs (LLM required)
.\.venv\Scripts\python.exe backend\scripts\build_product_knowledge.py
```

Use `npm.cmd run dev:debug` for verbose frontend API/navigation logging. If npm needs the Intel proxy:

```powershell
npm.cmd install --proxy=http://proxy-us.intel.com:912 --https-proxy=http://proxy-us.intel.com:912
```

Use `npm.cmd` in PowerShell if the local execution policy blocks `npm.ps1`.

## Configuration

Important environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `copilot_sdk` | `copilot_sdk`, `github_models`, or `offline_stub`. |
| `GITHUB_TOKEN` | empty | GitHub Models token used only when `LLM_PROVIDER=github_models`. Missing token falls back to offline stub. |
| `COPILOT_MINI_MODEL` | `gpt-5.4-mini` | Copilot mini/enrichment model. |
| `COPILOT_REASONING_MODEL` | `claude-sonnet-4.6` | Copilot final root-cause model. |
| `COPILOT_GITHUB_TOKEN` | empty | Optional GitHub token passed directly to the Copilot SDK provider. If empty, the SDK uses the logged-in Copilot CLI user. |
| `COPILOT_PROXY` | `http://proxy-us.intel.com:912` | Optional proxy for Copilot SDK subprocesses. |
| `GITHUB_CLIENT_ID` | empty | Client ID from the github.com OAuth App. |
| `GITHUB_CLIENT_SECRET` | empty | Client secret from the github.com OAuth App. Set only at runtime. |
| `GITHUB_CALLBACK_URL` | `http://localhost:8000/api/auth/github/callback` | OAuth callback registered in GitHub. |
| `FRONTEND_URL` | `http://localhost:5173` | URL to redirect users back to after sign-in. |
| `JWT_SECRET` | `dev-only-change-me` | Secret used to sign Co-Trace session cookies. Override outside local throwaway runs. |
| `COOKIE_SECURE` | `0` | Set to `1` when serving over HTTPS in production/IIS. |
| `GITHUB_ADMIN_USERS` | empty | Comma-separated GitHub usernames allowed to manage knowledge writes and protected cache entries. |
| `ADMIN_USERNAME` | `admin` | Username for the local maintenance admin login (separate from GitHub). |
| `ADMIN_PASSWORD` | empty | Password for the local maintenance admin login. Empty disables it, leaving GitHub as the only sign-in. |
| `HTTP_PROXY` / `HTTPS_PROXY` | empty | Corporate proxy for backend calls to GitHub OAuth endpoints. |
| `SESSION_TTL_S` | `2592000` | Auth session lifetime, 30 days by default. |
| `WORK_DIR` | `.cotrace_work` | Per-job uploads, job state, and analysis cache location. |
| `JOB_TTL_S` | `2592000` | Job retention window, 30 days by default. |
| `CLEANUP_JOB_WORKDIR_AFTER_RUN` | `1` | Deletes uploads/extracted files/preprocessed JSON after terminal job state. |
| `ANALYSIS_CACHE_ENABLED` | `1` | Reuses successful diagnoses across uploads. |
| `DEBUG_EXCERPT_CHAR_BUDGET` | `6000` | Max characters in failed-unit DebugLog excerpt. |
| `UPLOAD_ZIP_MAX_*` | varies | Limits root zip upload file count and uncompressed size. |
| `ZIP_MAX_*` | varies | Limits nested DebugLog zip traversal size and depth. |
| `PREPROCESSED_JSON_FORMAT` | `compact` | `compact` or `legacy`; optional gzip via `PREPROCESSED_JSON_GZIP`. |
| `PRODUCT_KNOWLEDGE_ENABLED` | `1` | Enables product-aware diagnosis (curated summaries in prompts). |
| `PRODUCT_KNOWLEDGE_SUMMARY_MODEL` | `gpt-5.4-mini` | Model that summarizes product docs at ingestion (LLM required). |
| `PRODUCT_KNOWLEDGE_SOURCE_DIRS` | `Log_Files_Folder`, `product_docs` | Folders scanned for supporting PDF/DOCX docs (`os.pathsep`-joined). |
| `PRODUCT_KNOWLEDGE_TOP_K` | `4` | Max curated sections retrieved per failure. |
| `PRODUCT_KNOWLEDGE_MAX_CONTEXT_CHARS` | `4000` | Char budget for curated summaries sent to the model. |
| `CORS_ORIGINS` | localhost dev origins | Allowed frontend origins in development. |

Set secrets at runtime only. See [backend/app/config.py](backend/app/config.py) for the full settings list and defaults.

For the default `copilot_sdk` provider, authenticate with either `copilot auth login` or `COPILOT_GITHUB_TOKEN`. Use `GITHUB_TOKEN` only when explicitly switching to `LLM_PROVIDER=github_models`.

## Product-Aware Diagnosis

Diagnosis can be grounded in curated product context. Supporting PDF/DOCX docs are
ingested once into a repo-root knowledge pack; at runtime only a few matched
summaries (never whole documents) are sent alongside the redacted failure excerpt.

- **Add docs**: drop them in `product_docs/` or `Log_Files_Folder/`, or upload from the **Knowledge** tab (admin). The product code and category are derived from the filename.
- **Ingestion**: sections are summarized by `gpt-5.4-mini` (LLM required). Generated artifacts (`product_knowledge*.json`, `*_sections.jsonl`) live at the repo root, are gitignored, and store only curated summaries — never raw document text.
- **Rebuild/invalidation**: rebuild from the Knowledge tab or `backend/scripts/build_product_knowledge.py`. The cache key folds in the product/knowledge hash, so changing knowledge invalidates stale diagnoses. The Engineer view shows whether/which product knowledge matched.

## Security and Storage

- Never commit raw logs, `.env`, tokens, `.cotrace_work`, virtualenvs, `node_modules`, build output, or any GitHub/OAuth/session secrets.
- Redaction scrubs credentials, IPs, hostnames, usernames, MACs, and serials before LLM analysis; users authenticate via GitHub and Co-Trace stores only its signed HttpOnly session cookie.
- Uploads, extracted zips, and preprocessed JSON are removed after processing by default; the analysis cache persists under `WORK_DIR`.
- In production behind IIS, set OAuth and proxy variables once on the server; users just open the app URL and sign in.

## Project Layout

```text
backend/app/
  main.py             FastAPI routes and static SPA serving
  config.py           Environment settings
  models.py           Pydantic schemas
  preprocessor.py     FTRunner parser, DebugLog discovery, product JSON writer
  orchestrator.py     Background job pipeline
  job_registry.py     Disk-backed job state and TTL cleanup
  analyzer.py         Failure signature dedup, cache, provider routing
  llm_client.py       Offline, GitHub Models, and Copilot providers
  knowledge/          Product-aware diagnosis (parsing, summarizer, retriever)
  aggregator.py       Manager metrics
  redaction.py        Sensitive-data scrubbing
  upload_storage.py   Upload and root-zip safety

frontend/src/
  App.jsx             Authenticated shell and tabs
  api.js              Fetch wrapper and session recovery
  pages/Home.jsx      Upload and progress UI
  pages/Engineer.jsx  Unit diagnostics
  pages/Manager.jsx   Yield analytics
  pages/Knowledge.jsx Product-knowledge management (upload/rebuild/delete)
  pages/About.jsx     App summary and current behavior
  components/         UI primitives and terminal log viewer
```

## Current Limitations

- DebugLog excerpt anchors and character budget may need tuning as more product families are validated.
- Per-product JSON artifacts are removed by default after processing; disable `CLEANUP_JOB_WORKDIR_AFTER_RUN` to inspect them.
- No Dockerfile or compose file is included yet.
- Existing jobs created before GitHub OAuth ownership may not be visible to newly signed-in users, but saved analysis cache entries can still be reused by matching uploads.

## Git Hygiene

Ignored generated/local content includes:

```text
Log_Files_Folder/
.cotrace_work/
.vscode/
backend/.venv/
frontend/node_modules/
frontend/dist/
product_docs/
product_knowledge.json
product_knowledge_index.json
product_knowledge_sections.jsonl
.env
```

Before committing:

```powershell
git diff --cached --name-only
git diff --cached --check
```