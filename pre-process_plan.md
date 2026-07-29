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
- `ftrunnerlog01.txt` is always processed first. When it detects a failure, and a
  `debuglog.txt` is available, preprocessing must search the DebugLog for details related
  to that detected failure and attach those details to the failed unit's JSON detail.
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
5. For units where `ftrunnerlog01.txt` detected a failure, use the FTRunner failure signal
    (`failing_step`, `ErrorMsg`, `Errorcode`, and nearby ftrunner failure text) to search any
    available `debuglog.txt` for more specific matching details. Strip ANSI; extract a
    bounded failure window around matched failure details first, falling back to generic
    markers (`ERROR`, `FAIL`, `Exception`, `Traceback`, `Result : Failed`, bin codes) plus a
    tail when no specific match is found; cap to a configurable char/token budget →
    `debug_excerpt`.

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
       `failing_step`, `ftrunner_snippet`, `debug_excerpt` containing DebugLog details
       relevant to the FTRunner-detected failure when available, and empty `root_cause` /
       `suggested_solution` placeholders for the future LLM step.

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
3. For a failed unit with both `ftrunnerlog01.txt` and `debuglog.txt`, assert the DebugLog
    excerpt is selected from details relevant to the FTRunner-detected failure
    (`failing_step` / `ErrorMsg` / `Errorcode`) before falling back to generic markers.
4. Assert one `<product_code>.json` is written per product; PASS units carry the Manager
   fields; FAIL units carry the deep detail.
5. Security check: grep the emitted JSON for `tr@nsf3r` and `10.250.0.1` → must be absent;
   serial numbers must remain.
6. Assert an empty / irrelevant folder produces a `job.warnings` entry visible via
   `JobStatus`.

## Open tuning items
- `debug_excerpt` char budget (default ~4–6k chars) — finalize exact markers after
  inspecting the extracted `debuglog.txt` during implementation.

## Post-implementation discovery: APSE implicit-PASS / abort classification

### Problem (2026-07-29)
Some APSE-mode runs omit a `done file content:` block and have no ERR-level log line,
so the previous implicit-PASS fallback silently marked every such run as PASS. Two
contrasting real-world patterns exist:

| Pattern | Example product | Duration | Correct result |
|---------|----------------|----------|----------------|
| FTRunner aborted before test started (e.g. `testflow.xml` not found) | N32828-201 | ~0.2 s | **FAIL** |
| Genuine APSE run, result not emitted to done file | M13983-700, M79060-001 EEPROM3 | 58–1115 s | **PASS** |

Note: the `testflow file not found` log line is **not** a reliable abort signal — it
appears in genuine M13983-700 and M79060-001 EEPROM3 runs that still complete
normally (TestProgramRunner.exe continues without it).

### Solution implemented in `FtrunnerPreprocessor`
`process_folder()` now runs a two-pass approach:

**Pass 1 — `_compute_apse_thresholds(folders)`**
- Lightweight pre-scan of every run folder.
- Collects `Total Test time(s):` from APSE runs whose `done file content:` block carries
  `Result=PASS`, grouped by `(product_code, op_id)`.
- Threshold per group = `max(_APSE_ABORT_FLOOR_S, avg_pass_duration × _APSE_ABORT_FACTOR)`
  (defaults: floor = 5.0 s, factor = 0.05).
- `(product_code, op_id)` pairs with no explicit PASS reference fall back to the 5.0 s
  floor.

**Pass 2 — main parse loop**
- Each run is processed by `process_run_folder()` as before.
- After parsing, if `result == PASS` AND `test_mode == APSE` AND
  `duration_s < threshold[(product, op_id)]` → reclassify to FAIL with message
  `"FTRunner aborted before test completed (duration: Xs, threshold: Ys)"`.

### Why group by (product_code, op_id)
M79060-001 has two distinct APSE operation types on the same product:
- `OPID=SI1`: explicit PASS runs averaging ~4900 s → threshold ≈ 245 s.
- `OPID=EEPROM3`: no explicit PASS runs, genuine runs 94–1115 s → uses 5.0 s floor.
Without grouping, SI1's high average would incorrectly penalise EEPROM3 runs.

### Corpus verification
| Product | Runs | Result after change |
|---------|------|---------------------|
| N32828-201 APSE | 3 | FAIL (0.19–0.22 s, below 5 s floor) ✓ |
| M13983-700 APSE | 107 | PASS (58–779 s, no PASS refs → 5 s floor) ✓ |
| M79060-001 APSE EEPROM3 | ~32 | PASS (94–1115 s, no PASS refs → 5 s floor) ✓ |
| M79060-001 APSE SI1 explicit PASS | 32 | PASS (unchanged, done block present) ✓ |
| M79060-001 APSE SI1 explicit FAIL | 142+ | FAIL (unchanged, done block present) ✓ |
| K77469-400 TestApp | 95 | Unaffected (check is APSE-mode-only) ✓ |
