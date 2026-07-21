"""Preprocessor module — FTRunner-primary.

`ftrunnerlog01.txt` is the single source of truth: for each run folder we
parse its `scan file content:` block (identity/station metadata), its
per-test step blocks, and its authoritative `done file content:` block
(Result / EndTime / ErrorMsg / Errorcode). When a failure is detected and a
`debuglog.txt` is reachable inside a nested `.zip` (motherboard-PAN /
HST_ET / Aguila flows only — add-in cards normally don't have one), a
bounded, redacted excerpt relevant to that failure is attached.

SIMS `.itf` datalog parsing has been removed. See pre-process_plan.md for
the full design and locked decisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import datetime
from typing import Iterable, Protocol

from .config import settings
from .models import StepRecord, UnitRecord
from .redaction import redact

# ---- ANSI + generic line helpers ------------------------------------------
_ANSI_RE = re.compile(r"\x1b?\[[0-9;]*m")
_RE_LOG_PREFIX = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^\]]*\]\s*")
_RE_KV = re.compile(r"^([A-Za-z_]+)\s*=\s*(.*)$")

# ---- FTRunner log patterns --------------------------------------------------
_RE_SCAN_HEADER = re.compile(r"scan file content:", re.IGNORECASE)
_RE_DONE_HEADER = re.compile(r"done file content:", re.IGNORECASE)
_RE_STEP_START = re.compile(r"\*{3,}\s*(.+?)\s*test start\.\*{3,}", re.IGNORECASE)
_RE_STEP_END = re.compile(r"\*{3,}\s*(.+?)\s*test end\.\*{3,}", re.IGNORECASE)
_RE_TEST_TIME = re.compile(r"Test time\(hh\\mm\\ss\):\s*(\d{2}):(\d{2}):(\d{2})")
_RE_TEST_START_TIME = re.compile(r"Test start time:\s*(\d{14})")
_RE_TEST_END_TIME = re.compile(r"Test end time:\s*(\d{14})")
_RE_LINE_TS = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_RE_ERR_LEVEL = re.compile(r"\d{2}:\d{2}:\d{2}\s+ERR\]")
_RE_TEST_MODE = re.compile(r"(?i)testmode\s*:\s*(\S+)")
_RE_LOTID_KV1 = re.compile(r"(?i)\blotid\s*=\s*([^;\s]+)")
_RE_LOTID_KV2 = re.compile(r"(?i)\bLotID\s*=\s*(\S+)")
_LOT_PREFIX_RE = re.compile(r"^(LOTAM2|NoLotId|ENG1|STC)_", re.IGNORECASE)

# Markers that indicate a motherboard-PAN flow (ExecutionTool.exe / Aguila /
# HST_ET), as opposed to a simpler add-in-card TestApp-only flow. Heuristic,
# tuned against the sample corpus (see pre-process_plan.md discovery notes).
_PAN_HINTS = ("hst_et", "aguila", "mb_pan_test", "executiontool.exe", "hst_mix")

_FTRUNNER_NAMES = ("ftrunnerlog", "ftrunner")
_GENERIC_DEBUG_MARKERS = ("traceback", "exception", "result : failed", "error", "fail")


class Preprocessor(Protocol):
    def iter_run_folders(self, root: str) -> Iterable[str]:
        """Yield folders that contain one unit run."""
        ...

    def process_run_folder(self, folder: str, root: str) -> UnitRecord | None:
        """Process one unit run folder using the batch root for relative metadata."""
        ...

    def process_folder(self, root: str) -> list[UnitRecord]:
        """Walk a batch root and return one normalized record per unit run."""
        ...


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _iso(ts14: str | None) -> str | None:
    if not ts14 or len(ts14) != 14:
        return None
    try:
        return datetime.strptime(ts14, "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return None


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _classify_line(text: str) -> str | None:
    """Tolerant PASS/FAIL classifier for a step's result text, matching
    `passed.`, `TEST PASSED`, `...failed.`, `Copy to STC process failed.`"""
    low = text.lower()
    if "failed" in low:
        return "FAIL"
    if "passed" in low:
        return "PASS"
    return None


def _extract_kv_block(text: str, header_re: re.Pattern[str]) -> dict[str, str]:
    """Pull the raw KEY=value lines that FTRunner dumps verbatim right after
    a `scan file content:` / `done file content:` header line."""
    m = header_re.search(text)
    if not m:
        return {}
    started = False
    out: dict[str, str] = {}
    for raw in text[m.end():].splitlines():
        line = _RE_LOG_PREFIX.sub("", raw).strip()
        if not line:
            if started:
                break
            continue
        kv = _RE_KV.match(line)
        if not kv:
            break
        out[kv.group(1)] = kv.group(2).strip()
        started = True
    return out


# ---------------------------------------------------------------------------
# Phase 2/3 — recursive DebugLog discovery + failure-relevant excerpt
# ---------------------------------------------------------------------------
def _safe_extract_member(zf: zipfile.ZipFile, member: zipfile.ZipInfo, dest_dir: str) -> str | None:
    """Extract one zip member into dest_dir, guarding against zip-slip and
    oversized entries."""
    if member.is_dir():
        return None
    if member.file_size > settings.ZIP_MAX_FILE_BYTES:
        return None
    dest_root = os.path.normpath(dest_dir)
    target = os.path.normpath(os.path.join(dest_dir, member.filename))
    if target != dest_root and not target.startswith(dest_root + os.sep):
        return None  # zip-slip guard
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            out.write(src.read(settings.ZIP_MAX_FILE_BYTES + 1)[: settings.ZIP_MAX_FILE_BYTES])
    except OSError:
        return None
    return target


def find_debuglog(folder: str) -> str | None:
    """Recursively search `*.zip` archives directly under `folder` for a
    `debuglog.txt` (case-insensitive), extracting only what's needed into a
    scratch subdir. Absence is normal — add-in cards don't use the
    motherboard PAN. Guards against zip-slip and zip-bombs via size/depth
    caps (see `ZIP_MAX_*` settings)."""
    extract_root = os.path.join(folder, "_cotrace_extracted")
    budget = {"used": 0}

    def _walk(zip_path: str, depth: int) -> str | None:
        if depth > settings.ZIP_MAX_DEPTH or budget["used"] > settings.ZIP_MAX_TOTAL_BYTES:
            return None
        try:
            with zipfile.ZipFile(zip_path) as zf:
                infos = zf.infolist()
                if sum(i.file_size for i in infos) > settings.ZIP_MAX_TOTAL_BYTES:
                    return None  # zip-bomb guard
                safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(zip_path))
                dest_dir = os.path.join(extract_root, f"d{depth}_{safe_stem}")
                nested: list[zipfile.ZipInfo] = []
                for info in infos:
                    low = info.filename.lower()
                    if low.endswith("debuglog.txt"):
                        extracted = _safe_extract_member(zf, info, dest_dir)
                        if extracted:
                            budget["used"] += info.file_size
                            return extracted
                    elif low.endswith(".zip"):
                        nested.append(info)
                for info in nested:
                    if budget["used"] > settings.ZIP_MAX_TOTAL_BYTES:
                        break
                    extracted = _safe_extract_member(zf, info, dest_dir)
                    if not extracted:
                        continue
                    budget["used"] += info.file_size
                    found = _walk(extracted, depth + 1)
                    if found:
                        return found
        except (zipfile.BadZipFile, OSError):
            return None
        return None

    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if name.lower().endswith(".zip"):
            found = _walk(os.path.join(folder, name), 1)
            if found:
                return found
    return None


def extract_debug_excerpt(
    debug_text: str,
    error_code: str | None,
    error_message: str | None,
    failing_step: str | None,
    char_budget: int | None = None,
) -> str | None:
    """Bounded, redacted excerpt from DebugLog.txt relevant to the
    FTRunner-detected failure. Tries a specific match first (error code /
    error message / failing step text appearing verbatim in the DebugLog —
    e.g. a bin description line), then generic failure markers, then a tail
    fallback. Redacted with `keep_serial=True` since this text is meant for
    the at-rest per-product JSON."""
    budget = char_budget or settings.DEBUG_EXCERPT_CHAR_BUDGET
    text = _strip_ansi(debug_text)
    if not text.strip():
        return None

    match_pos: int | None = None
    for needle in (error_code, error_message, failing_step):
        if not needle:
            continue
        idx = text.find(needle)
        if idx != -1:
            match_pos = idx
            break

    if match_pos is None:
        low = text.lower()
        best = -1
        for marker in _GENERIC_DEBUG_MARKERS:
            idx = low.rfind(marker)
            if idx > best:
                best = idx
        match_pos = best if best != -1 else None

    if match_pos is None:
        excerpt = text[-budget:]
    else:
        half = budget // 2
        start = max(0, match_pos - half)
        end = min(len(text), match_pos + half)
        excerpt = text[start:end]

    return redact(excerpt.strip(), keep_serial=True) or None


def find_incomplete_folders(root: str) -> list[str]:
    """Run folders with neither `ftrunnerlog01.txt` nor any reachable
    `debuglog.txt` (loose or nested in a zip). Surfaced as UI warnings —
    not treated as an error."""
    incomplete: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "_cotrace_extracted"]
        if not filenames:
            continue
        if any(FtrunnerPreprocessor._is_ftrunner(f) for f in filenames):
            continue
        if any(f.lower() == "debuglog.txt" for f in filenames):
            continue
        zips = [f for f in filenames if f.lower().endswith(".zip")]
        if zips and any(_zip_contains_debuglog(os.path.join(dirpath, f)) for f in zips):
            continue
        incomplete.append(os.path.relpath(dirpath, root))
    return incomplete


def _zip_contains_debuglog(zip_path: str) -> bool:
    """Lightweight namelist check (no extraction) used only for the warning
    scan above."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return any(n.lower().endswith("debuglog.txt") for n in zf.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


# ---------------------------------------------------------------------------
# FtrunnerPreprocessor
# ---------------------------------------------------------------------------
class FtrunnerPreprocessor:
    """ftrunnerlog-primary implementation. See module docstring."""

    def process_folder(self, root: str) -> list[UnitRecord]:
        records: list[UnitRecord] = []
        for run_folder in self.iter_run_folders(root):
            rec = self.process_run_folder(run_folder, root)
            if rec is not None:
                records.append(rec)
        return records

    # -- discovery ------------------------------------------------------
    def iter_run_folders(self, root: str) -> Iterable[str]:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "_cotrace_extracted"]
            if any(self._is_ftrunner(f) for f in filenames):
                yield dirpath

    @staticmethod
    def _is_ftrunner(name: str) -> bool:
        low = name.lower()
        return low.endswith(".txt") and any(t in low for t in _FTRUNNER_NAMES)

    # -- per-run ------------------------------------------------------------
    def process_run_folder(self, folder: str, root: str) -> UnitRecord | None:
        files = os.listdir(folder)
        ft_files = [f for f in files if self._is_ftrunner(f)]
        if not ft_files:
            return None  # "neither file" folders are surfaced separately as warnings

        raw_text = _read(os.path.join(folder, ft_files[0]))
        text = _strip_ansi(raw_text)
        source_files = [ft_files[0]]

        meta = _extract_kv_block(text, _RE_SCAN_HEADER)
        done = self._parse_done_block(text)
        steps, failing_step, ftrunner_snippet = self._parse_steps(text, done)

        result = done["result"]
        err_code = done["error_code"]
        err_msg = done["error_message"]

        start_m = _RE_TEST_START_TIME.search(text)
        start_iso = _iso(start_m.group(1)) if start_m else None
        end_iso = done["end_time"]
        if not end_iso:
            end_m = _RE_TEST_END_TIME.search(text)
            end_iso = _iso(end_m.group(1)) if end_m else None
        stamps = None
        if not start_iso or not end_iso:
            stamps = _RE_LINE_TS.findall(text)
        if not start_iso and stamps:
            start_iso = stamps[0].replace(" ", "T")
        if not end_iso and stamps:
            end_iso = stamps[-1].replace(" ", "T")
        duration_s = self._compute_duration(start_iso, end_iso, steps)

        lot_id = self._parse_lot_id(text, folder)
        test_mode_m = _RE_TEST_MODE.search(text)
        test_mode = test_mode_m.group(1) if test_mode_m else None
        device_class = self._classify_device(text, steps, test_mode)

        has_debuglog = False
        debug_excerpt = None
        if result == "FAIL":
            debug_path = find_debuglog(folder)
            if debug_path:
                has_debuglog = True
                debug_excerpt = extract_debug_excerpt(
                    _read(debug_path), err_code, err_msg, failing_step,
                )

        rel = os.path.relpath(folder, root)
        unit_id = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]

        return UnitRecord(
            unit_id=unit_id,
            serial_number=meta.get("SERIALNUMBER"),
            product_code=meta.get("PRODUCTCODE"),
            lot_id=lot_id,
            op_id=meta.get("OPID"),
            station_id=meta.get("STATIONID"),
            host=meta.get("Host") or meta.get("HOST"),
            start_time=start_iso,
            end_time=end_iso,
            duration_s=duration_s,
            result=result,
            error_code=err_code,
            error_message=err_msg,
            failing_step=failing_step,
            steps=steps,
            source_files=source_files,
            run_folder=rel,
            tp_name=meta.get("TPDIR_NAME"),
            tp_version=meta.get("TPDIR_VERSION"),
            test_mode=test_mode,
            device_class=device_class,
            has_debuglog=has_debuglog,
            debug_excerpt=debug_excerpt,
            ftrunner_snippet=ftrunner_snippet,
            redacted_snippet=ftrunner_snippet,
        )

    # -- FTRunner parsing ---------------------------------------------------
    @staticmethod
    def _parse_done_block(text: str) -> dict[str, str | None]:
        raw = _extract_kv_block(text, _RE_DONE_HEADER)
        if raw:
            result_raw = (raw.get("Result") or "").upper()
            result = result_raw if result_raw in ("PASS", "FAIL") else "UNKNOWN"
            return {
                "result": result,
                "end_time": raw.get("EndTime"),
                "error_code": raw.get("Errorcode") if result == "FAIL" else None,
                "error_message": raw.get("ErrorMsg") if result == "FAIL" else None,
            }
        # Some simple TestApp/APSE flows only emit a "done file content:"
        # block on failure; a clean run just backs up the log with no result
        # line at all. Absence of an ERR-level log line means FTRunner never
        # flagged anything, so treat it as an implicit PASS.
        if _RE_ERR_LEVEL.search(text):
            return {
                "result": "FAIL",
                "end_time": None,
                "error_code": "UNKNOWN",
                "error_message": "FTRunner reported an error (see source log for detail).",
            }
        return {"result": "PASS", "end_time": None, "error_code": None, "error_message": None}

    @staticmethod
    def _parse_steps(
        text: str, done: dict[str, str | None]
    ) -> tuple[list[StepRecord], str | None, str | None]:
        starts = list(_RE_STEP_START.finditer(text))
        done_m = _RE_DONE_HEADER.search(text)
        done_pos = done_m.start() if done_m else len(text)

        steps: list[StepRecord] = []
        for i, sm in enumerate(starts):
            name = sm.group(1).strip()
            block_start = sm.end()
            block_end = starts[i + 1].start() if i + 1 < len(starts) else done_pos
            block_text = text[block_start:block_end]

            em = _RE_STEP_END.search(block_text)
            is_last = i == len(starts) - 1
            if em:
                result_zone = block_text[: em.start()]
                dur_zone = block_text[em.end():]
            else:
                # Dangling step with no explicit "test end" marker (e.g. the
                # HST_ET / MB_PAN_TEST leg, whose result comes from the bin
                # lookup rather than a printed pass/fail line).
                result_zone = block_text
                dur_zone = block_text

            step_result = _classify_line(result_zone)
            if step_result is None and is_last:
                step_result = done["result"]
            if step_result is None:
                step_result = "UNKNOWN"

            dur_m = _RE_TEST_TIME.search(dur_zone) or _RE_TEST_TIME.search(block_text)
            duration_s = 0.0
            if dur_m:
                h, mi, s = (int(g) for g in dur_m.groups())
                duration_s = float(h * 3600 + mi * 60 + s)

            steps.append(StepRecord(name=name, result=step_result, duration_s=duration_s))

        failing_step = next((s.name for s in steps if s.result == "FAIL"), None)

        ftrunner_snippet: str | None = None
        if done["result"] == "FAIL":
            lines = ["Result: FAIL"]
            if failing_step:
                lines.append(f"Failing step: {failing_step}")
            if done["error_code"]:
                lines.append(f"Errorcode: {done['error_code']}")
            if done["error_message"]:
                lines.append(f"ErrorMsg: {done['error_message']}")
            ftrunner_snippet = "\n".join(lines)

        return steps, failing_step, ftrunner_snippet

    @staticmethod
    def _compute_duration(start_iso: str | None, end_iso: str | None, steps: list[StepRecord]) -> float:
        if start_iso and end_iso:
            try:
                delta = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
                return round(delta.total_seconds(), 3)
            except ValueError:
                pass
        return round(sum(s.duration_s for s in steps), 3)

    @staticmethod
    def _parse_lot_id(text: str, folder: str) -> str | None:
        m = _RE_LOTID_KV1.search(text) or _RE_LOTID_KV2.search(text)
        if m:
            return m.group(1).strip().rstrip(";,")
        base = os.path.basename(os.path.normpath(folder))
        pm = _LOT_PREFIX_RE.match(base)
        return pm.group(0).rstrip("_") if pm else None

    @staticmethod
    def _classify_device(text: str, steps: list[StepRecord], test_mode: str | None) -> str:
        low = text.lower()
        step_names = {s.name.lower() for s in steps}
        if any(h in low for h in _PAN_HINTS) or "mb_pan_test" in step_names or "hst_et" in step_names:
            return "pan"
        if (test_mode and test_mode.upper() == "TESTAPP") or steps:
            return "aic"
        return "unknown"


# ---------------------------------------------------------------------------
# Phase 5 — per-PRODUCTCODE JSON emission
# ---------------------------------------------------------------------------
def build_product_json(product_code: str, records: list[UnitRecord]) -> dict:
    total = len(records)
    passed = sum(1 for r in records if r.result == "PASS")
    failed = sum(1 for r in records if r.result == "FAIL")
    unknown = total - passed - failed
    fpy = round(passed / total * 100.0, 2) if total else 0.0

    units: list[dict] = []
    for r in records:
        if r.result == "FAIL":
            units.append({
                "unit_id": r.unit_id,
                "serial_number": r.serial_number,
                "result": r.result,
                "op_id": r.op_id,
                "station_id": r.station_id,
                "host": r.host,
                "lot_id": r.lot_id,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "duration_s": r.duration_s,
                "steps": [s.model_dump() for s in r.steps],
                "error_code": r.error_code,
                "error_message": redact(r.error_message, keep_serial=True) or None,
                "failing_step": r.failing_step,
                "ftrunner_snippet": redact(r.ftrunner_snippet, keep_serial=True) or None,
                "debug_excerpt": r.debug_excerpt,  # already redacted at extraction time
                "root_cause": "",
                "suggested_solution": "",
            })
        else:
            units.append({
                "serial_number": r.serial_number,
                "result": r.result,
                "op_id": r.op_id,
                "station_id": r.station_id,
                "host": r.host,
                "lot_id": r.lot_id,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "duration_s": r.duration_s,
            })

    return {
        "product_code": product_code,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {"total": total, "pass": passed, "fail": failed, "unknown": unknown, "fpy": fpy},
        "warnings": [],
        "units": units,
    }


def write_product_jsons(
    records: list[UnitRecord], output_dir: str, warnings: list[str] | None = None
) -> list[str]:
    """Group records by product_code and write one redacted
    `<product_code>.json` per group into `output_dir`. Returns the written
    file paths."""
    os.makedirs(output_dir, exist_ok=True)
    by_product: dict[str, list[UnitRecord]] = {}
    for r in records:
        by_product.setdefault(r.product_code or "UNKNOWN", []).append(r)

    written: list[str] = []
    for product_code, recs in by_product.items():
        doc = build_product_json(product_code, recs)
        if warnings:
            doc["warnings"] = list(warnings)
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", product_code)
        path = os.path.join(output_dir, f"{safe_name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        written.append(path)
    return written


def get_preprocessor() -> Preprocessor:
    return FtrunnerPreprocessor()
