"""Engineer Analyzer — error-signature dedup + redaction + LLM call.

Passing units never trigger an LLM call. Failed units are grouped by a stable
signature (error_code + normalized error_message); the LLM is called once per
unique signature and the result is cached on the job.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from . import llm_client, redaction
from .job_registry import Job
from .models import UnitRecord

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d+")

AnalyzeFailure = Callable[[str | None, str | None, str], tuple[str, str, str]]


def _normalize_msg(msg: str | None) -> str:
    if not msg:
        return ""
    text = _NUM.sub("#", msg.lower())
    return _WS.sub(" ", text).strip()


def signature_for(record: UnitRecord) -> str:
    basis = f"{record.error_code or 'FAIL'}|{_normalize_msg(record.error_message)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _redacted_context(record: UnitRecord) -> tuple[str, str]:
    err_msg = redaction.redact(record.error_message)
    snippet = redaction.redact(record.redacted_snippet or record.error_message or "")
    return err_msg, snippet


def analyze_job(job: Job, analyze_failure: AnalyzeFailure = llm_client.analyze) -> None:
    """Populate root cause / solution for all failed units, using the cache."""
    for rec in job.records:
        if rec.result != "FAIL":
            continue
        _analyze_unit(job, rec, force=False, analyze_failure=analyze_failure)


def _analyze_unit(
    job: Job,
    rec: UnitRecord,
    force: bool,
    analyze_failure: AnalyzeFailure,
) -> None:
    sig = signature_for(rec)
    rec.signature = sig
    err_msg, snippet = _redacted_context(rec)
    rec.redacted_snippet = snippet

    if not force and sig in job.signature_cache:
        root, solution, _src = job.signature_cache[sig]
        rec.root_cause = root
        rec.suggested_solution = solution
        rec.analysis_source = "cached"
        return

    root, solution, source = analyze_failure(rec.error_code, err_msg, snippet)
    job.signature_cache[sig] = (root, solution, source)
    rec.root_cause = root
    rec.suggested_solution = solution
    rec.analysis_source = source


def reanalyze_unit(
    job: Job,
    unit_id: str,
    analyze_failure: AnalyzeFailure = llm_client.analyze,
) -> UnitRecord | None:
    """Force a fresh per-unit LLM call, bypassing the signature cache."""
    for rec in job.records:
        if rec.unit_id == unit_id:
            if rec.result != "FAIL":
                return rec
            _analyze_unit(job, rec, force=True, analyze_failure=analyze_failure)
            return rec
    return None
