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

from . import analysis_cache, llm_client, redaction
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
    cache: object | None = None,
) -> None:
    """Populate root cause / solution for all failed units, using the cache.

    ``cache`` may be any object satisfying the ``AnalysisCache`` protocol.
    When ``None`` the module-level ``DiskAnalysisCache`` default is used.
    """
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
                _analysis_progress_message(len(completed_signatures) + 1, total_signatures, "checking"),
            )
        source = _analyze_unit(
            job,
            rec,
            force=False,
            analyze_failure=analyze_failure,
            cache=cache,
            progress_callback=(
                lambda message: progress_callback(
                    len(completed_signatures),
                    total_signatures,
                    message,
                )
                if is_new_signature and progress_callback
                else None
            ),
            progress_index=len(completed_signatures) + 1,
            progress_total=total_signatures,
        )
        if is_new_signature:
            completed_signatures.add(sig)
            if progress_callback:
                progress_callback(
                    len(completed_signatures),
                    total_signatures,
                    _analysis_progress_message(len(completed_signatures), total_signatures, "done", source),
                )
    log.info("Analysis finished for job %s: %s cached signatures.", job.job_id[:8], len(job.signature_cache))


def _analysis_progress_message(done: int, total: int, state: str, source: str | None = None) -> str:
    if total == 0:
        return "No failed units need analysis"
    if state == "starting":
        return f"Preparing failure analysis for {total} signature{'s' if total != 1 else ''}"
    if state == "checking":
        return f"Checking saved analysis for failure signature {done}/{total}"
    if state == "llm":
        return f"Analyzing uncached failure signature {done}/{total}; LLM calls can take a minute"
    if source in ("cached", "local-cache"):
        return f"Loaded saved analysis for failure signature {done}/{total}"
    return f"Analyzed failure signature {done}/{total}"


def _analyze_unit(
    job: Job,
    rec: UnitRecord,
    force: bool,
    analyze_failure: AnalyzeFailure,
    progress_callback: Callable[[str], None] | None = None,
    progress_index: int = 1,
    progress_total: int = 1,
    cache: object | None = None,
) -> str:
    from . import analysis_cache as _ac_module  # avoid circular at import time
    _cache: object = cache if cache is not None else _ac_module._default_cache
    sig = signature_for(rec)
    rec.signature = sig
    err_msg, snippet, context_source = _redacted_context(rec)
    rec.redacted_snippet = snippet
    rec.analysis_context_source = context_source
    cache_key = _cache.make_key(
        error_code=rec.error_code,
        error_message=err_msg,
        context=snippet,
        context_source=context_source,
        signature=sig,
    )
    rec.analysis_cache_key = cache_key

    if not force and sig in job.signature_cache:
        root, solution, _src = job.signature_cache[sig]
        rec.root_cause = root
        rec.suggested_solution = solution
        rec.analysis_source = "local-cache" if _src == "local-cache" else "cached"
        log.debug("Used cached analysis for unit %s (signature %s).", rec.unit_id, sig)
        return rec.analysis_source

    if not force:
        cached_entry = _cache.get(cache_key)
        if cached_entry:
            root = str(cached_entry.get("root_cause") or "No root cause returned.")
            solution = str(cached_entry.get("suggested_solution") or "No solution returned.")
            job.signature_cache[sig] = (root, solution, "local-cache")
            rec.root_cause = root
            rec.suggested_solution = solution
            rec.analysis_source = "local-cache"
            log.info("Used saved analysis cache for unit %s (cache %s).", rec.unit_id, cache_key[:8])
            return rec.analysis_source

    if progress_callback:
        progress_callback(_analysis_progress_message(progress_index, progress_total, "llm"))

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
    _cache.put(
        cache_key,
        root_cause=root,
        suggested_solution=solution,
        source=source,
        metadata={
            "signature": sig,
            "error_code": rec.error_code,
            "error_message": err_msg,
            "context_source": context_source,
            "unit_id": rec.unit_id,
            "product_code": rec.product_code,
            "failing_step": rec.failing_step,
        },
    )
    log.info("Analysis result for unit %s came from %s.", rec.unit_id, source)
    return source


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


# ---------------------------------------------------------------------------
# AnalyzerService — concrete adapter for the FailureAnalyzer contract
# ---------------------------------------------------------------------------

class AnalyzerService:
    """Encapsulates injected cache and LLM provider for the ``FailureAnalyzer``
    protocol, allowing tests to substitute either dependency without importing
    or monkeypatching module globals.

    When ``cache`` is ``None`` the module-level ``DiskAnalysisCache`` default
    is used. When ``analyze_failure`` is ``None`` ``llm_client.analyze`` is
    used (which itself routes to the configured provider).
    """

    def __init__(
        self,
        analyze_failure: AnalyzeFailure | None = None,
        cache: object | None = None,
    ) -> None:
        self._analyze_failure: AnalyzeFailure = analyze_failure or llm_client.analyze
        self._cache = cache  # None ⇒ module default inside analyze_job/_analyze_unit

    def analyze_job(
        self,
        job: Job,
        progress_callback: AnalysisProgress | None = None,
    ) -> None:
        """Implements the ``FailureAnalyzer.analyze_job`` contract."""
        analyze_job(
            job,
            analyze_failure=self._analyze_failure,
            progress_callback=progress_callback,
            cache=self._cache,
        )

    def reanalyze_unit(self, job: Job, unit_id: str) -> UnitRecord | None:
        """Force a fresh per-unit analysis, bypassing the signature cache."""
        for rec in job.records:
            if rec.unit_id == unit_id:
                if rec.result != "FAIL":
                    return rec
                _analyze_unit(
                    job, rec, force=True,
                    analyze_failure=self._analyze_failure,
                    cache=self._cache,
                )
                return rec
        return None
