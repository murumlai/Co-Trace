"""Engineer Analyzer — error-signature dedup + redaction + LLM call.

Passing units never trigger an LLM call. Failed units are grouped by a stable
signature (error_code + normalized error_message); the LLM is called once per
unique signature and the result is cached on the job.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable

from . import llm_client, redaction
from .job_registry import Job
from .models import UnitRecord

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d+")
log = logging.getLogger("cotrace.analyzer")

AnalyzeFailure = Callable[[str | None, str | None, str], tuple[str, str, str]]
AnalysisProgress = Callable[[int, int, str], None]


def _normalize_msg(msg: str | None) -> str:
    if not msg:
        return ""
    text = _NUM.sub("#", msg.lower())
    return _WS.sub(" ", text).strip()


def signature_for(record: UnitRecord) -> str:
    basis = f"{record.error_code or 'FAIL'}|{_normalize_msg(record.error_message)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def build_llm_context(record: UnitRecord) -> tuple[str, str]:
    """Select the best available failure context for the LLM and report its
    source. Prefers the deterministic, bounded DebugLog excerpt, then the
    FTRunner snippet, then the raw error message.

    The DebugLog excerpt is the highest-signal source because it is anchored
    on the actual failure (see ``extract_debug_excerpt``), so routing it into
    the model — rather than the thin FTRunner snippet — is the whole point of
    the deterministic extraction step.
    """
    if record.debug_excerpt:
        return record.debug_excerpt, "debug_excerpt"
    if record.ftrunner_snippet:
        return record.ftrunner_snippet, "ftrunner_snippet"
    return record.error_message or "", "error_message"


def _redacted_context(record: UnitRecord) -> tuple[str, str, str]:
    """Return (redacted_error_message, redacted_context, context_source)."""
    err_msg = redaction.redact(record.error_message)
    raw_context, source = build_llm_context(record)
    # debug_excerpt is stored redacted with keep_serial=True; re-redacting with
    # the default scrubs the serial before anything leaves the process.
    snippet = redaction.redact(raw_context or record.error_message or "")
    return err_msg, snippet, source


def analyze_job(
    job: Job,
    analyze_failure: AnalyzeFailure = llm_client.analyze,
    progress_callback: AnalysisProgress | None = None,
) -> None:
    """Populate root cause / solution for all failed units, using the cache."""
    failed = [rec for rec in job.records if rec.result == "FAIL"]
    total_signatures = len({signature_for(rec) for rec in failed})
    log.info(
        "Analysis started for job %s: %s failed units, %s unique signatures, %s cached signatures.",
        job.job_id[:8],
        len(failed),
        total_signatures,
        len(job.signature_cache),
    )
    if progress_callback:
        progress_callback(0, total_signatures, _analysis_progress_message(0, total_signatures, "starting"))

    completed_signatures: set[str] = set()
    for rec in failed:
        sig = signature_for(rec)
        is_new_signature = sig not in completed_signatures
        if is_new_signature and progress_callback:
            progress_callback(
                len(completed_signatures),
                total_signatures,
                _analysis_progress_message(len(completed_signatures) + 1, total_signatures, "running"),
            )
        _analyze_unit(job, rec, force=False, analyze_failure=analyze_failure)
        if is_new_signature:
            completed_signatures.add(sig)
            if progress_callback:
                progress_callback(
                    len(completed_signatures),
                    total_signatures,
                    _analysis_progress_message(len(completed_signatures), total_signatures, "done"),
                )
    log.info("Analysis finished for job %s: %s cached signatures.", job.job_id[:8], len(job.signature_cache))


def _analysis_progress_message(done: int, total: int, state: str) -> str:
    if total == 0:
        return "No failed units need analysis"
    if state == "starting":
        return f"Preparing failure analysis for {total} signature{'s' if total != 1 else ''}"
    if state == "running":
        return f"Analyzing failure signature {done}/{total}; LLM calls can take a minute"
    return f"Analyzed failure signature {done}/{total}"


def _analyze_unit(
    job: Job,
    rec: UnitRecord,
    force: bool,
    analyze_failure: AnalyzeFailure,
) -> None:
    sig = signature_for(rec)
    rec.signature = sig
    err_msg, snippet, context_source = _redacted_context(rec)
    rec.redacted_snippet = snippet
    rec.analysis_context_source = context_source

    if not force and sig in job.signature_cache:
        root, solution, _src = job.signature_cache[sig]
        rec.root_cause = root
        rec.suggested_solution = solution
        rec.analysis_source = "cached"
        log.debug("Used cached analysis for unit %s (signature %s).", rec.unit_id, sig)
        return

    log.info(
        "Analyzing unit %s with %s context (signature %s, force=%s).",
        rec.unit_id,
        context_source,
        sig,
        force,
    )
    root, solution, source = analyze_failure(rec.error_code, err_msg, snippet)
    job.signature_cache[sig] = (root, solution, source)
    rec.root_cause = root
    rec.suggested_solution = solution
    rec.analysis_source = source
    log.info("Analysis result for unit %s came from %s.", rec.unit_id, source)


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
