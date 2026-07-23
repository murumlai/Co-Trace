"""Safety-net tests: job registry persistence, restore, TTL eviction, and
interrupted-running-to-error promotion. These lock the disk-backed state
behavior before the SOLID refactor separates Job state from storage.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from app.job_registry import Job, JobRegistry
from app.models import UnitRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_file(workdir: str, **overrides) -> str:
    """Write a minimal job_state.json and return the path."""
    job_id = overrides.get("job_id", "testjob001")
    os.makedirs(workdir, exist_ok=True)
    state = {
        "job_id": job_id,
        "status": "done",
        "message": "Completed",
        "processed": 5,
        "total": 5,
        "created_at": time.time(),
        "workdir": workdir,
        "warnings": [],
        "cancel_requested": False,
        "records": [],
        "signature_cache": {},
    }
    state.update(overrides)
    path = os.path.join(workdir, "job_state.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    return path


# ---------------------------------------------------------------------------
# Job.save
# ---------------------------------------------------------------------------

class TestJobSave:
    def test_writes_job_state_json(self, tmp_path):
        workdir = str(tmp_path / "job1")
        os.makedirs(workdir)
        job = Job(job_id="abc123", workdir=workdir, status="running", message="test")
        job.save()
        path = os.path.join(workdir, "job_state.json")
        assert os.path.isfile(path)

    def test_written_state_roundtrips(self, tmp_path):
        workdir = str(tmp_path / "job1")
        os.makedirs(workdir)
        rec = UnitRecord(unit_id="u1", result="PASS", run_folder="run1")
        job = Job(job_id="abc123", workdir=workdir, status="done",
                  message="Completed: 1 unit runs", processed=1, total=1,
                  records=[rec])
        job.save()

        path = os.path.join(workdir, "job_state.json")
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)

        assert state["job_id"] == "abc123"
        assert state["status"] == "done"
        assert state["processed"] == 1
        assert len(state["records"]) == 1
        assert state["records"][0]["unit_id"] == "u1"

    def test_save_skips_when_no_workdir(self):
        """Job with empty workdir must not raise or create files."""
        job = Job(job_id="abc123", workdir="")
        job.save()  # should be a no-op

    def test_save_is_atomic(self, tmp_path):
        """Write must use a temp file + replace so readers never see partial state."""
        workdir = str(tmp_path / "job1")
        os.makedirs(workdir)
        job = Job(job_id="abc123", workdir=workdir)
        job.save()
        # If atomic, no .tmp file should remain
        tmp_file = os.path.join(workdir, "job_state.json.tmp")
        assert not os.path.exists(tmp_file)


# ---------------------------------------------------------------------------
# JobRegistry.load_from_disk
# ---------------------------------------------------------------------------

class TestLoadFromDisk:
    def test_restores_completed_job(self, tmp_path, monkeypatch, isolated_settings):
        job_id = "completed01"
        workdir = str(tmp_path / "work" / job_id)
        _make_state_file(workdir, job_id=job_id, status="done")

        reg = JobRegistry()
        reg.load_from_disk()

        job = reg.get(job_id)
        assert job is not None
        assert job.status == "done"

    def test_restores_error_job(self, tmp_path, monkeypatch, isolated_settings):
        job_id = "errjob01"
        workdir = str(tmp_path / "work" / job_id)
        _make_state_file(workdir, job_id=job_id, status="error",
                         message="Processing failed: something broke")

        reg = JobRegistry()
        reg.load_from_disk()

        job = reg.get(job_id)
        assert job is not None
        assert job.status == "error"

    def test_marks_running_job_as_error(self, tmp_path, monkeypatch, isolated_settings):
        """A job that was 'running' when the server died must be promoted to 'error'."""
        job_id = "running01"
        workdir = str(tmp_path / "work" / job_id)
        _make_state_file(workdir, job_id=job_id, status="running",
                         message="Processed 3/10 runs")

        reg = JobRegistry()
        reg.load_from_disk()

        job = reg.get(job_id)
        assert job is not None
        assert job.status == "error"
        assert "restart" in job.message.lower() or "restarted" in job.message.lower()

    def test_deletes_expired_job_dir(self, tmp_path, monkeypatch, isolated_settings):
        """Jobs older than JOB_TTL_S must be removed from disk."""
        monkeypatch.setattr(isolated_settings, "JOB_TTL_S", 60)  # 1 minute TTL

        job_id = "expired01"
        workdir = str(tmp_path / "work" / job_id)
        old_time = time.time() - 120  # 2 minutes old → expired
        _make_state_file(workdir, job_id=job_id, status="done", created_at=old_time)

        reg = JobRegistry()
        reg.load_from_disk()

        assert not os.path.isdir(workdir)
        assert reg.get(job_id) is None

    def test_skips_directory_without_state_file(self, tmp_path, monkeypatch, isolated_settings):
        empty_dir = tmp_path / "work" / "orphan_dir"
        empty_dir.mkdir(parents=True)

        reg = JobRegistry()
        reg.load_from_disk()  # should not raise

    def test_restores_records(self, tmp_path, monkeypatch, isolated_settings):
        job_id = "withrecs01"
        workdir = str(tmp_path / "work" / job_id)
        records = [{"unit_id": "u1", "result": "PASS", "run_folder": "run1",
                    "steps": [], "source_files": [], "device_class": "unknown",
                    "has_debuglog": False, "duration_s": 0.0}]
        _make_state_file(workdir, job_id=job_id, status="done", records=records)

        reg = JobRegistry()
        reg.load_from_disk()

        job = reg.get(job_id)
        assert job is not None
        assert len(job.records) == 1
        assert job.records[0].unit_id == "u1"


# ---------------------------------------------------------------------------
# JobRegistry in-memory eviction
# ---------------------------------------------------------------------------

class TestEvictExpired:
    def test_evicts_expired_job_on_get(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "JOB_TTL_S", 0)
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", False)

        workdir = str(tmp_path / "evict_job")
        os.makedirs(workdir)

        reg = JobRegistry()
        job = reg.create("evictme", workdir)
        # With TTL=0, the job is immediately expired
        result = reg.get("evictme")
        assert result is None

    def test_non_expired_job_returned(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "JOB_TTL_S", 60 * 60 * 24 * 30)  # 30 days
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", False)

        workdir = str(tmp_path / "fresh_job")
        os.makedirs(workdir)

        reg = JobRegistry()
        reg.create("fresh", workdir)
        assert reg.get("fresh") is not None


# ---------------------------------------------------------------------------
# JobRegistry.request_cancel
# ---------------------------------------------------------------------------

class TestRequestCancel:
    def test_sets_cancel_flag(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", False)

        workdir = str(tmp_path / "cancel_job")
        os.makedirs(workdir)

        reg = JobRegistry()
        job = reg.create("cjob", workdir)
        job.status = "running"
        returned = reg.request_cancel("cjob")

        assert returned is not None
        assert returned.cancel_requested is True

    def test_returns_none_for_unknown_job(self, tmp_path):
        reg = JobRegistry()
        assert reg.request_cancel("nosuchjob") is None

    def test_terminal_job_cancel_is_noop(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", False)

        workdir = str(tmp_path / "done_job")
        os.makedirs(workdir)

        reg = JobRegistry()
        job = reg.create("djob", workdir)
        job.status = "done"
        returned = reg.request_cancel("djob")
        assert returned is not None
        # cancel_requested stays False for already-terminal jobs
        assert returned.cancel_requested is False
