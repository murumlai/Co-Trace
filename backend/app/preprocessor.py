"""Preprocessor module.

Interface (`Preprocessor`) plus a working placeholder implementation
(`FtrunnerPreprocessor`) that extracts fields from a unit run folder:

- FTRunner log scan block -> serial / product / station / host metadata.
- SIMS `.itf` datalog -> authoritative PASS/FAIL, per-step results, and the
  failing bin -> error code/message.

The exact extraction rules are expected to evolve; keep this behind the
interface so it can be swapped without touching the orchestrator.
"""
from __future__ import annotations

import hashlib
import os
import re
import zipfile
from datetime import datetime
from typing import Iterable, Protocol

from .models import StepRecord, UnitRecord

# ---- FTRunner log patterns ------------------------------------------------
_TS = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
_RE_LINE_TS = re.compile(_TS)
_RE_KV = re.compile(r"^([A-Za-z_]+)\s*=\s*(.*)$")
_RE_START_TIME = re.compile(r"Test start time:\s*(\d{14})")
_RE_ELAPSED = re.compile(r"elapsed time:\s*([\d.]+)")

# ---- SIMS .itf datalog patterns -------------------------------------------
_RE_TRSLT = re.compile(r"(?m)^3_trslt_(\w+)")
_RE_BINN = re.compile(r"(?m)^3_binn_(\d+)")
_RE_CURFBIN = re.compile(r"(?m)^3_curfbin_(\d+)")
_RE_TTIME = re.compile(r"(?m)^3_ttime_([\d.]+)")
_RE_LOTID = re.compile(r"(?m)^6_lotid_(.+)$")
_RE_BEGINDT = re.compile(r"(?m)^4_begindt_(\d{14})")
_RE_ENDDATE = re.compile(r"(?m)^4_enddate_(\d{14})")
_RE_BINNAME = re.compile(r"(?m)^3_comnt_b(\d+)_(.+)$")
_RE_TNAME = re.compile(r"(?m)^2_tname_(.+)$")
_RE_STRGVAL = re.compile(r"(?m)^2_strgval_(.+)$")

_FTRUNNER_NAMES = ("ftrunnerlog", "ftrunner")


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


def _iso(ts14: str | None) -> str | None:
    if not ts14 or len(ts14) != 14:
        return None
    try:
        return datetime.strptime(ts14, "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return None


def _lot_from_serial(serial: str | None) -> str | None:
    if not serial:
        return None
    m = re.match(r"^([A-Za-z]+\d{2,4})", serial)
    return m.group(1) if m else serial[:6]


def _extract_nested_zips(folder: str) -> None:
    """Extract any *.zip in-place so nested logs become reachable."""
    for name in os.listdir(folder):
        if name.lower().endswith(".zip"):
            path = os.path.join(folder, name)
            try:
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(folder)
            except (zipfile.BadZipFile, OSError):
                continue


class _NoMatch:
    def group(self, _):  # tiny null-object helper for optional matches
        return None


class FtrunnerPreprocessor:
    """Placeholder implementation that parses the sample data shape."""

    def process_folder(self, root: str) -> list[UnitRecord]:
        records: list[UnitRecord] = []
        for run_folder in self.iter_run_folders(root):
            rec = self.process_run_folder(run_folder, root)
            if rec is not None:
                records.append(rec)
        return records

    # -- discovery ----------------------------------------------------------
    def iter_run_folders(self, root: str) -> Iterable[str]:
        for dirpath, _dirnames, filenames in os.walk(root):
            if any(self._is_ftrunner(f) for f in filenames):
                yield dirpath

    @staticmethod
    def _is_ftrunner(name: str) -> bool:
        low = name.lower()
        return low.endswith(".txt") and any(t in low for t in _FTRUNNER_NAMES)

    @staticmethod
    def _is_itf(name: str) -> bool:
        return name.lower().endswith(".itf")

    # -- per-run ------------------------------------------------------------
    def process_run_folder(self, folder: str, root: str) -> UnitRecord | None:
        _extract_nested_zips(folder)
        files = os.listdir(folder)
        ft_files = [f for f in files if self._is_ftrunner(f)]
        if not ft_files:
            return None

        ft_text = _read(os.path.join(folder, ft_files[0]))
        meta = self._parse_scan_block(ft_text)
        source_files = [ft_files[0]]

        start_m = _RE_START_TIME.search(ft_text)
        start_iso = _iso(start_m.group(1)) if start_m else None
        elapsed_m = _RE_ELAPSED.search(ft_text)
        elapsed = float(elapsed_m.group(1)) if elapsed_m else 0.0
        first_ts, last_ts = self._parse_ts_bounds(ft_text)

        result = "UNKNOWN"
        err_code: str | None = None
        err_msg: str | None = None
        steps: list[StepRecord] = []
        snippet: str | None = None
        lot_id = _lot_from_serial(meta.get("SERIALNUMBER"))

        itf_files = [f for f in files if self._is_itf(f)]
        if itf_files:
            itf_text = _read(os.path.join(folder, itf_files[0]))
            source_files.append(itf_files[0])
            parsed = self._parse_itf(itf_text)
            result = parsed["result"]
            err_code = parsed["error_code"]
            err_msg = parsed["error_message"]
            steps = parsed["steps"]
            snippet = parsed["snippet"]
            lot_id = parsed["lot_id"] or lot_id
            start_iso = _iso(parsed["begin"]) or start_iso
            last_ts = _iso(parsed["end"]) or last_ts
            if parsed["duration"]:
                elapsed = parsed["duration"]

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
            start_time=start_iso or first_ts,
            end_time=last_ts,
            duration_s=round(elapsed, 3),
            result=result,
            error_code=err_code,
            error_message=err_msg,
            steps=steps,
            source_files=source_files,
            run_folder=rel,
            redacted_snippet=snippet,
        )

    # -- FTRunner parsing ---------------------------------------------------
    @staticmethod
    def _parse_scan_block(text: str) -> dict[str, str]:
        meta: dict[str, str] = {}
        for raw in text.splitlines():
            m = _RE_KV.match(raw.strip())
            if m:
                meta[m.group(1)] = m.group(2).strip()
        return meta

    @staticmethod
    def _parse_ts_bounds(text: str) -> tuple[str | None, str | None]:
        stamps = _RE_LINE_TS.findall(text)
        if not stamps:
            return None, None
        return stamps[0].replace(" ", "T"), stamps[-1].replace(" ", "T")

    # -- SIMS .itf parsing --------------------------------------------------
    @staticmethod
    def _parse_itf(text: str) -> dict:
        result_raw = (_RE_TRSLT.search(text) or _NoMatch()).group(1)
        result = {"pass": "PASS", "fail": "FAIL"}.get((result_raw or "").lower(), "UNKNOWN")

        bin_names = {b: name.strip() for b, name in _RE_BINNAME.findall(text)}
        binn_m = _RE_BINN.search(text)
        binn = binn_m.group(1) if binn_m else None
        curfbin_m = _RE_CURFBIN.search(text)
        curfbin = curfbin_m.group(1) if curfbin_m else None

        names = _RE_TNAME.findall(text)
        vals = _RE_STRGVAL.findall(text)
        steps: list[StepRecord] = []
        failed_step: str | None = None
        for name, val in zip(names, vals):
            if name == "BINS_IN_THIS_RUN":
                continue
            parts = val.split(";")
            res = parts[0].strip().lower()
            dur = 0.0
            if len(parts) >= 3:
                try:
                    dur = float(parts[2])
                except ValueError:
                    dur = 0.0
            step_res = "PASS" if res == "pass" else "FAIL" if res == "fail" else "UNKNOWN"
            clean = re.sub(r"^\d+", "", name).strip() or name
            steps.append(StepRecord(name=clean, result=step_res, duration_s=dur))
            if step_res == "FAIL" and failed_step is None:
                failed_step = clean

        err_code = None
        err_msg = None
        snippet = None
        if result == "FAIL":
            fail_bin = binn or curfbin
            err_code = fail_bin or "FAIL"
            err_msg = (
                (bin_names.get(binn) if binn else None)
                or (bin_names.get(curfbin) if curfbin else None)
                or failed_step
                or "Unknown failure"
            )
            fail_lines = [f"{s.name}: FAIL" for s in steps if s.result == "FAIL"]
            snippet = "\n".join(
                ["result: fail", f"bin: {fail_bin or 'n/a'} ({err_msg})", *fail_lines[:8]]
            )

        lot_m = _RE_LOTID.search(text)
        begin_m = _RE_BEGINDT.search(text)
        end_m = _RE_ENDDATE.search(text)
        ttime_m = _RE_TTIME.search(text)

        return {
            "result": result,
            "error_code": err_code,
            "error_message": err_msg,
            "steps": steps,
            "snippet": snippet,
            "lot_id": lot_m.group(1).strip() if lot_m else None,
            "begin": begin_m.group(1) if begin_m else None,
            "end": end_m.group(1) if end_m else None,
            "duration": float(ttime_m.group(1)) if ttime_m else 0.0,
        }


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def get_preprocessor() -> Preprocessor:
    return FtrunnerPreprocessor()
