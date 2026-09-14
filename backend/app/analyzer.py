"""Engineer Analyzer — error-signature dedup + redaction + LLM call.

Passing units never trigger an LLM call. Failed units are grouped by a stable
signature (error_code + normalized error_message); the LLM is called once per
unique signature and the result is cached on the job.
"""
from __future__ import annotations

import inspect
import logging
from collections.abc import Callable

from . import analysis_cache, llm_client, redaction
from .job_registry import Job
from .knowledge.acronym_glossary import AcronymGlossaryContext
from .knowledge.models import KnowledgeContext
from .models import AnalysisResult, LlmAnalysisResult, UnitRecord
from .record_views import _normalize_msg, signature_for
log = logging.getLogger("cotrace.analyzer")

AnalysisReturn = tuple[str, str, str] | LlmAnalysisResult
AnalyzeFailure = Callable[..., AnalysisReturn]
AnalysisProgress = Callable[[int, int, str, str], None]


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


def _insufficient_root_cause(error_code: str | None, error_message: str | None) -> str:
    code = (error_code or "UNKNOWN").strip() or "UNKNOWN"
    message = (error_message or "").strip()
    if message:
        return (
            f"The supplied evidence shows failure code '{code}' with message "
            f"'{message[:160]}', but it does not contain enough product-specific "
            "or log evidence to identify a single root cause."
        )
    return (
        f"The supplied evidence shows failure code '{code}', but it does not "
        "contain enough product-specific or log evidence to identify a single root cause."
    )


def _insufficient_solution() -> str:
    return (
        "Review the failing step's full DebugLog/FTRunner context, verify DUT seating, "
        "fixture connections, and station calibration/configuration, then re-run or "
        "reanalyze with more failure evidence."
    )


def analyze_job(
    job: Job,
    analyze_failure: AnalyzeFailure = llm_client.analyze_with_metrics,
    progress_callback: AnalysisProgress | None = None,
    cache: object | None = None,
    knowledge_retriever: object | None = None,
    acronym_glossary: object | None = None,
    playbook_store: object | None = None,
) -> None:
    """Populate root cause / solution for all failed units, using the cache.

    ``cache`` may be any object satisfying the ``AnalysisCache`` protocol.
    When ``None`` the module-level ``DiskAnalysisCache`` default is used.
    ``knowledge_retriever`` (optional) supplies curated product context; when
    ``None`` product-aware diagnosis is skipped. ``acronym_glossary`` (optional)
    supplies authoritative acronym expansions and records unknown acronyms as
    pending review; when ``None`` glossary injection is skipped.
    """
    failed = [rec for rec in job.records if rec.result == "FAIL"]
    force_refresh = bool(getattr(job, "force_refresh", False))
    if force_refresh and job.signature_cache:
        job.signature_cache.clear()
    total_signatures = len({signature_for(rec) for rec in failed})
    log.info(
        "Analysis started for job %s: %s failed units, %s unique signatures, %s cached signatures.",
        job.job_id[:8],
        len(failed),
        total_signatures,
        len(job.signature_cache),
    )
    if progress_callback:
        progress_callback(
            0,
            total_signatures,
            _analysis_progress_message(0, total_signatures, "starting"),
            "analysis",
        )

    completed_signatures: set[str] = set()
    for rec in failed:
        sig = signature_for(rec)
        is_new_signature = sig not in completed_signatures
        if is_new_signature and progress_callback:
            progress_callback(
                len(completed_signatures),
                total_signatures,
                _analysis_progress_message(len(completed_signatures) + 1, total_signatures, "checking"),
                "checking_cache",
            )
        source = _analyze_unit(
            job,
            rec,
            force=force_refresh,
            analyze_failure=analyze_failure,
            cache=cache,
            knowledge_retriever=knowledge_retriever,
            acronym_glossary=acronym_glossary,
            playbook_store=playbook_store,
            progress_callback=(
                lambda message, stage: progress_callback(
                    len(completed_signatures),
                    total_signatures,
                    message,
                    stage,
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
                    "playbook" if source == "playbook" else (
                        "loaded_cache" if source in ("cached", "local-cache") else "analyzing"
                    ),
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
        return f"Analyzing uncached failure signature {done}/{total}"
    if source in ("cached", "local-cache"):
        return f"Loaded saved analysis for failure signature {done}/{total}"
    if source == "playbook":
        return f"Matched known failure for signature {done}/{total}"
    return f"Analyzed failure signature {done}/{total}"


def _analyze_unit(
    job: Job,
    rec: UnitRecord,
    force: bool,
    analyze_failure: AnalyzeFailure,
    reuse_signature_cache: bool = True,
    progress_callback: Callable[[str, str], None] | None = None,
    progress_index: int = 1,
    progress_total: int = 1,
    cache: object | None = None,
    knowledge_retriever: object | None = None,
    acronym_glossary: object | None = None,
    playbook_store: object | None = None,
) -> str:
    from . import analysis_cache as _ac_module  # avoid circular at import time
    _cache: object = cache if cache is not None else _ac_module._default_cache
    sig = signature_for(rec)
    rec.signature = sig
    err_msg, snippet, context_source = _redacted_context(rec)
    rec.redacted_snippet = snippet
    rec.analysis_context_source = context_source

    playbook = _find_reviewed_playbook(playbook_store, sig, rec.product_code)
    if playbook is not None:
        existing = job.signature_cache.get(sig)
        cached_analysis = _coerce_cached_analysis(existing) if existing is not None else None
        if not cached_analysis or cached_analysis.playbook_id != playbook.playbook_id:
            cached_analysis = AnalysisResult(
                root_cause=playbook.root_cause or _insufficient_root_cause(rec.error_code, err_msg),
                suggested_solution=playbook.corrective_action or _insufficient_solution(),
                source="playbook",
                playbook_id=playbook.playbook_id,
            )
        job.signature_cache[sig] = cached_analysis
        rec.analysis_cache_key = None
        _apply_analysis_to_record(rec, cached_analysis)
        job.llm_metrics.record_playbook_hit()
        return "playbook"

    stale_analysis = job.signature_cache.get(sig)
    if stale_analysis is not None and _coerce_cached_analysis(stale_analysis).source == "playbook":
        job.signature_cache.pop(sig, None)

    knowledge = _retrieve_knowledge(rec, knowledge_retriever)
    glossary = _resolve_glossary(rec, acronym_glossary, snippet)
    cache_key = _cache.make_key(
        error_code=rec.error_code,
        error_message=err_msg,
        context=snippet,
        context_source=context_source,
        signature=sig,
        product_code=rec.product_code,
        op_id=rec.op_id,
        failing_step=rec.failing_step,
        knowledge_hash=knowledge.knowledge_hash if knowledge else None,
        knowledge_sections=",".join(rec.knowledge_section_ids),
        knowledge_categories=",".join(rec.knowledge_categories),
        acronym_glossary_hash=glossary.glossary_hash if glossary else None,
    )
    rec.analysis_cache_key = cache_key

    if reuse_signature_cache and sig in job.signature_cache:
        cached_analysis = _coerce_cached_analysis(job.signature_cache[sig])
        root, solution = _apply_exact_knowledge_fallback(
            rec,
            knowledge,
            cached_analysis.root_cause,
            cached_analysis.suggested_solution,
        )
        cached_analysis = cached_analysis.model_copy(
            update={"root_cause": root, "suggested_solution": solution}
        )
        job.signature_cache[sig] = cached_analysis
        display_source = "local-cache" if cached_analysis.source == "local-cache" else "cached"
        _apply_analysis_to_record(rec, cached_analysis, source=display_source)
        job.llm_metrics.record_cache_hit(rec.analysis_source)
        log.debug("Used cached analysis for unit %s (signature %s).", rec.unit_id, sig)
        return rec.analysis_source

    if not force:
        cached_entry = _cache.get(cache_key)
        if cached_entry:
            root = str(cached_entry.get("root_cause") or "").strip() or _insufficient_root_cause(rec.error_code, err_msg)
            solution = str(cached_entry.get("suggested_solution") or "").strip() or _insufficient_solution()
            root, solution = _apply_exact_knowledge_fallback(rec, knowledge, root, solution)
            cached_analysis = AnalysisResult(
                root_cause=root,
                suggested_solution=solution,
                source="local-cache",
                confidence=_cache_confidence(cached_entry.get("confidence")),
                root_cause_category=_cache_text(cached_entry.get("root_cause_category")),
                evidence_summary=_cache_text(cached_entry.get("evidence_summary")),
                next_debug_action=_cache_text(cached_entry.get("next_debug_action")),
                likely_owner=_cache_text(cached_entry.get("likely_owner")),
                safety_or_escape_risk=_cache_text(cached_entry.get("safety_or_escape_risk")),
                needs_more_evidence=(
                    cached_entry.get("needs_more_evidence")
                    if isinstance(cached_entry.get("needs_more_evidence"), bool)
                    else None
                ),
            )
            job.signature_cache[sig] = cached_analysis
            _apply_analysis_to_record(rec, cached_analysis)
            job.llm_metrics.record_cache_hit(rec.analysis_source)
            log.info("Used saved analysis cache for unit %s (cache %s).", rec.unit_id, cache_key[:8])
            return rec.analysis_source

    if progress_callback:
        progress_callback(
            _analysis_progress_message(progress_index, progress_total, "llm"),
            "analyzing",
        )

    _record_glossary_unknowns(rec, glossary, acronym_glossary)
    log.info(
        "Analyzing unit %s with %s context (signature %s, force=%s).",
        rec.unit_id,
        context_source,
        sig,
        force,
    )
    knowledge_prompt = _compose_knowledge_prompt(knowledge, glossary)
    analysis_result = _coerce_analysis_result(
        _call_analyze(analyze_failure, rec.error_code, err_msg, snippet, knowledge_prompt)
    )
    root, solution, source = analysis_result.as_tuple()
    root, solution = _apply_exact_knowledge_fallback(rec, knowledge, root, solution)
    job.llm_metrics.merge(analysis_result.metrics)
    cached_analysis = analysis_result.without_metrics().model_copy(
        update={"root_cause": root, "suggested_solution": solution}
    )
    job.signature_cache[sig] = cached_analysis
    _apply_analysis_to_record(rec, cached_analysis)
    _cache.put(
        cache_key,
        root_cause=root,
        suggested_solution=solution,
        source=source,
        confidence=cached_analysis.confidence,
        root_cause_category=cached_analysis.root_cause_category,
        evidence_summary=cached_analysis.evidence_summary,
        next_debug_action=cached_analysis.next_debug_action,
        likely_owner=cached_analysis.likely_owner,
        safety_or_escape_risk=cached_analysis.safety_or_escape_risk,
        needs_more_evidence=cached_analysis.needs_more_evidence,
        metadata={
            "created_by": getattr(job, "owner_id", ""),
            "created_by_login": getattr(job, "owner_login", ""),
            "created_by_role": getattr(job, "owner_role", "user"),
            "protected": getattr(job, "owner_role", "user") == "admin",
            "signature": sig,
            "error_code": rec.error_code,
            "error_message": err_msg,
            "context_source": context_source,
            "unit_id": rec.unit_id,
            "product_code": rec.product_code,
            "failing_step": rec.failing_step,
            "op_id": rec.op_id,
            "knowledge_hash": rec.knowledge_hash,
            "knowledge_match_status": rec.knowledge_match_status,
            "knowledge_section_ids": ",".join(rec.knowledge_section_ids),
            "knowledge_categories": ",".join(rec.knowledge_categories),
            "acronym_glossary_hash": rec.acronym_glossary_hash,
            "acronyms_used": ",".join(rec.acronyms_used),
            "unknown_acronyms": ",".join(rec.unknown_acronyms),
        },
    )
    log.info("Analysis result for unit %s came from %s.", rec.unit_id, source)
    return source


def _retrieve_knowledge(
    rec: UnitRecord, knowledge_retriever: object | None
) -> KnowledgeContext | None:
    """Retrieve curated product context and persist its metadata on ``rec``."""
    if knowledge_retriever is None:
        return None
    try:
        knowledge = knowledge_retriever.retrieve(rec)
    except Exception:  # noqa: BLE001 - knowledge retrieval must never break analysis
        log.exception("Product-knowledge retrieval failed for unit %s.", rec.unit_id)
        return None
    rec.knowledge_used = bool(knowledge.matched)
    rec.knowledge_hash = knowledge.knowledge_hash or None
    rec.knowledge_match_status = knowledge.match_status
    rec.knowledge_section_ids = list(knowledge.matched_section_ids)
    rec.knowledge_categories = list(knowledge.matched_categories)
    return knowledge


def _resolve_glossary(
    rec: UnitRecord, acronym_glossary: object | None, context_text: str
) -> AcronymGlossaryContext | None:
    """Resolve approved acronym expansions and persist metadata on ``rec``.

    Read-only: the pending-review queue is written separately, only on a cache
    miss (see ``_record_glossary_unknowns``).
    """
    if acronym_glossary is None:
        return None
    try:
        glossary = acronym_glossary.glossary_for(rec, context_text)
    except Exception:  # noqa: BLE001 - glossary lookup must never break analysis
        log.exception("Acronym glossary lookup failed for unit %s.", rec.unit_id)
        return None
    rec.acronyms_used = list(glossary.used_acronyms)
    rec.unknown_acronyms = list(glossary.unknown_acronyms)
    rec.acronym_glossary_hash = glossary.glossary_hash or None
    return glossary


def _record_glossary_unknowns(
    rec: UnitRecord, glossary: AcronymGlossaryContext | None, acronym_glossary: object | None
) -> None:
    """Persist observed-but-undefined acronyms as pending review (cache-miss only)."""
    if glossary is None or acronym_glossary is None:
        return
    try:
        acronym_glossary.record_unknowns(rec, glossary)
    except Exception:  # noqa: BLE001 - recording must never break analysis
        log.exception("Recording unknown acronyms failed for unit %s.", rec.unit_id)


def _compose_knowledge_prompt(
    knowledge: KnowledgeContext | None, glossary: AcronymGlossaryContext | None
) -> str | None:
    """Combine trusted acronym expansions, product knowledge, and the unknown
    block into one trusted-context payload. Works even when no product knowledge
    matched, so the glossary is still injected."""
    parts: list[str] = []
    if glossary is not None and glossary.trusted_text:
        parts.append(glossary.trusted_text)
    if knowledge is not None and knowledge.context_text:
        parts.append(knowledge.context_text)
    if glossary is not None and glossary.unknown_text:
        parts.append(glossary.unknown_text)
    return "\n\n".join(parts) if parts else None


def _call_analyze(
    analyze_failure: AnalyzeFailure,
    error_code: str | None,
    error_message: str | None,
    snippet: str,
    knowledge_context: str | None,
) -> AnalysisReturn:
    """Call ``analyze_failure``, passing curated product context only to
    callables that accept it. Legacy 3-argument stubs are called unchanged."""
    if knowledge_context and _accepts_knowledge_arg(analyze_failure):
        return analyze_failure(error_code, error_message, snippet, knowledge_context)
    return analyze_failure(error_code, error_message, snippet)


def _accepts_knowledge_arg(fn: AnalyzeFailure) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    positional = 0
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            return True
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional += 1
    return positional >= 4


def _coerce_analysis_result(result: AnalysisReturn) -> LlmAnalysisResult:
    if isinstance(result, LlmAnalysisResult):
        return result
    root, solution, source = result
    return LlmAnalysisResult(root_cause=root, suggested_solution=solution, source=source)


def _coerce_cached_analysis(result: object) -> AnalysisResult:
    if isinstance(result, AnalysisResult):
        return result
    if isinstance(result, dict):
        return AnalysisResult(**result)
    root, solution, source = result
    return AnalysisResult(root_cause=root, suggested_solution=solution, source=source)


def _apply_analysis_to_record(
    record: UnitRecord,
    analysis: AnalysisResult,
    *,
    source: str | None = None,
) -> None:
    record.root_cause = analysis.root_cause
    record.suggested_solution = analysis.suggested_solution
    record.analysis_source = source or analysis.source
    record.playbook_id = analysis.playbook_id
    record.confidence = analysis.confidence
    record.root_cause_category = analysis.root_cause_category
    record.evidence_summary = analysis.evidence_summary
    record.next_debug_action = analysis.next_debug_action
    record.likely_owner = analysis.likely_owner
    record.safety_or_escape_risk = analysis.safety_or_escape_risk
    record.needs_more_evidence = analysis.needs_more_evidence


def _cache_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cache_confidence(value: object) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, confidence))


def _find_reviewed_playbook(
    store: object | None,
    signature: str,
    product_code: str | None,
):
    if store is None:
        return None
    try:
        return store.find_reviewed(signature=signature, product_code=product_code)
    except Exception:  # noqa: BLE001 - playbook lookup must not block diagnosis
        log.exception("Playbook lookup failed for signature %s.", signature)
        return None


def _apply_exact_knowledge_fallback(
    rec: UnitRecord,
    knowledge: KnowledgeContext | None,
    root: str,
    solution: str,
) -> tuple[str, str]:
    if not knowledge or not knowledge.matched:
        return root, solution
    if not _analysis_needs_knowledge_fallback(rec, root, solution):
        return root, solution
    known_failure = _best_exact_known_failure(rec, knowledge)
    if known_failure is None:
        return root, solution
    match, failure = known_failure
    symptom = failure.log_signature or failure.symptom or failure.failing_step or match.heading or "known failure"
    action = failure.corrective_action or _rfc_notes(failure)
    if not action:
        return root, solution
    rooted = failure.root_cause or (
        f"Product knowledge has an exact {match.category} match for {rec.product_code or 'this product'}: "
        f"{symptom}."
    )
    return rooted, action


def _analysis_needs_knowledge_fallback(rec: UnitRecord, root: str, solution: str) -> bool:
    root_norm = _normalize_msg(root)
    solution_norm = _normalize_msg(solution)
    return (
        "does not contain enough product-specific" in root_norm
        or "insufficient" in root_norm
        or root_norm.startswith("offline heuristic:")
        or solution_norm in ("see root cause above.", "see root cause above")
        or solution_norm == _normalize_msg(_insufficient_solution())
        or "copilot error:" in solution_norm
    )


def _best_exact_known_failure(rec: UnitRecord, knowledge: KnowledgeContext):
    query_parts = [rec.failing_step or "", rec.error_message or "", rec.error_code or ""]
    query = _normalize_msg(" ".join(query_parts))
    for match in knowledge.matches:
        for failure in match.known_failures:
            fields = [
                failure.log_signature,
                failure.symptom,
                failure.failing_step,
                *(ref.error_message_or_finding for ref in failure.rfc_references),
                *(ref.failed_test_name for ref in failure.rfc_references),
            ]
            if any(_field_matches_query(field, query) for field in fields):
                return match, failure
    return None


def _field_matches_query(field: str | None, query: str) -> bool:
    field_norm = _normalize_msg(field)
    return bool(field_norm and (field_norm in query or query in field_norm))


def _rfc_notes(failure) -> str:
    return "; ".join(ref.notes for ref in failure.rfc_references if ref.notes)


def reanalyze_unit(
    job: Job,
    unit_id: str,
    analyze_failure: AnalyzeFailure = llm_client.analyze_with_metrics,
    knowledge_retriever: object | None = None,
    acronym_glossary: object | None = None,
    playbook_store: object | None = None,
) -> UnitRecord | None:
    """Force a fresh per-unit LLM call, bypassing the signature cache."""
    for rec in job.records:
        if rec.unit_id == unit_id:
            if rec.result != "FAIL":
                return rec
            _analyze_unit(
                job, rec, force=True,
                reuse_signature_cache=False,
                analyze_failure=analyze_failure,
                knowledge_retriever=knowledge_retriever,
                acronym_glossary=acronym_glossary,
                playbook_store=playbook_store,
            )
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
        knowledge_retriever: object | None = None,
        acronym_glossary: object | None = None,
        playbook_store: object | None = None,
    ) -> None:
        self._analyze_failure: AnalyzeFailure = analyze_failure or llm_client.analyze_with_metrics
        self._cache = cache  # None ⇒ module default inside analyze_job/_analyze_unit
        self._knowledge_retriever = knowledge_retriever
        self._acronym_glossary = acronym_glossary
        self._playbook_store = playbook_store

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
            knowledge_retriever=self._knowledge_retriever,
            acronym_glossary=self._acronym_glossary,
            playbook_store=self._playbook_store,
        )

    def reanalyze_unit(self, job: Job, unit_id: str) -> UnitRecord | None:
        """Force a fresh per-unit analysis, bypassing the signature cache."""
        for rec in job.records:
            if rec.unit_id == unit_id:
                if rec.result != "FAIL":
                    return rec
                _analyze_unit(
                    job, rec, force=True,
                    reuse_signature_cache=False,
                    analyze_failure=self._analyze_failure,
                    cache=self._cache,
                    knowledge_retriever=self._knowledge_retriever,
                    acronym_glossary=self._acronym_glossary,
                    playbook_store=self._playbook_store,
                )
                return rec
        return None
