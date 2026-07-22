"""Job Orchestrator — runs the preprocessing pipeline as a background task."""
from __future__ import annotations

import os

from . import analyzer
from .config import settings
from .job_registry import registry
from .preprocessor import find_incomplete_folders, get_preprocessor, write_product_jsons


def run_job(job_id: str) -> None:
    """Executed in a background thread/task. Updates progress as it goes."""
    job = registry.get(job_id)
    if job is None:
        return

    job.status = "running"
    job.message = "Scanning uploaded files"
    job.save()

    try:
        pre = get_preprocessor()

        # First pass to establish a total for progress reporting.
        run_folders = list(pre.iter_run_folders(job.workdir))
        job.total = max(len(run_folders), 1)

        records = []
        for i, folder in enumerate(run_folders, start=1):
            rec = pre.process_run_folder(folder, job.workdir)
            if rec is not None:
                records.append(rec)
            job.processed = i
            job.message = f"Processed {i}/{job.total} runs"

        job.records = records

        incomplete = find_incomplete_folders(job.workdir)
        job.warnings = [
            f"No ftrunnerlog01.txt or debuglog.txt found in: {rel}" for rel in incomplete
        ]
        job.save()

        # One redacted <product_code>.json per product, serving both tabs.
        # Written to the stable app-root preprocessed/ folder so the files
        # persist across backend restarts and job eviction.
        job.message = "Writing per-product JSON"
        write_product_jsons(
            records, settings.PREPROCESSED_DIR, warnings=job.warnings
        )

        # Engineer analysis only for failed units (grouped by signature).
        job.message = "Analyzing failed units"
        analyzer.analyze_job(job)

        job.status = "done"
        job.message = f"Completed: {len(records)} unit runs"
        job.save()
    except Exception as exc:  # noqa: BLE001 - surface failure to the UI
        job.status = "error"
        job.message = f"Processing failed: {type(exc).__name__}: {exc}"
        job.save()
