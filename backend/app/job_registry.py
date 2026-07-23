"""Job registry with disk-backed persistence and 30-day TTL.

Phase 3 (SOLID refactor): file I/O is isolated in ``DiskJobStateStore``.
``Job`` is now a pure state/domain object; ``JobRegistry`` delegates all
disk operations to an injected store so tests can substitute an in-memory
store without touching the filesystem.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .models import JobProgress, JobState, JobStatus, UnitRecord
from .upload_storage import cleanup_job_workdir

log = logging.getLogger(__name__)


@dataclass
class Job:
    job_id: str
    status: JobState = "pending"
    message: str = ""
    processed: int = 0
    total: int = 0
    created_at: float = field(default_factory=time.time)
    records: list[UnitRecord] = field(default_factory=list)
    workdir: str = ""
    warnings: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    # signature -> (root_cause, suggested_solution, analysis_source)
    signature_cache: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    # Injected by the registry so save() does not hard-code disk paths.
    # init=False keeps it out of __init__; compare=False / repr=False keep it
    # invisible to equality checks and string representations.
    _state_store: Any = field(default=None, init=False, repr=False, compare=False)

    def to_status(self) -> JobStatus:
        return JobStatus(
            job_id=self.job_id,
            status=self.status,
            progress=JobProgress(processed=self.processed, total=self.total),
            message=self.message,
            unit_count=len(self.records),
            warnings=self.warnings,
        )

    def save(self) -> None:
        """Persist current job state via the injected store.

        Falls back to inline file I/O when no store is set (backward
        compatibility for Job objects created outside the registry).
        """
        if self._state_store is not None:
            self._state_store.save(self)
            return
        # Inline fallback — keeps ad-hoc Job() construction working.
        if not self.workdir:
            return
        _inline_save(self)


def _inline_save(job: Job) -> None:
    """File-I/O implementation shared by the inline fallback and DiskJobStateStore."""
    state = {
        "job_id": job.job_id,
        "status": job.status,
        "message": job.message,
        "processed": job.processed,
        "total": job.total,
        "created_at": job.created_at,
        "workdir": job.workdir,
        "warnings": job.warnings,
        "cancel_requested": job.cancel_requested,
        "records": [r.model_dump() for r in job.records],
        "signature_cache": job.signature_cache,
    }
    path = os.path.join(job.workdir, "job_state.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except OSError:
        log.exception("Failed to persist job state for %s", job.job_id)


# ---------------------------------------------------------------------------
# DiskJobStateStore — concrete adapter for the JobStateStore contract
# ---------------------------------------------------------------------------

class DiskJobStateStore:
    """Wraps all disk I/O for job state: save, load, and delete.

    Extracted from ``Job.save()`` and ``JobRegistry.load_from_disk()``
    so that filesystem operations can be replaced in tests or swapped for
    an alternative store (Phase 7 composition root).
    """

    def save(self, job: Job) -> None:
        """Atomically write job state to ``<workdir>/job_state.json``."""
        if not job.workdir:
            return
        _inline_save(job)

    def load_all(self, work_dir: str):
        """Scan *work_dir* and yield restored ``Job`` objects.

        Expired entries (older than ``JOB_TTL_S``) are deleted from disk and
        not yielded. Jobs that were ``"running"`` when the server died are
        promoted to ``"error"`` and re-persisted before being yielded.
        """
        if not os.path.isdir(work_dir):
            return
        now = time.time()
        for entry in os.scandir(work_dir):
            if not entry.is_dir():
                continue
            state_path = os.path.join(entry.path, "job_state.json")
            if not os.path.exists(state_path):
                continue
            try:
                with open(state_path, encoding="utf-8") as fh:
                    state = json.load(fh)
                created_at = float(state.get("created_at", now))
                if now - created_at > settings.JOB_TTL_S:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    log.info("Deleted expired job dir: %s", entry.path)
                    continue
                job = Job(
                    job_id=state["job_id"],
                    status=state.get("status", "error"),
                    message=state.get("message", ""),
                    processed=state.get("processed", 0),
                    total=state.get("total", 0),
                    created_at=created_at,
                    workdir=state.get("workdir", entry.path),
                    warnings=state.get("warnings", []),
                    cancel_requested=state.get("cancel_requested", False),
                    records=[UnitRecord(**r) for r in state.get("records", [])],
                    signature_cache=state.get("signature_cache", {}),
                )
                if job.status == "running":
                    job.status = "error"
                    job.message = "Server restarted during processing — please re-upload"
                    self.save(job)
                yield job
            except Exception:  # noqa: BLE001
                log.exception("Failed to restore job from %s", state_path)

    def delete(self, job: Job) -> None:
        """Remove the entire job workdir (used for TTL eviction)."""
        if job.workdir and os.path.isdir(job.workdir):
            shutil.rmtree(job.workdir, ignore_errors=True)
            log.info("Evicted and deleted job dir: %s", job.workdir)


class JobRegistry:
    def __init__(self, store: DiskJobStateStore | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._store: DiskJobStateStore = store if store is not None else DiskJobStateStore()

    def create(self, job_id: str, workdir: str) -> Job:
        with self._lock:
            job = Job(job_id=job_id, workdir=workdir)
            job._state_store = self._store
            self._jobs[job_id] = job
            job.save()
            return job

    def request_cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {"done", "error", "cancelled"}:
                return job
            job.cancel_requested = True
            job.message = "Stopping batch after the current step"
            job.save()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._evict_expired()
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            self._evict_expired()
            return list(self._jobs.values())

    def load_from_disk(self) -> None:
        """Scan WORK_DIR for persisted job_state.json files and restore them."""
        for job in self._store.load_all(settings.WORK_DIR):
            # Attach the store so subsequent job.save() calls go through it.
            job._state_store = self._store
            # Cleanup payload/artifact files left over from done/error jobs.
            if job.status in {"done", "error"}:
                removed = cleanup_job_workdir(job.workdir)
                if removed:
                    log.info("Cleaned restored job %s (%s items removed)", job.job_id, len(removed))
            with self._lock:
                self._jobs[job.job_id] = job
            log.info("Restored job %s (status=%s)", job.job_id, job.status)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, j in self._jobs.items() if now - j.created_at > settings.JOB_TTL_S]
        for k in expired:
            job = self._jobs.pop(k, None)
            if job:
                self._store.delete(job)
                log.info("Evicted and deleted job dir: %s", job.workdir)


registry = JobRegistry()
