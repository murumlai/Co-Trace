# Plan: FTRunner + DebugLog Local Preprocessing

## Overview
Rewrite the preprocessor to be **ftrunnerlog-primary**. For each uploaded run folder, parse
`ftrunnerlog01.txt`, recursively dig into any `.zip` to find a nested `debuglog.txt`
(motherboard-PAN only), extract failure-relevant sections, strip ANSI + redact secrets
(keep serial), and emit **one redacted `.json` per PRODUCTCODE** into the per-job working
directory. The JSON is the single local artifact serving **both** the Engineer and Manager
tabs. **No LLM call** in this task — prompt design comes later.

## Discovery findings (verified from sample data)
- `ftrunnerlog01.txt` is rich and self-contained:
  - `scan file content:` block → `SERIALNUMBER`, `PRODUCTCODE`, `OPID`, `USER`, `SHIFT`,
    `STATIONID`, `Host`, `TestServer`, `TPDIR_NAME`, `TPDIR_VERSION`, `CHILD_SN`.
  - Per-test blocks: `******<TestName> test start.******` … result …
    `******<TestName> test end.*****`, `Test time(hh\mm\ss): HH:MM:SS`.
  - `done file content:` block = authoritative: `Result=PASS|FAIL`, `EndTime=`,
    `SerialNumber=`, and on fail `ErrorMsg=`, `Errorcode=` (e.g. `FFFFFFFF`).
  - Final ANSI-colored `[41mFAIL` / `[42mPASS`. ANSI codes (`[31m/[33m/[34m/[41m/[42m`)
    embedded throughout → must strip.
  - Contains secrets: `-u sysc -p tr@nsf3r`, UNC IPs `\\10.250.0.1` → redaction required.
- `DebugLog.txt` lives nested inside a `.zip` (ITUFF archive from `ExecutionTool.exe` for
  motherboard-PAN / HST_ET / Aguila tests). Sample:
  `Log_Files_Folder/All_LogFiles_M95113-001/NoLotId_RMPT51700047_SI2_20250504040511/NoLotId_20250504034917.zip`
  → `Sequencer 1/…/debuglog.txt`. Must recurse into each run folder, find the `.zip`,
  extract, and recurse again for `debuglog.txt`.
- Add-in cards and simpler devices do **not** use the motherboard PAN, so only
  `ftrunnerlog01.txt` is present (no DebugLog). This is normal, not an error.
- Existing `preprocessor.py` uses `SIMS!*.itf` as the authoritative PASS/FAIL source; this
  is being replaced by ftrunnerlog-primary parsing.
- Folder layout: `All_LogFiles_<ProductCode>/<run_folder>/ftrunnerlog01.txt` (+ other txt,
  optional `SIMS!*.itf`, optional zip). One run folder = one unit test run.

## Locked decisions
- **One JSON per PRODUCTCODE**, written to the per-job working dir (ephemeral, Option A).
- **ftrunnerlog-primary**; SIMS `.itf` reliance dropped.
- **Assembly number = PRODUCTCODE**.
- **PASS units** = compact metadata sufficient for Manager metrics; **FAIL units** = full
  detail.
- **Redact at rest** in the saved JSON, but **keep serial number** (needed for yield).
- Folder with **neither** `ftrunnerlog01.txt` nor `debuglog.txt` → surface as a **UI
  warning**.
- **LLM / prompt design deliberately out of scope** for this task. Only produce the local
  JSON. `analyzer.py` and `llm_client.py` are not modified.

## Steps

### Phase 1 — Rewrite FTRunner parsing (`backend/app/preprocessor.py`)
1. Parse the `scan file content:` block → `serial_number`, `product_code` (= assembly),
   `op_id`, `station_id`, `host`, `tp_name`, `tp_version`, `user`, `shift`.
2. Parse per-test blocks (`******<name> test start.******` … result …
   `Test time(hh\mm\ss)`) → `StepRecord(name, result, duration_s)` using a tolerant
   PASS/FAIL classifier (`passed.`, `TEST PASSED`, `…failed.`,
   `Copy to STC process failed.`).
3. Parse the authoritative `done file content:` block → `Result`, `EndTime`, `ErrorMsg`,
   `Errorcode`. Add an ANSI stripper. Parse `lot_id` from `lotid=` / `LotID =` lines or the
   run-folder name prefix (`LOTAM2_` / `NoLotId_` / `ENG1_` / `STC_`). Drop SIMS `.itf`
   authority.

### Phase 2 — Recursive DebugLog discovery (depends on Phase 1)
4. Walk each run folder for `*.zip`; extract into a per-job temp subdir; recurse into
   extracted subfolders (e.g. `Sequencer N`) and any nested zips to locate `debuglog.txt`
   (case-insensitive). Absence is normal for add-in cards. Add zip-bomb / path-traversal
   guards and size caps.

### Phase 3 — DebugLog filtering (depends on Phase 2)
5. Strip ANSI; extract a bounded failure window around markers (`ERROR`, `FAIL`,
   `Exception`, `Traceback`, `Result : Failed`, bin codes) plus a tail; cap to a
   configurable char/token budget → `debug_excerpt`.

### Phase 4 — Models + redaction (parallel with Phases 1–3)
6. Extend `UnitRecord` (`backend/app/models.py`) with `tp_name`, `tp_version`,
   `test_mode`, `device_class` (`pan` | `aic` | `unknown`), `has_debuglog`,
   `debug_excerpt`. Add a `redact(text, keep_serial=True)` mode
   (`backend/app/redaction.py`) so at-rest JSON scrubs creds/IPs/hosts but retains the
   serial. Reuse existing `-u/-p`, UNC, IP, MAC patterns.

### Phase 5 — Per-PRODUCTCODE JSON emission (serves both tabs, depends on Phases 1–4)
7. Group records by `product_code`; write `<product_code>.json` to the job working dir:
   - `product_code`, `generated_at`.
   - `summary` → `total`, `pass`, `fail`, `unknown`, `fpy` (Manager tab).
   - `warnings[]` → run folders with neither file.
   - `units[]`:
     - **PASS** = compact metadata: `serial_number`, `result`, `op_id`, `station_id`,
       `host`, `lot_id`, `start_time`, `end_time`, `duration_s` (so Manager FPY / trend /
       station-tester / lot-to-lot aggregations work).
     - **FAIL** = full detail: the above plus `steps[]`, `error_code`, `error_message`,
       `failing_step`, `ftrunner_snippet`, `debug_excerpt`, and empty
       `root_cause` / `suggested_solution` placeholders for the future LLM step.

### Phase 6 — Orchestrator + UI warning wiring (depends on Phase 5)
8. In `run_job` (`backend/app/orchestrator.py`), collect neither-file folders into
   `job.warnings`; expose via `JobStatus`; add a frontend warning banner. Keep in-memory
   `UnitRecord`s driving the existing engineer/manager endpoints and
   `aggregator.build_manager_view`.

## Relevant files
- `backend/app/preprocessor.py` — rewrite `FtrunnerPreprocessor`
  (`process_run_folder`, `_parse_scan_block`, `_extract_nested_zips`); remove
  `_parse_itf`; add ftrunner test-block + done-block parsers, recursive zip/debuglog walk,
  and the JSON writer.
- `backend/app/models.py` — extend `UnitRecord` / `StepRecord`.
- `backend/app/redaction.py` — add `keep_serial` mode.
- `backend/app/orchestrator.py` — JSON emission + `job.warnings`.
- Not modified: `backend/app/analyzer.py`, `backend/app/llm_client.py` (LLM deferred).

## Verification
1. Smoke test across `K77469-400` (add-in card, ftrunner-only), `M44968-001` (EEPROM3),
   `M95113-001` SI2 (zip + debuglog), `M79060-001` (has `Result=FAIL` units). Assert record
   counts and that `Errorcode` / `ErrorMsg` are captured.
2. Assert `debuglog.txt` is found + extracted for
   `M95113-001/NoLotId_RMPT51700047_SI2_.../NoLotId_20250504034917.zip` and
   `debug_excerpt` is populated.
3. Assert one `<product_code>.json` is written per product; PASS units carry the Manager
   fields; FAIL units carry the deep detail.
4. Security check: grep the emitted JSON for `tr@nsf3r` and `10.250.0.1` → must be absent;
   serial numbers must remain.
5. Assert an empty / irrelevant folder produces a `job.warnings` entry visible via
   `JobStatus`.

## Open tuning items
- `debug_excerpt` char budget (default ~4–6k chars) — finalize exact markers after
  inspecting the extracted `debuglog.txt` during implementation.
