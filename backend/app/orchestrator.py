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
        log.warning("job missing job_id=%s", job_id)
        return

    log.info("job start job_id=%s workdir=%s", job_id, job.workdir)
    job.status = "running"
    job.message = "Scanning uploaded files"
    job.save()

    try:
        pre = get_preprocessor()

        # First pass to establish a total for progress reporting.
        run_folders = list(pre.iter_run_folders(job.workdir))
        job.total = max(len(run_folders), 1)
        log.info("job scan complete job_id=%s run_folder_count=%s", job_id, len(run_folders))

        records = []
        for i, folder in enumerate(run_folders, start=1):
            rec = pre.process_run_folder(folder, job.workdir)
            if rec is not None:
                records.append(rec)
            log.debug("job processed run job_id=%s index=%s total=%s folder=%s", job_id, i, job.total, folder)
            job.processed = i
            job.message = f"Processed {i}/{job.total} runs"

        job.records = records

        incomplete = find_incomplete_folders(job.workdir)
        job.warnings = [
            f"No ftrunnerlog01.txt or debuglog.txt found in: {rel}" for rel in incomplete
        ]
        if job.warnings:
            log.warning("job warnings job_id=%s count=%s", job_id, len(job.warnings))
        job.save()

        # One redacted <product_code>.json per product, serving both tabs.
        job.message = "Writing per-product JSON"
        written = write_product_jsons(
            records, os.path.join(job.workdir, "preprocessed"), warnings=job.warnings
        )
        log.info("job wrote preprocessed json job_id=%s file_count=%s", job_id, len(written))

        # Engineer analysis only for failed units (grouped by signature).
        job.message = "Analyzing failed units"
        log.info("job analysis start job_id=%s fail_count=%s", job_id, sum(1 for r in records if r.result == "FAIL"))
        analyzer.analyze_job(job)

        job.status = "done"
        job.message = f"Completed: {len(records)} unit runs"
        job.save()
        log.info("job done job_id=%s record_count=%s", job_id, len(records))
    except Exception as exc:  # noqa: BLE001 - surface failure to the UI
        job.status = "error"
        job.message = f"Processing failed: {type(exc).__name__}: {exc}"
        job.save()
        log.exception("job failed job_id=%s", job_id)
