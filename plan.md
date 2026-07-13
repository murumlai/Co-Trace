# Manufacturing Log Dashboard — Architecture Plan

## Problem Statement
Manufacturing test runs produce tracelog/log files (per the example dataset found at
`Co_Trace\Log_Files_Folder`: an FTRunner-style orchestrator log plus a `DebugLog.txt`
normally nested inside a `.zip` in the same run folder, organized as
`AllLogFiles_<ProductCode>\<UnitRunFolder>\...`). Two audiences need different views:

- **Engineers**: upload a folder or individual log files → see pass/fail, and *only when
  a unit failed*, get a most-probable root cause + suggested solution (no LLM call at all
  for passing units, to save token cost).
- **Managers**: upload folder(s) of logs for a product → see first-pass yield (FPY),
  yield trend, Pareto of top failure reasons, station/tester breakdown, and lot-to-lot
  comparison.

The dashboard has a **Home** tab (upload), an **Engineer** tab, and a **Manager** tab.

## Confirmed Decisions (from Q&A)
| Area | Decision |
|---|---|
| Stack | Python (FastAPI) backend + React frontend (separate, more customizable UI) |
| Deployment | Shared internal web server, browser-based access |
| Auth | Placeholder simple auth now; built behind a pluggable interface to swap in SSO/AD later |
| Data persistence | **Ephemeral/session-only** — no long-term DB. Yield trend is computed from timestamps within the uploaded batch itself, not accumulated across separate sessions |
| Preprocessing | A separate script (details to be defined in a **follow-up session**) extracts fields from `ftrunner.log` and/or `DebugLog.txt` (nested in a `.zip`) and emits a normalized per-unit JSON. This plan treats that as a pluggable module behind a defined interface |
| Upload | Browser drag-and-drop / folder picker (not server-side path reference); works uniformly for single file, multiple files, or large folders |
| Processing model | Async background jobs with progress tracking (upload returns immediately; UI polls/streams status) |
| Engineer LLM cost control | Failed units are grouped by **error signature** (Errorcode + normalized ErrorMsg). One LLM call per unique signature; result applied to all matching units. Engineer can force a fresh per-unit re-analysis if the grouped diagnosis doesn't fit |
| Root cause LLM | GitHub Copilot/Models API. Sensitive fields (serial numbers, IPs, hostnames, credentials, usernames) are **redacted before any data leaves the process** |
| Engineer tab detail | Minimal by default: Pass/Fail + root cause + solution; expandable to view the raw redacted log snippet the diagnosis was based on |
| Manager tab detail | FPY, yield trend chart, Pareto of top failure reasons, station/tester breakdown, lot-to-lot comparison |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  React SPA (frontend)                                               │
│  ┌────────────┐   ┌────────────────┐   ┌───────────────────────┐    │
│  │  Home tab  │   │ Engineer tab   │   │   Manager tab         │    │
│  │  (upload)  │   │ (pass/fail +   │   │ (FPY, trend, Pareto,  │    │
│  │            │   │  root cause)   │   │  station, lot compare)│    │
│  └─────┬──────┘   └────────┬───────┘   └───────────┬───────────┘    │
│        │ upload            │ poll job / get result │                │
└────────┼───────────────────┼───────────────────────┼────────────────┘
         │                                            │
         ▼                                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI backend                                                     │
│                                                                       │
│  Auth middleware (pluggable; placeholder impl now)                   │
│                                                                       │
│  Upload API ──▶ Job Orchestrator (background task) ──▶ Job Registry  │
│                        │                                (in-memory,  │
│                        ▼                                 per job_id) │
│               ┌──────────────────┐                                   │
│               │ Preprocessor      │  (interface only in this phase;  │
│               │ module            │   real ftrunner.log/DebugLog.txt │
│               │ (placeholder)     │   extraction rules defined later)│
│               └────────┬─────────┘                                   │
│                        │  normalized per-unit JSON records            │
│              ┌─────────┴─────────┐                                   │
│              ▼                   ▼                                   │
│    Manager Aggregator      Engineer Analyzer                         │
│    (FPY/trend/Pareto/      (error-signature dedup →                  │
│     station/lot compare,   redaction → GitHub Models call →          │
│     pure computation,      root cause + solution, cached             │
│     no LLM)                per signature)                            │
│                                   │                                   │
│                                   ▼                                   │
│                          Redaction module + LLM client                │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Frontend (React)
- **Home tab**: drag-and-drop / folder picker upload, mode selection (Engineer vs
  Manager isn't strictly required at upload time — same upload works for both; tabs
  just render different views of the same processed batch), upload + job progress bar.
- **Engineer tab**: per-unit list with Pass/Fail badge; failed units show root
  cause + suggested solution; row expands to show the raw redacted log snippet used for
  diagnosis; a "Re-analyze this unit" action forces a fresh per-unit LLM call.
- **Manager tab**: FPY summary card, yield trend line chart, Pareto bar chart of top
  failure reasons, station/tester breakdown chart, lot-to-lot comparison table/chart.
- **Login screen**: placeholder auth (simple credential check) gating access to the app.
- Suggested libraries: Vite + React, TanStack Query (job polling/data fetching),
  Recharts (charts) — swappable, not a hard requirement.

### 2. Backend (FastAPI)
- **Auth module**: pluggable interface; starts as simple hardcoded/basic-auth check;
  designed so SSO/AD can be swapped in later without touching route logic.
- **Upload API**: accepts multipart file/folder uploads, stores into a temp working
  directory keyed by `job_id`.
- **Job Orchestrator**: async background task per upload batch:
  1. Locates and extracts nested `.zip` files as needed to reach `DebugLog.txt`.
  2. Runs the **Preprocessor module** (see below) on `ftrunner.log` / `DebugLog.txt`
     per unit run folder → normalized per-unit JSON record.
  3. Stores records in the **Job Registry** (in-memory dict keyed by `job_id`;
     ephemeral, cleared on job expiry/cleanup — consistent with the "no long-term
     persistence" decision).
  4. Updates job progress (`processed/total` file counts) for the frontend to poll.
- **Manager Aggregator**: pure computation over the batch's per-unit JSON records —
  FPY (first attempt per serial number vs. retests), yield trend (grouped by
  timestamp/day/lot found in the logs), Pareto of Errorcode/ErrorMsg, station/tester
  breakdown (grouped by StationID/Host), lot-to-lot comparison. No LLM involved — fast
  and free.
- **Engineer Analyzer**:
  1. For each failed unit, compute an error signature (e.g., hash of
     `Errorcode + normalized ErrorMsg`).
  2. Group failed units by signature; call the LLM **once per unique signature**.
  3. Apply the cached result to all units sharing that signature.
  4. Expose a "force re-analyze" endpoint for a single unit that bypasses the cache.
  5. Passing units never trigger an LLM call.
- **Redaction module**: shared utility invoked before any data is sent to the LLM.
  Pattern-based scrubbing of serial numbers, IP addresses, hostnames,
  usernames/passwords/credential-like key=value pairs, MAC addresses. Applied to both
  the log snippet and any structured fields forwarded in the prompt.
- **LLM client module**: wraps the GitHub Copilot/Models API call; prompt template
  requests root cause + suggested solution from the redacted error context; includes
  timeout/retry/error handling and a swappable model/config setting (defaulting to a
  cost-efficient model given the token-cost sensitivity).

### 3. Preprocessor module (interface defined now, logic finalized later)
- **Input**: raw `ftrunner.log` content, plus optional `DebugLog.txt` content extracted
  from a nested `.zip` in the same unit run folder.
- **Output**: a normalized per-unit JSON record. Draft schema based on the sample
  data's observed structure:
  ```json
  {
    "serial_number": "string",
    "product_code": "string",
    "lot_id": "string",
    "op_id": "string",
    "station_id": "string",
    "start_time": "ISO-8601",
    "end_time": "ISO-8601",
    "result": "PASS | FAIL",
    "error_code": "string | null",
    "error_message": "string | null",
    "steps": [{"name": "string", "result": "PASS | FAIL", "duration_s": 0.0}],
    "source_files": ["ftrunner.log", "DebugLog.txt"]
  }
  ```
- This module is intentionally a stub/interface in this phase — exact extraction rules
  for `ftrunner.log` / `DebugLog.txt` will be defined together in a follow-up session,
  per your request.

### 4. Data flow & storage
- Uploaded raw files live in a per-job temp directory; cleaned up after job
  completion/expiry.
- Parsed results and LLM outputs live in an **in-memory job registry**, scoped to the
  running server process — nothing persisted long-term, matching the ephemeral/
  session-only decision. Tradeoff to flag: an app restart loses in-flight/completed
  job data; acceptable given the ephemeral requirement, but worth confirming.

### 5. Security
- Redaction happens **before** any content reaches the LLM client.
- Placeholder auth now; interface designed for SSO/AD swap-in later.
- No manufacturing log content is persisted beyond the active session's temp storage.

### 6. Deployment
- Single internal server running the FastAPI app (serving the API and the built React
  static assets) via Uvicorn; containerizable (Docker) for straightforward internal
  deployment. Can be split into separate frontend/backend processes later if needed.

## Open Items / Assumptions to revisit
- Exact `ftrunner.log` / `DebugLog.txt` extraction rules — **follow-up session**.
- Exact redaction pattern list — draft proposed above (serials, IPs, hostnames,
  credentials, MACs); confirm/refine once preprocessing is defined.
- Specific GitHub Models model choice/config — default to a cost-efficient model,
  configurable.
- First-pass yield retest handling (how a retest of the same serial number is
  identified vs. a first attempt) — will firm up alongside the preprocessor schema.
- Project name/location on disk — to be set when implementation starts.
