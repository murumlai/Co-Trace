# Co-Trace

Co-Trace is a browser-based dashboard for manufacturing FTRunner logs. It parses uploaded log folders, files, or root-level zip archives and presents two focused views:

- **Engineer**: latest result per serial, retry history, failed-unit evidence, AI-assisted root cause and suggested solution, cache controls, and manual re-analysis.
- **Manager**: first-pass yield (FPY), yield trend, Pareto of failure reasons, station/tester breakdown, and lot comparison.

Related planning docs: [plan.md](plan.md), [hybrid_UI.md](hybrid_UI.md), and [pre-process_plan.md](pre-process_plan.md).

## Current State

- `ftrunnerlog01.txt` is the source of truth for identity, step timing, PASS/FAIL, `ErrorMsg`, and `Errorcode`. SIMS `.itf` files are no longer authoritative.
- Failed PAN / HST / Aguila-style runs can attach a bounded, redacted `DebugLog.txt` excerpt found inside nested zip archives.
- Each processed batch writes one redacted `<product_code>.json` artifact per product in the per-job work directory before cleanup.
- Diagnosis uses `LLM_PROVIDER` (`copilot_sdk` by default, `github_models`, or `offline_stub`). Passing units never trigger LLM analysis.
- Completed jobs persist parsed records, warnings, progress, and analysis results in `.cotrace_work/<job_id>/job_state.json` until TTL cleanup.

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

The parser extracts:

- `scan file content:` metadata: serial, product code, OP ID, station, host, test-program name/version.
- Per-step blocks: `******<name> test start/end.******`, tolerant PASS/FAIL text, and step duration.
- `done file content:` result data: `Result`, `EndTime`, `ErrorMsg`, `Errorcode`.
- Missing-log folders as UI warnings when they contain neither `ftrunnerlog01.txt` nor a reachable `DebugLog.txt`.

Runs without a done block are classified by mode:

- **TestApp**: no done block + no ERR line = implicit PASS (K77469-400 pattern).
- **APSE**: no done block uses a two-pass threshold. The pre-scan averages explicit PASS `Total Test time(s)` per `(product_code, op_id)`. If a no-done-block APSE run is below `max(5 s, avg * 5%)`, it is marked FAIL as a FTRunner abort; otherwise it remains PASS. Products/OPIDs with no explicit PASS reference use the 5 s floor.

## Quick Start

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_backend.py
```

Frontend dev server:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 for Vite development. The frontend proxies `/api` to the backend on port `8000`.

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
cd frontend
npm run build

cd ..\backend
.\.venv\Scripts\python.exe run_backend.py
```

Open http://127.0.0.1:8000.

## Useful Commands

```powershell
# Backend tests
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q

# Frontend build
cd frontend
npm run build

# Backend debug mode
cd backend
.\.venv\Scripts\python.exe run_backend.py --debug

# Measure preprocessed JSON size
.\backend\.venv\Scripts\python.exe backend\scripts\measure_preprocessed.py "Log_Files_Folder\All_LogFiles_M95113-001"

# Rebuild the product-knowledge pack from source docs (LLM required)
.\backend\.venv\Scripts\python.exe backend\scripts\build_product_knowledge.py
```

Use `npm run dev:debug` for verbose frontend API/navigation logging. If npm needs the Intel proxy:

```powershell
npm install --proxy=http://proxy-us.intel.com:912 --https-proxy=http://proxy-us.intel.com:912
```

## Configuration

Important environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `copilot_sdk` | `copilot_sdk`, `github_models`, or `offline_stub`. |
| `GITHUB_TOKEN` | empty | GitHub Models token. Missing token falls back to offline stub. |
| `COPILOT_MINI_MODEL` | `gpt-5.4-mini` | Copilot mini/enrichment model. |
| `COPILOT_REASONING_MODEL` | `claude-sonnet-4.6` | Copilot final root-cause model. |
| `COPILOT_PROXY` | `http://proxy-us.intel.com:912` | Optional proxy for Copilot SDK subprocesses. |
| `APP_USERNAME` / `APP_PASSWORD` | `admin` / `admin` | Placeholder login credentials. Change before shared use. |
| `SESSION_TTL_S` | `28800` | Auth session lifetime. |
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

Example:

```powershell
$env:APP_USERNAME = "operator"
$env:APP_PASSWORD = "change-me"
$env:GITHUB_TOKEN = "<set-at-runtime-only>"
```

See [backend/app/config.py](backend/app/config.py) for the full settings list and defaults.

## Product-Aware Diagnosis

Diagnosis can be grounded in proprietary card/product context. Supporting
documents are preprocessed once into a curated, repo-root knowledge pack;
runtime diagnosis never loads or sends whole documents — it matches a failed
record to product knowledge by `PRODUCTCODE`, retrieves a few relevant curated
summaries, and sends only those alongside the bounded, redacted failure excerpt.

**Document workflow**

- Place PDF/DOCX docs in `product_docs/` or alongside sample logs in
  `Log_Files_Folder/`, or upload them from the **Knowledge** tab.
- Filenames drive matching and categorization. The product code is the first
  filename token when it looks like a code (e.g. `M79060-001`), otherwise the
  first code found anywhere in the name. A document maps to a single product
  code in v1.
- Category is detected from filename keywords:
  - `debug_learning` — `Debug`, `Support`, `Key Learning`, `Learning`,
    `Failure`, `Troubleshooting`, `Lesson`, `Known Issue`, `FA`, `RCA`. These
    receive the strongest retrieval boost (product-specific known failures/fixes).
  - `hld` — `HLD`, `High Level Design`, `Architecture`.
  - `product_overview` — `Card`, `Product`, `Overview`, `Board`, `Module`,
    `Datasheet`, `User Guide`, `Manual`, `Spec`.
  - `uncategorized` — anything else (lowest priority).
- v1 extracts PDF and DOCX. PPTX/XLSX/legacy Office are planned parser adapters.

**Ingestion and privacy boundary**

- Sections are summarized at ingestion by `gpt-5.4-mini` (LLM required — a
  rebuild fails fast if no LLM backend is available). Summaries become active
  immediately.
- Generated artifacts live at the repo root and are gitignored because they may
  contain proprietary summarized content:
  - `product_knowledge.json` — manifest (products, docs, hashes, category counts).
  - `product_knowledge_index.json` — retrieval index partitioned by product,
    with JSONL byte offsets.
  - `product_knowledge_sections.jsonl` — one curated section-summary per line,
    byte-offset addressable so runtime reads only matched sections.
- No raw extracted document text is stored in the generated artifacts — only
  curated summaries, section metadata, acronyms, limits/specs, and known-failure
  entries.

**Rebuild and cache invalidation**

- Rebuild from the **Knowledge** tab or with
  `backend/scripts/build_product_knowledge.py`.
- Each product's knowledge has a hash. The analysis cache key folds in the
  product code, knowledge hash, and matched section/category mix, so changing
  product knowledge automatically invalidates stale diagnoses. The prompt/cache
  version was bumped so pre-knowledge answers are not reused.
- The Engineer view shows whether product knowledge was used, which categories
  matched, and how many sections matched (or that no knowledge exists for the
  product).

## Security and Storage

- Do not commit raw logs, `.env`, tokens, `.cotrace_work`, virtual environments, `node_modules`, or frontend build output.
- Redaction removes credentials, IPs, hostnames, usernames, MAC addresses, and other secret-like values before LLM analysis.
- At-rest per-product JSON keeps serial numbers for yield math while redacting other sensitive fields; LLM-bound text scrubs serials too.
- Uploaded folders, extracted zips, and preprocessed JSON are removed after processing by default; the analysis cache persists separately under `WORK_DIR`.
- Placeholder auth uses in-memory tokens and should be replaced with SSO/AD before broader production use.

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
- SimpleAuth is temporary and not production identity.

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