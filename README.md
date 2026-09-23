# Co-Trace

Co-Trace is a browser-based dashboard for manufacturing FTRunner logs. It parses uploaded log folders, files, or root-level zip archives and presents two views:

- **Engineer**: triage worklist and signature-keyed failure clusters, search/sort/pagination, per-unit inspection with retry-vs-final-pass comparison, structured RCA (confidence, category, owner, risk, next action) linked to its log evidence, feedback, investigation actions, and redacted debug-packet export.
- **Manager**: scoped filtering, first-pass yield vs. attempts, yield trend, signature Pareto, station/tester and lot breakdowns, retest burden, qualified baseline comparison against prior batches, clickable drill-down into Engineer, and shift-review report export.

The app opens Home without sign-in. All visitors share newly created batches, feedback, and actions. Recent batches can be reopened, and explicit investigation URLs are restored after a page refresh. Browser filters and drafts are still local to each browser, not live-synchronized across users.

## Current State

- `ftrunnerlog01.txt` is the source of truth for identity, timing, PASS/FAIL, `ErrorMsg`, `Errorcode` (SIMS `.itf` no longer authoritative).
- Failed runs may attach a bounded, redacted `DebugLog.txt` excerpt from nested zips; each batch writes one redacted `<product_code>.json` per product before cleanup.
- Diagnosis uses `LLM_PROVIDER` (`copilot_sdk` default = enterprise GitHub Copilot, or `offline_stub`); the public GitHub Models path is removed, and passing units never call the LLM.
- Ordinary use needs no Microsoft/GitHub identity or app login. **Admin** opens a maintenance-only sign-in; cache deletion and knowledge/playbook/acronym mutations remain protected by backend Admin checks.
- Successful diagnoses are cached and reused across uploads unless force-refreshed or the product/acronym context changes the cache key.
- Admin-reviewed known-failure playbooks match exact failure signatures and are applied before the cache or Copilot.
- Engineer feedback and investigation actions (owner, status, handoff) persist per job under `WORK_DIR`.

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

Open http://localhost:5173 for Vite development. The frontend proxies `/api` to the backend on port `8000` and opens Home directly. To enable **Admin**, set a private `ADMIN_PASSWORD` in the backend environment before starting it. There is no default password. **Exit Admin** returns to regular mode without clearing the current batch or drafts. No password or Copilot credential is stored in browser storage.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Compress
```

Expected shape:

```json
{"status":"ok","llm_provider":"copilot_sdk","copilot_gh_host":"intel-foundry.ghe.com","debug":false,"llm_auth":{"copilot_sdk_available":true,"copilot_token_configured":false}}
```

GitHub app OAuth is retired; its old routes return HTTP 410. Copilot CLI authentication is unchanged and belongs to the backend process. Its credentials must not be distributed to browser users. Confirm organizational approval and licensing for shared backend Copilot usage.

## Single-Server Run

Build the React app, then start FastAPI. The backend serves both API routes and `frontend/dist`.

```powershell
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd run build

Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe backend\run_backend.py
```

For single-server mode, set `FRONTEND_URL` to the exact origin used in the browser (for example `http://localhost:8000`) and open that URL. Set `CORS_ORIGINS` to any additional approved frontend origins. Unexpected browser origins are rejected for API mutations.

## Common Commands

```powershell
# Backend tests
Set-Location C:\Users\lloganat\source\repos\Co_Trace
.\.venv\Scripts\python.exe -m pytest backend\tests\ -q

# Frontend helper/component tests and build
Set-Location C:\Users\lloganat\source\repos\Co_Trace\frontend
npm.cmd test
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
| `COPILOT_MINI_MIN_CONTEXT_CHARS` | `500` | Shorter failure contexts skip the mini pass and go straight to reasoning. |
| `COPILOT_GITHUB_TOKEN` | empty | Optional GitHub token passed directly to the Copilot SDK provider. If empty, the SDK uses the logged-in Copilot CLI user. |
| `COPILOT_GH_HOST` | `intel-foundry.ghe.com` | Enterprise host for Copilot auth/session. Public hosts such as `github.com` are rejected. |
| `COPILOT_PROXY` | `http://proxy-us.intel.com:912` | Optional proxy for Copilot SDK subprocesses. |
| `FRONTEND_URL` | `http://localhost:5173` | Approved browser origin for API mutations. Set to the deployed app origin. |
| `CORS_ORIGINS` | localhost and 127.0.0.1 on port 5173 | Additional approved browser origins for API reads/writes. Use exact origins, not a wildcard. |
| `JWT_SECRET` | random per process | Signs Admin cookies. Configure a strong stable secret (at least 32 characters) for persistent sessions or multiple workers; without it a restart ends Admin sessions. |
| `COOKIE_SECURE` | `0` | Set to `1` when serving over HTTPS in production/IIS. |
| `ADMIN_USERNAME` | `admin` | Username for maintenance Admin mode, not a workspace identity. |
| `ADMIN_PASSWORD` | empty | Private maintenance password. Empty disables Admin sign-in, not the shared app. |
| `WORK_DIR` | `.cotrace_work` | Per-job uploads, job state, and analysis cache location. |
| `CLEANUP_JOB_WORKDIR_AFTER_RUN` | `1` | Deletes uploads/extracted files/preprocessed JSON after terminal job state. |
| `ANALYSIS_CACHE_ENABLED` | `1` | Reuses successful diagnoses across uploads. |
| `FEEDBACK_STORE_FILE` | `WORK_DIR/feedback.json` | Engineer diagnosis feedback. |
| `INVESTIGATION_ACTION_STORE_FILE` | `WORK_DIR/investigation_actions.json` | Investigation actions and handoffs. |
| `DEBUG_EXCERPT_CHAR_BUDGET` | `6000` | Max characters in failed-unit DebugLog excerpt. |
| `PRODUCT_KNOWLEDGE_ENABLED` | `1` | Enables product-aware diagnosis (curated summaries in prompts). |
| `PRODUCT_KNOWLEDGE_SUMMARY_MODEL` | `gpt-5.4-mini` | Model that summarizes product docs at ingestion (LLM required). |
| `PRODUCT_KNOWLEDGE_SOURCE_DIRS` | `Log_Files_Folder`, `Product_Docs` | Folders scanned for supporting PDF/DOCX/XLSX docs (`os.pathsep`-joined). |
| `PRODUCT_KNOWLEDGE_PLAYBOOKS_FILE` | `admin_playbooks.json` (repo root) | Reviewed known-failure playbooks. |

See [backend/app/config.py](backend/app/config.py) for the full settings list and defaults.

For the default `copilot_sdk` provider, authenticate against `intel-foundry.ghe.com` with either `copilot auth login` or `COPILOT_GITHUB_TOKEN`. Public GitHub Models access is not available in this app.

## Product-Aware Diagnosis

Diagnosis can be grounded in curated product context. Supporting PDF/DOCX/XLSX docs are
ingested once into a repo-root knowledge pack; at runtime only a few matched
summaries (never whole documents) are sent alongside the redacted failure excerpt.

- **Add docs**: drop them in `Product_Docs/` or `Log_Files_Folder/`, or upload from the **Knowledge** tab (admin). If an uploaded filename already exists in `Product_Docs/`, choose whether to replace it or keep the old file; keeping an already-ingested file does no extra work.
- **Ingestion**: sections are summarized by `gpt-5.4-mini` (LLM required). Generated artifacts (`product_knowledge*.json`, `*_sections.jsonl`) live at the repo root, are gitignored, and store only curated summaries, never raw document text.
- **Remove/rebuild**: **Remove from pack** prunes only generated knowledge artifacts and preserves the source document. Rebuild from the Knowledge tab or `backend/scripts/build_product_knowledge.py`; changing knowledge invalidates stale diagnoses through the product/knowledge hash.
- **Coverage and playbooks**: the Knowledge tab lists failure families lacking product coverage, and admins can create, edit, or delete reviewed known-failure playbooks (stored in gitignored `admin_playbooks.json`).

## Security and Storage

- Local/generated outputs are gitignored, including `.cotrace_work`, virtualenvs, `node_modules`, `frontend/dist`, `product_docs` / `Product_Docs`, `product_knowledge*.json` artifacts, and `admin_playbooks.json`.
- This is a trusted-network prototype, not an authenticated multi-user service. Anyone who can reach it can read shared results, upload, reanalyze, stop shared jobs, and edit shared feedback/actions. Admin protects maintenance, not ordinary data access; restrict deployment with firewall/network controls and use HTTPS for shared access. Origin checks are not authentication.
- Redaction scrubs credentials, IPs, hostnames, usernames, MACs, and serials before LLM analysis. Only Admin uses a signed HttpOnly, SameSite cookie; enable `COOKIE_SECURE` with HTTPS. Ordinary action history records `shared-workspace`, not an identifiable person. Admin events carry the configured maintenance label, not proof of an individual operator.
- Uploads, extracted zips, and preprocessed JSON are removed after processing by default; the analysis cache, feedback, and investigation actions persist under `WORK_DIR`. Feedback and exported debug packets are redacted.
- Existing GitHub/admin-owned job files are preserved but are not automatically exposed in the shared job catalog. All new jobs use the stable `shared-workspace` owner through the existing registry/store contracts. Publishing old jobs and their feedback/actions requires a separately reviewed migration; existing diagnosis cache reuse remains unchanged.
- Copilot authentication failures retain the existing offline fallback and never redirect to an app login screen. No additional AI request is made to enter Home or Admin mode.

## Project Layout

```text
backend/app/
  main.py             FastAPI routes, auth, static SPA serving
  preprocessor.py     FTRunner parsing and DebugLog discovery
  analyzer.py         Failure dedup, cache, provider routing
  copilot_client.py   Enterprise Copilot SDK adapter
  knowledge/          Product-aware diagnosis pipeline and playbook store
  job_registry.py     Disk-backed job state and recent-batch listing
  analysis_cache.py   Disk-backed diagnosis cache
  comparison.py       Comparable batch baselines
  record_views.py     Signatures, serial grouping, debug-packet export
  feedback_store.py   Engineer diagnosis feedback
  investigation_action_store.py  Investigation actions and handoffs

frontend/src/
  App.jsx             Shared Home-first shell and tabs
  auth.jsx            Shared workspace context and Admin lifecycle
  api.js              Fetch wrapper and Admin permission expiry handling
  pages/              Upload, diagnostics, analytics, knowledge UI
  components/         UI primitives, recent batches, terminal log viewer
  *.js / *.test.js    Pure view-model helpers with node:test coverage
```

## Current Limitations

- DebugLog excerpt anchors and character budget may need tuning as more product families are validated.
- Per-product JSON artifacts are removed by default after processing; disable `CLEANUP_JOB_WORKDIR_AFTER_RUN` to inspect them.
- Shared workspace access does not provide per-person authorization or reliable individual audit attribution. Do not expose it publicly. Legacy private batches are not automatically migrated.