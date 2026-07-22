"""Job Orchestrator — runs the preprocessing pipeline as a background task."""
from __future__ import annotations

import logging
import os

from . import analyzer
from .job_registry import registry
from .preprocessor import find_incomplete_folders, get_preprocessor, write_product_jsons

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

        # First pass to establish a total for progress reporting.
        run_folders = list(pre.iter_run_folders(job.workdir))
        job.total = max(len(run_folders), 1)
        log.info("Job %s found %s run folders.", job_id[:8], len(run_folders))

        records = []
        for i, folder in enumerate(run_folders, start=1):
            rec = pre.process_run_folder(folder, job.workdir)
            if rec is not None:
                records.append(rec)
            log.debug("Job %s processed run %s/%s: %s.", job_id[:8], i, job.total, folder)
            job.processed = i
            job.message = f"Processed {i}/{job.total} runs"

        job.records = records

        incomplete = find_incomplete_folders(job.workdir)
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
        analyzer.analyze_job(job)

        job.status = "done"
        job.message = f"Completed: {len(records)} unit runs"
        job.save()
        log.info("Job %s finished: %s unit runs.", job_id[:8], len(records))
    except Exception as exc:  # noqa: BLE001 - surface failure to the UI
        job.status = "error"
        job.message = f"Processing failed: {type(exc).__name__}: {exc}"
        job.save()
        log.exception("Job %s failed.", job_id[:8])
