"""Job Orchestrator — runs the preprocessing pipeline as a background task."""
from __future__ import annotations

import os

from . import analyzer
from .job_registry import Job, registry
from .preprocessor import get_preprocessor


def run_job(job_id: str) -> None:
    """Executed in a background thread/task. Updates progress as it goes."""
    job = registry.get(job_id)
    if job is None:
        return

    job.status = "running"
    job.message = "Scanning uploaded files"

    try:
        pre = get_preprocessor()

        # First pass to establish a total for progress reporting.
        run_folders = list(_iter_run_folders(job.workdir))
        job.total = max(len(run_folders), 1)

        records = []
        for i, folder in enumerate(run_folders, start=1):
            rec = pre_single(pre, folder, job.workdir)
            if rec is not None:
                records.append(rec)
            job.processed = i
            job.message = f"Processed {i}/{job.total} runs"

        job.records = records

        # Engineer analysis only for failed units (grouped by signature).
        job.message = "Analyzing failed units"
        analyzer.analyze_job(job)

        job.status = "done"
        job.message = f"Completed: {len(records)} unit runs"
    except Exception as exc:  # noqa: BLE001 - surface failure to the UI
        job.status = "error"
        job.message = f"Processing failed: {type(exc).__name__}: {exc}"


def pre_single(pre, folder: str, root: str):
    """Process one run folder through the preprocessor."""
    records = pre.process_folder(folder)
    return records[0] if records else None


def _iter_run_folders(root: str):
    """Mirror of preprocessor's discovery so we can report per-folder progress."""
    from .preprocessor import FtrunnerPreprocessor

    is_ft = FtrunnerPreprocessor._is_ftrunner
    for dirpath, _dirs, files in os.walk(root):
        if any(is_ft(f) for f in files):
            yield dirpath
