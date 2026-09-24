from __future__ import annotations

import json
import os

from app.config import settings
from app.job_registry import Job
from app.models import BatchMetadata, UnitRecord
from app.orchestrator import _batch_metadata
from app.upload_storage import cleanup_job_workdir


def _record(unit_id: str, **overrides) -> UnitRecord:
    values = {
        "unit_id": unit_id,
        "result": "PASS",
        "product_code": "P1",
        "start_time": "2026-09-20T08:00:00",
        "end_time": "2026-09-20T08:01:00",
        "debuglog_status": "not_applicable",
    }
    values.update(overrides)
    return UnitRecord(**values)


def test_batch_metadata_captures_scope_and_quality_counts():
    records = [
        _record("pass", product_code="P2"),
        _record(
            "fail",
            result="FAIL",
            product_code="P1",
            debuglog_status="not_found",
            start_time="2026-09-20T09:00:00",
            end_time="2026-09-20T09:02:00",
        ),
        _record("unknown", result="UNKNOWN", product_code=None),
    ]

    metadata = _batch_metadata(
        BatchMetadata(display_name="Uploaded folder", source_file_count=12),
        ["run-1", "run-2", "run-3", "run-4"],
        records,
        ["missing-run"],
    )

    assert metadata.display_name == "Uploaded folder"
    assert metadata.source_file_count == 12
    assert metadata.discovered_run_count == 4
    assert metadata.included_run_count == 3
    assert metadata.parse_excluded_count == 1
    assert metadata.incomplete_folder_count == 1
    assert metadata.unknown_result_count == 1
    assert metadata.missing_debuglog_count == 1
    assert metadata.product_codes == ["P1", "P2"]
    assert metadata.observed_start_time == "2026-09-20T08:00:00"
    assert metadata.observed_end_time == "2026-09-20T09:02:00"
    assert metadata.timestamp_timezone == "unspecified"


def test_batch_metadata_reports_mixed_and_unavailable_timezones():
    mixed = _batch_metadata(
        BatchMetadata(),
        ["run-1", "run-2"],
        [
            _record("offset", start_time="2026-09-20T08:00:00Z", end_time=None),
            _record("naive", start_time="2026-09-20T09:00:00", end_time=None),
        ],
        [],
    )
    unavailable = _batch_metadata(
        BatchMetadata(),
        [],
        [],
        [],
    )

    assert mixed.timestamp_timezone == "mixed"
    assert mixed.observed_start_time is None
    assert mixed.observed_end_time is None
    assert mixed.chronology_unavailable_reason == "Mixed timezone styles prevent determining the observed period"
    assert unavailable.observed_start_time is None
    assert unavailable.observed_end_time is None
    assert unavailable.timestamp_timezone == "unavailable"


def test_persisted_batch_metadata_survives_payload_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", True)
    workdir = tmp_path / "job"
    input_dir = workdir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "ftrunnerlog01.txt").write_text("payload", encoding="utf-8")
    job = Job(
        job_id="job-1",
        workdir=str(workdir),
        status="done",
        batch=BatchMetadata(display_name="Folder A", product_codes=["P1"]),
    )
    job.save()

    cleanup_job_workdir(str(workdir))

    assert not input_dir.exists()
    with open(os.path.join(workdir, "job_state.json"), encoding="utf-8") as handle:
        state = json.load(handle)
    assert state["batch"]["display_name"] == "Folder A"
    assert state["batch"]["product_codes"] == ["P1"]
