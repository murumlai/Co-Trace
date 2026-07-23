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
from collections.abc import Callable
from typing import Any

from . import analyzer as _analyzer_module
from .config import settings
from .contracts import ArtifactWriter, FailureAnalyzer, JobRepository, PayloadCleaner, Preprocessor
from .job_registry import registry
from .preprocessor import (
    FtrunnerPreprocessor,
    find_incomplete_folders,
    get_preprocessor,
    write_product_jsons,
)
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


class _FunctionFailureAnalyzer:
    """Wraps ``analyzer.analyze_job`` as a ``FailureAnalyzer``."""

    def analyze_job(self, job: Any, progress_callback: Callable | None = None) -> None:
        _analyzer_module.analyze_job(job, progress_callback=progress_callback)


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

            incomplete = find_incomplete_folders(input_root)
            job.warnings = [
                f"No ftrunnerlog01.txt or debuglog.txt found in: {rel}" for rel in incomplete
            ]
            if job.warnings:
                log.warning("Job %s completed with %s folder warnings.", job_id[:8], len(job.warnings))
            job.save()
            _raise_if_cancelled(job)

            # One redacted <product_code>.json per product, serving both tabs.
            job.message = "Writing per-product JSON"
            written = self._writer.write(
                records, os.path.join(job.workdir, "preprocessed"), warnings=job.warnings
            )
            log.info("Job %s wrote %s preprocessed files.", job_id[:8], len(written))
            _raise_if_cancelled(job)

            # Engineer analysis only for failed units (grouped by signature).
            job.message = "Analyzing failed units"
            log.info(
                "Job %s analyzing %s failed units.",
                job_id[:8],
                sum(1 for r in records if r.result == "FAIL"),
            )
            self._analyzer.analyze_job(job, progress_callback=_analysis_progress_updater(job))

            job.status = "done"
            job.processed = job.total
            job.message = f"Completed: {len(records)} unit runs"
            job.save()
            self._do_cleanup(job)
            log.info("Job %s finished: %s unit runs.", job_id[:8], len(records))
        except JobCancelled:
            job.status = "cancelled"
            job.message = "Batch stopped by user"
            job.save()
            self._do_cleanup(job)
            log.info("Job %s stopped by user.", job_id[:8])
        except Exception as exc:  # noqa: BLE001 - surface failure to the UI
            job.status = "error"
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
    analyzer=_FunctionFailureAnalyzer(),
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
    def update(processed: int, total: int, message: str) -> None:
        _raise_if_cancelled(job)
        job.processed = processed
        job.total = max(total, 1)
        if settings.LLM_PROVIDER == "copilot_sdk" and total > 0 and processed < total:
            passes = 2 if settings.COPILOT_ENABLE_MINI_ENRICH else 1
            timeout_s = int(settings.COPILOT_TIMEOUT_S * passes)
            message = f"{message} (up to {timeout_s}s per uncached signature)"
        job.message = message
        job.save()

    return update


def _raise_if_cancelled(job: Any) -> None:
    if job.cancel_requested:
        raise JobCancelled()


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
