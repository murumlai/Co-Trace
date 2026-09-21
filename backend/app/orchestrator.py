"""Job Orchestrator — runs the preprocessing pipeline as a background task.

Phase 4 (SOLID refactor): the monolithic ``run_job`` function is replaced by
``JobOrchestrator``, an application service that receives its collaborators
(repository, preprocessor, artifact writer, analyzer, cleaner) via
constructor injection. The module-level ``run_job(job_id)`` function remains
as a thin compatibility wrapper so ``main.py`` / ``BackgroundTasks`` callers
need no changes.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from typing import Any

from . import analyzer as _analyzer_module
from .analyzer import AnalyzerService
from .config import settings
from .contracts import ArtifactWriter, FailureAnalyzer, JobRepository, PayloadCleaner, Preprocessor
from .job_registry import registry
from .models import BatchMetadata
from .preprocessor import FtrunnerPreprocessor, get_preprocessor, write_product_jsons
from .upload_storage import cleanup_job_workdir, get_job_input_root

log = logging.getLogger("cotrace.orchestrator")


class JobCancelled(RuntimeError):
    """Raised internally when a user requests a batch stop."""


# ---------------------------------------------------------------------------
# Concrete adapters (thin wrappers around existing module functions)
# ---------------------------------------------------------------------------

class _FunctionArtifactWriter:
    """Wraps ``preprocessor.write_product_jsons`` as an ``ArtifactWriter``."""

    def write(
        self,
        records: list,
        output_dir: str,
        warnings: list[str] | None = None,
    ) -> list[str]:
        return write_product_jsons(records, output_dir, warnings=warnings)


class _FunctionPayloadCleaner:
    """Wraps ``upload_storage.cleanup_job_workdir`` as a ``PayloadCleaner``."""

    def cleanup(self, workdir: str) -> list[str]:
        return cleanup_job_workdir(workdir)


# ---------------------------------------------------------------------------
# JobOrchestrator application service
# ---------------------------------------------------------------------------

class JobOrchestrator:
    """Runs the full preprocessing → artifact writing → analysis pipeline for
    a single job. All I/O dependencies are injected; no direct module imports
    for collaborators at call time.
    """

    def __init__(
        self,
        *,
        repository: JobRepository,
        preprocessor: Preprocessor,
        artifact_writer: ArtifactWriter,
        analyzer: FailureAnalyzer,
        cleaner: PayloadCleaner,
    ) -> None:
        self._repo = repository
        self._pre = preprocessor
        self._writer = artifact_writer
        self._analyzer = analyzer
        self._cleaner = cleaner

    def run_job(self, job_id: str) -> None:
        """Execute the full pipeline for *job_id* in the calling thread."""
        job = self._repo.get(job_id)
        if job is None:
            log.warning("Job %s was not found.", job_id[:8])
            return

        log.info("Job %s started.", job_id[:8])
        job.status = "running"
        job.started_at = job.started_at or time.time()
        job.completed_at = None
        job.stage = "parsing"
        job.message = "Scanning uploaded files"
        job.save()

        try:
            input_root = get_job_input_root(job.workdir)
            _raise_if_cancelled(job)

            # First pass to establish a total for progress reporting.
            run_folders = list(self._pre.iter_run_folders(input_root))
            job.total = max(len(run_folders), 1)
            log.info("Job %s found %s run folders.", job_id[:8], len(run_folders))

            records = []
            for i, folder in enumerate(run_folders, start=1):
                _raise_if_cancelled(job)
                rec = self._pre.process_run_folder(folder, input_root)
                if rec is not None:
                    records.append(rec)
                log.debug("Job %s processed run %s/%s: %s.", job_id[:8], i, job.total, folder)
                job.processed = i
                job.message = f"Processed {i}/{job.total} runs"

            job.records = records
            _raise_if_cancelled(job)

            incomplete = self._pre.find_incomplete_folders(input_root)
            job.warnings = [
                f"No ftrunnerlog01.txt or debuglog.txt found in: {rel}" for rel in incomplete
            ]
            if job.warnings:
                log.warning("Job %s completed with %s folder warnings.", job_id[:8], len(job.warnings))
            job.batch = _batch_metadata(job.batch, run_folders, records, incomplete)
            job.save()
            _raise_if_cancelled(job)

            # One redacted <product_code>.json per product, serving both tabs.
            job.stage = "writing"
            job.message = "Writing per-product JSON"
            written = self._writer.write(
                records, os.path.join(job.workdir, "preprocessed"), warnings=job.warnings
            )
            log.info("Job %s wrote %s preprocessed files.", job_id[:8], len(written))
            _raise_if_cancelled(job)

            # Engineer analysis only for failed units (grouped by signature).
            job.stage = "analysis"
            job.message = "Analyzing failed units"
            log.info(
                "Job %s analyzing %s failed units.",
                job_id[:8],
                sum(1 for r in records if r.result == "FAIL"),
            )
            self._analyzer.analyze_job(job, progress_callback=_analysis_progress_updater(job))

            job.status = "done"
            job.completed_at = time.time()
            job.processed = job.total
            job.stage = "complete"
            job.message = f"Completed: {len(records)} unit runs"
            job.save()
            self._do_cleanup(job)
            log.info("Job %s finished: %s unit runs.", job_id[:8], len(records))
        except JobCancelled:
            job.status = "cancelled"
            job.completed_at = time.time()
            job.stage = "cancelled"
            job.message = "Batch stopped by user"
            job.save()
            self._do_cleanup(job)
            log.info("Job %s stopped by user.", job_id[:8])
        except Exception as exc:  # noqa: BLE001 - surface failure to the UI
            job.status = "error"
            job.completed_at = time.time()
            job.stage = "error"
            job.message = f"Processing failed: {type(exc).__name__}: {exc}"
            job.save()
            self._do_cleanup(job)
            log.exception("Job %s failed.", job_id[:8])

    def _do_cleanup(self, job: Any) -> None:
        removed = self._cleaner.cleanup(job.workdir)
        if removed:
            log.info(
                "Job %s cleaned local payloads: %s item%s removed.",
                job.job_id[:8],
                len(removed),
                "" if len(removed) == 1 else "s",
            )


# ---------------------------------------------------------------------------
# Default singleton orchestrator (wired to concrete implementations)
# ---------------------------------------------------------------------------

_default_orchestrator = JobOrchestrator(
    repository=registry,
    preprocessor=FtrunnerPreprocessor(),
    artifact_writer=_FunctionArtifactWriter(),
    analyzer=AnalyzerService(),       # uses DiskAnalysisCache + llm_client.analyze defaults
    cleaner=_FunctionPayloadCleaner(),
)


# ---------------------------------------------------------------------------
# Compatibility wrapper — keeps main.py / BackgroundTasks callers unchanged
# ---------------------------------------------------------------------------

def run_job(job_id: str) -> None:
    """Compatibility wrapper: delegates to the default ``JobOrchestrator``."""
    _default_orchestrator.run_job(job_id)


# ---------------------------------------------------------------------------
# Private helpers (also used by JobOrchestrator)
# ---------------------------------------------------------------------------

def _analysis_progress_updater(job: Any) -> Callable[[int, int, str], None]:
    def update(processed: int, total: int, message: str, stage: str = "analysis") -> None:
        _raise_if_cancelled(job)
        job.processed = processed
        job.total = max(total, 1)
        job.stage = stage
        if settings.LLM_PROVIDER == "copilot_sdk" and total > 0 and processed < total:
            if settings.COPILOT_ENABLE_MINI_ENRICH:
                calls = f"1-2 Copilot calls; mini skips contexts below {settings.COPILOT_MINI_MIN_CONTEXT_CHARS} chars"
                passes = 2
            else:
                calls = "1 Copilot call"
                passes = 1
            timeout_s = int(settings.COPILOT_TIMEOUT_S * passes)
            message = f"{message} ({calls}; up to {timeout_s}s per uncached signature)"
        job.message = message
        job.save()

    return update


def _raise_if_cancelled(job: Any) -> None:
    if job.cancel_requested:
        raise JobCancelled()


_TIMEZONE_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def _batch_metadata(
    current: BatchMetadata,
    run_folders: list[str],
    records: list[Any],
    incomplete: list[str],
) -> BatchMetadata:
    timestamps = [
        value
        for record in records
        for value in (record.start_time, record.end_time)
        if value
    ]
    timezone_flags = {_TIMEZONE_SUFFIX.search(value) is not None for value in timestamps}
    timezone = "unavailable"
    if timezone_flags == {True}:
        timezone = "offset"
    elif timezone_flags == {False}:
        timezone = "unspecified"
    elif timezone_flags:
        timezone = "mixed"
    missing_debuglog = sum(
        1
        for record in records
        if record.result == "FAIL" and record.debuglog_status not in {"excerpt", "not_applicable"}
    )
    return current.model_copy(update={
        "discovered_run_count": len(run_folders),
        "included_run_count": len(records),
        "parse_excluded_count": max(0, len(run_folders) - len(records)),
        "incomplete_folder_count": len(incomplete),
        "unknown_result_count": sum(1 for record in records if record.result == "UNKNOWN"),
        "missing_debuglog_count": missing_debuglog,
        "product_codes": sorted({record.product_code for record in records if record.product_code}),
        "observed_start_time": min(timestamps) if timestamps else None,
        "observed_end_time": max(timestamps) if timestamps else None,
        "timestamp_timezone": timezone,
    })


# Legacy private helper kept for external callers that imported it directly.
def _cleanup_job_workdir(job: Any) -> None:
    removed = cleanup_job_workdir(job.workdir)
    if removed:
        log.info(
            "Job %s cleaned local payloads: %s item%s removed.",
            job.job_id[:8],
            len(removed),
            "" if len(removed) == 1 else "s",
        )
