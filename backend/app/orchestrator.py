"""Job Orchestrator — runs the preprocessing pipeline as a background task."""
from __future__ import annotations

import logging
import os

from . import analyzer
from .config import settings
from .job_registry import registry
from .preprocessor import find_incomplete_folders, get_preprocessor, write_product_jsons
from .upload_storage import cleanup_job_workdir, get_job_input_root

log = logging.getLogger("cotrace.orchestrator")


def run_job(job_id: str) -> None:
    """Executed in a background thread/task. Updates progress as it goes."""
    job = registry.get(job_id)
    if job is None:
        log.warning("Job %s was not found.", job_id[:8])
        return

    log.info("Job %s started.", job_id[:8])
    job.status = "running"
    job.message = "Scanning uploaded files"
    job.save()

    try:
        pre = get_preprocessor()
        input_root = get_job_input_root(job.workdir)

        # First pass to establish a total for progress reporting.
        run_folders = list(pre.iter_run_folders(input_root))
        job.total = max(len(run_folders), 1)
        log.info("Job %s found %s run folders.", job_id[:8], len(run_folders))

        records = []
        for i, folder in enumerate(run_folders, start=1):
            rec = pre.process_run_folder(folder, input_root)
            if rec is not None:
                records.append(rec)
            log.debug("Job %s processed run %s/%s: %s.", job_id[:8], i, job.total, folder)
            job.processed = i
            job.message = f"Processed {i}/{job.total} runs"

        job.records = records

        incomplete = find_incomplete_folders(input_root)
        job.warnings = [
            f"No ftrunnerlog01.txt or debuglog.txt found in: {rel}" for rel in incomplete
        ]
        if job.warnings:
            log.warning("Job %s completed with %s folder warnings.", job_id[:8], len(job.warnings))
        job.save()

        # One redacted <product_code>.json per product, serving both tabs.
        job.message = "Writing per-product JSON"
        written = write_product_jsons(
            records, os.path.join(job.workdir, "preprocessed"), warnings=job.warnings
        )
        log.info("Job %s wrote %s preprocessed files.", job_id[:8], len(written))

        # Engineer analysis only for failed units (grouped by signature).
        job.message = "Analyzing failed units"
        log.info("Job %s analyzing %s failed units.", job_id[:8], sum(1 for r in records if r.result == "FAIL"))
        analyzer.analyze_job(job, progress_callback=_analysis_progress_updater(job))

        job.status = "done"
        job.processed = job.total
        job.message = f"Completed: {len(records)} unit runs"
        job.save()
        _cleanup_job_workdir(job)
        log.info("Job %s finished: %s unit runs.", job_id[:8], len(records))
    except Exception as exc:  # noqa: BLE001 - surface failure to the UI
        job.status = "error"
        job.message = f"Processing failed: {type(exc).__name__}: {exc}"
        job.save()
        _cleanup_job_workdir(job)
        log.exception("Job %s failed.", job_id[:8])


def _analysis_progress_updater(job):
    def update(processed: int, total: int, message: str) -> None:
        job.processed = processed
        job.total = max(total, 1)
        if settings.LLM_PROVIDER == "copilot_sdk" and total > 0 and processed < total:
            passes = 2 if settings.COPILOT_ENABLE_MINI_ENRICH else 1
            timeout_s = int(settings.COPILOT_TIMEOUT_S * passes)
            message = f"{message} (up to {timeout_s}s per uncached signature)"
        job.message = message
        job.save()

    return update


def _cleanup_job_workdir(job) -> None:
    removed = cleanup_job_workdir(job.workdir)
    if removed:
        log.info("Job %s cleaned local payloads: %s item%s removed.", job.job_id[:8], len(removed), "" if len(removed) == 1 else "s")
