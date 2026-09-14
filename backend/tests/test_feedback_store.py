from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.feedback_store import DiskFeedbackStore
from app.models import FeedbackEntry, UnitRecord
from tests.auth_helpers import auth_headers


def _entry(*, expires_at: float | None = None) -> FeedbackEntry:
    return FeedbackEntry(
        feedback_id="feedback-1",
        job_id="job-1",
        owner_id="42",
        owner_login="octocat",
        unit_id="unit-1",
        action="helpful",
        created_at="2026-09-14T10:00:00+00:00",
        expires_at=expires_at or time.time() + 3600,
    )


def test_feedback_survives_store_reload(tmp_path) -> None:
    path = str(tmp_path / "feedback.json")
    DiskFeedbackStore(path).add(_entry())

    entries = DiskFeedbackStore(path).list_for_job("job-1", "42")

    assert len(entries) == 1
    assert entries[0].action == "helpful"


def test_expired_feedback_is_pruned(tmp_path) -> None:
    store = DiskFeedbackStore(str(tmp_path / "feedback.json"))
    store.add(_entry(expires_at=time.time() - 1))

    assert store.list_for_job("job-1", "42") == []


@pytest.fixture()
def feedback_client(tmp_path):
    from app.dependencies import get_feedback_store, get_registry
    from app.job_registry import JobRegistry
    from app.main import app

    registry = JobRegistry()
    workdir = tmp_path / "owned-job"
    workdir.mkdir()
    job = registry.create("owned-job", str(workdir), owner_id="42", owner_login="octocat")
    job.records = [
        UnitRecord(
            unit_id="unit-1",
            result="FAIL",
            error_code="E1",
            error_message="password=secret voltage fault",
            signature="signature-1",
            analysis_cache_key="cache-1",
            product_code="P1",
            op_id="OP1",
            failing_step="VoltageCheck",
            analysis_source="llm",
            run_folder="unit-1",
        )
    ]
    store = DiskFeedbackStore(str(tmp_path / "feedback.json"))
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_feedback_store] = lambda: store
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_feedback_route_derives_metadata_and_redacts_notes(feedback_client) -> None:
    response = feedback_client.post(
        "/api/jobs/owned-job/feedback",
        headers=auth_headers(login="octocat", github_id="42"),
        json={"unit_id": "unit-1", "action": "fixed_after_action", "note": "password=secret"},
    )

    assert response.status_code == 200
    entry = response.json()
    assert entry["signature"] == "signature-1"
    assert entry["cache_key"] == "cache-1"
    assert entry["product_code"] == "P1"
    assert "secret" not in entry["note"]
    assert "secret" not in entry["error_message"]

    listed = feedback_client.get(
        "/api/jobs/owned-job/feedback",
        headers=auth_headers(login="octocat", github_id="42"),
    ).json()
    assert len(listed["entries"]) == 1


def test_feedback_route_hides_other_users_job(feedback_client) -> None:
    response = feedback_client.post(
        "/api/jobs/owned-job/feedback",
        headers=auth_headers(login="hubot", github_id="99"),
        json={"unit_id": "unit-1", "action": "helpful"},
    )

    assert response.status_code == 404