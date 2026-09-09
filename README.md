# Co-Trace

Co-Trace is a browser-based dashboard for manufacturing FTRunner logs. It parses uploaded log folders, files, or root-level zip archives and presents two views:

- **Engineer**: latest result per serial, retry history, failed-unit evidence, AI root cause/solution, and re-analysis.
- **Manager**: first-pass yield, yield trend, failure-reason Pareto, station/tester breakdown, and lot comparison.

## Current State

- `ftrunnerlog01.txt` is the source of truth for identity, timing, PASS/FAIL, `ErrorMsg`, `Errorcode` (SIMS `.itf` no longer authoritative).
- Failed runs may attach a bounded, redacted `DebugLog.txt` excerpt from nested zips; each batch writes one redacted `<product_code>.json` per product before cleanup.
- Diagnosis uses `LLM_PROVIDER` (`copilot_sdk` default = enterprise GitHub Copilot, or `offline_stub`); the public GitHub Models path is removed, and passing units never call the LLM.
- Sign-in can use local admin credentials (`ADMIN_USERNAME`/`ADMIN_PASSWORD`) or optional GitHub OAuth. Jobs are owned by the signer, and knowledge/cache deletes are admin-only.
- Successful diagnoses are cached and reused across uploads unless force-refreshed or the product/acronym context changes the cache key.

## Input Shape and Parsing

Expected input shape:

```text
Log_Files_Folder/
  All_LogFiles_<ProductCode>/
    <UnitRunFolder>/
      ftrunnerlog01.txt
      optional logs
      optional zip containing Sequencer N/DebugLog.txt
```

The parser reads scan metadata, per-step PASS/FAIL and durations, and the done-block result. Missing `ftrunnerlog01.txt` or unreachable `DebugLog.txt` files surface as UI warnings. Runs without a done block are classified by mode: **TestApp** treats no-done + no-ERR as PASS; **APSE** marks a no-done run FAIL when its time is below `max(5 s, avg_pass_time * 5%)` for that `(product_code, op_id)`.

## Quick Start

Backend:

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --proxy=http://proxy-us.intel.com:912 -r backend\requirements.txt

$env:HTTPS_PROXY = "http://proxy-us.intel.com:912"
$env:HTTP_PROXY = "http://proxy-us.intel.com:912"
$env:NO_PROXY = "localhost,127.0.0.1"

# AI diagnosis uses enterprise GitHub Copilot only (LLM_PROVIDER=copilot_sdk,
# the default). Authenticate the Copilot CLI against the enterprise host:
copilot auth login
$env:COPILOT_GH_HOST = "intel-foundry.ghe.com"   # enterprise host (default; hard-enforced)
$env:LLM_PROVIDER = "copilot_sdk"

$env:ADMIN_USERNAME = "admin"
$env:JWT_SECRET = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$env:FRONTEND_URL = "http://localhost:5173"
$env:COOKIE_SECURE = "false"

.\.venv\Scripts\python.exe backend\run_backend.py --debug
```

Frontend dev server:

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd install --proxy=http://proxy-us.intel.com:912 --https-proxy=http://proxy-us.intel.com:912
npm.cmd run dev -- --host localhost
```

Open http://localhost:5173 for Vite development. The frontend proxies `/api` to the backend on port `8000`. Use the **Sign in as Admin** path with the local credentials above.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Compress
```

Expected shape:

```json
{"status":"ok","llm_provider":"copilot_sdk","copilot_gh_host":"intel-foundry.ghe.com","debug":false,"llm_auth":{"copilot_sdk_available":true,"copilot_token_configured":false}}
```

Optional GitHub OAuth sign-in still exists for deployments that need per-user GitHub identities. Configure `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_CALLBACK_URL`, and `GITHUB_ADMIN_USERS`; otherwise local admin sign-in is enough for local/internal testing.

## Single-Server Run

Build the React app, then start FastAPI. The backend serves both API routes and `frontend/dist`.

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd run build

Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe backend\run_backend.py
```

If optional OAuth is enabled for single-server mode, set `FRONTEND_URL` to `http://localhost:8000` and open http://localhost:8000.

## Common Commands

```powershell
# Backend tests
Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe -m pytest backend\tests\ -q

# Frontend build
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd run build

# Measure preprocessed JSON size
.\.venv\Scripts\python.exe backend\scripts\measure_preprocessed.py "Log_Files_Folder\All_LogFiles_M95113-001"

# Rebuild the product-knowledge pack from source docs (LLM required)
.\.venv\Scripts\python.exe backend\scripts\build_product_knowledge.py
```

## Configuration

Most-used environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `copilot_sdk` | `copilot_sdk` for enterprise Copilot, or `offline_stub` for the deterministic local heuristic. Other values are rejected at startup. |
| `COPILOT_MINI_MODEL` | `gpt-5.4-mini` | Copilot mini/enrichment model. |
| `COPILOT_REASONING_MODEL` | `claude-sonnet-5` | Copilot final root-cause model. |
| `COPILOT_GITHUB_TOKEN` | empty | Optional GitHub token passed directly to the Copilot SDK provider. If empty, the SDK uses the logged-in Copilot CLI user. |
| `COPILOT_GH_HOST` | `intel-foundry.ghe.com` | Enterprise host for Copilot auth/session. Public hosts such as `github.com` are rejected. |
| `COPILOT_PROXY` | `http://proxy-us.intel.com:912` | Optional proxy for Copilot SDK subprocesses. |
| `FRONTEND_URL` | `http://localhost:5173` | URL to redirect users back to after sign-in. |
| `JWT_SECRET` | `dev-only-change-me` | Secret used to sign Co-Trace session cookies. Override outside local throwaway runs. |
| `COOKIE_SECURE` | `0` | Set to `1` when serving over HTTPS in production/IIS. |
| `ADMIN_USERNAME` | `admin` | Username for the local maintenance admin login (separate from GitHub). |
| `ADMIN_PASSWORD` | `admin` | Password for the local maintenance admin login. Set to empty to disable the local admin sign-in path. |
| `WORK_DIR` | `.cotrace_work` | Per-job uploads, job state, and analysis cache location. |
| `CLEANUP_JOB_WORKDIR_AFTER_RUN` | `1` | Deletes uploads/extracted files/preprocessed JSON after terminal job state. |
| `ANALYSIS_CACHE_ENABLED` | `1` | Reuses successful diagnoses across uploads. |
| `DEBUG_EXCERPT_CHAR_BUDGET` | `6000` | Max characters in failed-unit DebugLog excerpt. |
| `PRODUCT_KNOWLEDGE_ENABLED` | `1` | Enables product-aware diagnosis (curated summaries in prompts). |
| `PRODUCT_KNOWLEDGE_SUMMARY_MODEL` | `gpt-5.4-mini` | Model that summarizes product docs at ingestion (LLM required). |
| `PRODUCT_KNOWLEDGE_SOURCE_DIRS` | `Log_Files_Folder`, `product_docs` | Folders scanned for supporting PDF/DOCX docs (`os.pathsep`-joined). |

See [backend/app/config.py](backend/app/config.py) for the full settings list and defaults.

For the default `copilot_sdk` provider, authenticate against `intel-foundry.ghe.com` with either `copilot auth login` or `COPILOT_GITHUB_TOKEN`. Public GitHub Models access is not available in this app.

## Product-Aware Diagnosis

Diagnosis can be grounded in curated product context. Supporting PDF/DOCX/XLSX docs are
ingested once into a repo-root knowledge pack; at runtime only a few matched
summaries (never whole documents) are sent alongside the redacted failure excerpt.

- **Add docs**: drop them in `product_docs/` or `Log_Files_Folder/`, or upload from the **Knowledge** tab (admin). The product code and category are derived from the filename.
- **Ingestion**: sections are summarized by `gpt-5.4-mini` (LLM required). Generated artifacts (`product_knowledge*.json`, `*_sections.jsonl`) live at the repo root, are gitignored, and store only curated summaries, never raw document text.
- **Rebuild/invalidation**: rebuild from the Knowledge tab or `backend/scripts/build_product_knowledge.py`. The cache key folds in the product/knowledge hash, so changing knowledge invalidates stale diagnoses. The Engineer view shows whether/which product knowledge matched.

## Security and Storage

- Local/generated outputs are gitignored, including `.cotrace_work`, virtualenvs, `node_modules`, `frontend/dist`, `product_docs`, and `product_knowledge*.json` artifacts.
- Redaction scrubs credentials, IPs, hostnames, usernames, MACs, and serials before LLM analysis; users authenticate via local admin credentials or optional GitHub OAuth, and Co-Trace stores only its signed HttpOnly session cookie.
- Uploads, extracted zips, and preprocessed JSON are removed after processing by default; the analysis cache persists under `WORK_DIR`.
- In production behind IIS, set the chosen auth variables and proxy values once on the server; users just open the app URL and sign in.

## Project Layout

```text
backend/app/
  main.py             FastAPI routes, auth, static SPA serving
  preprocessor.py     FTRunner parsing and DebugLog discovery
  analyzer.py         Failure dedup, cache, provider routing
  copilot_client.py   Enterprise Copilot SDK adapter
  knowledge/          Product-aware diagnosis pipeline
  job_registry.py     Disk-backed job state
  analysis_cache.py   Disk-backed diagnosis cache

frontend/src/
  App.jsx             Authenticated shell and tabs
  api.js              Fetch wrapper and session recovery
  pages/              Upload, diagnostics, analytics, knowledge UI
  components/         UI primitives and terminal log viewer
```

## Current Limitations

- DebugLog excerpt anchors and character budget may need tuning as more product families are validated.
- Per-product JSON artifacts are removed by default after processing; disable `CLEANUP_JOB_WORKDIR_AFTER_RUN` to inspect them.
- Jobs created under a different login are not visible to the current signer, but matching saved diagnoses can still be reused.