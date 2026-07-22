"""Job registry with disk-backed persistence and 30-day TTL."""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field

from .config import settings
from .models import JobProgress, JobState, JobStatus, UnitRecord

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
    # signature -> (root_cause, suggested_solution, analysis_source)
    signature_cache: dict[str, tuple[str, str, str]] = field(default_factory=dict)

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
        """Atomically write job state to <workdir>/job_state.json."""
        if not self.workdir:
            return
        state = {
            "job_id": self.job_id,
            "status": self.status,
            "message": self.message,
            "processed": self.processed,
            "total": self.total,
            "created_at": self.created_at,
            "workdir": self.workdir,
            "warnings": self.warnings,
            "records": [r.model_dump() for r in self.records],
            "signature_cache": self.signature_cache,
        }
        path = os.path.join(self.workdir, "job_state.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
            os.replace(tmp, path)
        except OSError:
            log.exception("Failed to persist job state for %s", self.job_id)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, workdir: str) -> Job:
        with self._lock:
            job = Job(job_id=job_id, workdir=workdir)
            self._jobs[job_id] = job
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
        """Scan WORK_DIR for persisted job_state.json files and restore them.
        Jobs older than JOB_TTL_S are deleted from disk. Jobs that were
        'running' when the server died are marked 'error'.
        """
        work_dir = settings.WORK_DIR
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
                    records=[UnitRecord(**r) for r in state.get("records", [])],
                    signature_cache=state.get("signature_cache", {}),
                )
                if job.status == "running":
                    job.status = "error"
                    job.message = "Server restarted during processing — please re-upload"
                    job.save()
                with self._lock:
                    self._jobs[job.job_id] = job
                log.info("Restored job %s (status=%s)", job.job_id, job.status)
            except Exception:  # noqa: BLE001
                log.exception("Failed to restore job from %s", state_path)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, j in self._jobs.items() if now - j.created_at > settings.JOB_TTL_S]
        for k in expired:
            job = self._jobs.pop(k, None)
            if job and job.workdir and os.path.isdir(job.workdir):
                shutil.rmtree(job.workdir, ignore_errors=True)
                log.info("Evicted and deleted job dir: %s", job.workdir)


registry = JobRegistry()
