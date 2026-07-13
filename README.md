# Co_Trace — Manufacturing Log Dashboard

Browser-based dashboard for manufacturing test logs. See [plan.md](plan.md) for the
full architecture and [designUI.md](designUI.md) for the Neumorphism (Soft UI) design
system that the frontend implements.

- **Home** — drag-and-drop / folder upload with async job progress.
- **Engineer** — per-unit Pass/Fail; failed units get a most-probable root cause +
  suggested solution (one LLM call per unique error signature, cached; passing units
  never call the LLM). Expand a row for the redacted log snippet; re-analyze on demand.
- **Manager** — first-pass yield, yield trend, failure Pareto, station breakdown,
  lot-to-lot comparison. Pure computation, no LLM.

Data is **ephemeral** (in-memory job registry, temp upload dir); nothing is persisted
long-term. Sensitive fields (serials, IPs, hostnames, credentials, MACs) are **redacted
before any content reaches the LLM**.

## Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Optional environment variables:

| Var | Default | Purpose |
|-----|---------|---------|
| `GITHUB_TOKEN` | _(empty)_ | GitHub Models token. If unset, the analyzer uses an offline deterministic stub (no external calls). |
| `LLM_MODEL` | `gpt-4o-mini` | Cost-efficient default model. |
| `APP_USERNAME` / `APP_PASSWORD` | `admin` / `admin` | Placeholder auth credentials. |

## Frontend (React + Vite + Tailwind)

```powershell
cd frontend
npm install
npm run dev
```

Dev server runs at http://localhost:5173 and proxies `/api` to the backend on `:8000`.

### Production (single server)

```powershell
cd frontend
npm run build          # emits frontend/dist
cd ..\backend
uvicorn app.main:app --port 8000
```

The backend serves the built SPA from `frontend/dist` when present.

## Project layout

```
backend/app/
  main.py          FastAPI routes + static SPA serving
  auth.py          Pluggable auth (SimpleAuth placeholder)
  config.py        Env-driven settings
  models.py        Pydantic schemas
  preprocessor.py  Pluggable log parser (FTRunner placeholder impl)
  orchestrator.py  Async job pipeline + progress
  job_registry.py  In-memory ephemeral job store
  aggregator.py    Manager metrics (FPY, trend, Pareto, stations, lots)
  analyzer.py      Engineer error-signature dedup + analysis
  redaction.py     Pre-LLM scrubbing
  llm_client.py    GitHub Models client (+ offline stub)
frontend/src/
  pages/           Login, Home, Engineer, Manager
  components/ui.jsx Neumorphic primitives
```
