"""In-memory, ephemeral job registry (no long-term persistence)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .config import settings
from .models import JobProgress, JobState, JobStatus, UnitRecord


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
    # signature -> (root_cause, suggested_solution, analysis_source)
    signature_cache: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    def to_status(self) -> JobStatus:
        return JobStatus(
            job_id=self.job_id,
            status=self.status,
            progress=JobProgress(processed=self.processed, total=self.total),
            message=self.message,
            unit_count=len(self.records),
        )


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, workdir: str) -> Job:
        with self._lock:
            job = Job(job_id=job_id, workdir=workdir)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._evict_expired()
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            self._evict_expired()
            return list(self._jobs.values())

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, j in self._jobs.items() if now - j.created_at > settings.JOB_TTL_S]
        for k in expired:
            self._jobs.pop(k, None)


registry = JobRegistry()
