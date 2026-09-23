from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.investigation_action_store import ActionVersionConflict, DiskInvestigationActionStore
from app.job_registry import JobRegistry
from app.models import InvestigationActionEntry, InvestigationActionEvent, UnitRecord
from tests.auth_helpers import auth_headers


def _entry(action_id: str = "action-1", *, expires_at: float | None = None) -> InvestigationActionEntry:
    now = datetime.now(timezone.utc).isoformat()
    event = InvestigationActionEvent(
        version=1,
        actor_id="42",
        actor_login="octocat",
        changed_at=now,
        status="open",
        assignee="Test team",
        next_action="Inspect fixture",
    )
    return InvestigationActionEntry(
        action_id=action_id,
        job_id="job-1",
        owner_id="42",
        owner_login="octocat",
        unit_id="unit-1",
        product_code="P1",
        error_code="E1",
        assignee="Test team",
        next_action="Inspect fixture",
        created_at=now,
        updated_at=now,
        expires_at=expires_at or time.time() + 3600,
        history=[event],
    )


def test_store_updates_version_and_appends_audit_history(tmp_path):
    store = DiskInvestigationActionStore(str(tmp_path / "actions.json"))
    store.create(_entry())

    updated = store.update(
        "action-1", "42", 1,
        actor_id="42", actor_login="octocat",
        assignee="Product team", next_action="Measure rail", status="in_progress",
        fields_set={"assignee", "next_action", "status"},
    )

    assert updated.version == 2
    assert updated.status == "in_progress"
    assert updated.assignee == "Product team"
    assert updated.next_action == "Measure rail"
    assert len(updated.history) == 2
    assert updated.history[-1].previous_status == "open"
    assert updated.history[-1].actor_login == "octocat"


def test_store_rejects_stale_update_and_preserves_current(tmp_path):
    store = DiskInvestigationActionStore(str(tmp_path / "actions.json"))
    store.create(_entry())
    store.update(
        "action-1", "42", 1,
        actor_id="42", actor_login="octocat", assignee=None,
        next_action=None, status="blocked", fields_set={"status"},
    )

    with pytest.raises(ActionVersionConflict) as error:
        store.update(
            "action-1", "42", 1,
            actor_id="42", actor_login="octocat", assignee=None,
            next_action=None, status="resolved", fields_set={"status"},
        )

    assert error.value.current.version == 2
    assert error.value.current.status == "blocked"


def test_store_expires_entries_and_writes_atomically(tmp_path):
    path = tmp_path / "actions.json"
    store = DiskInvestigationActionStore(str(path))
    store.create(_entry("expired", expires_at=time.time() - 1))
    store.create(_entry("active"))

    entries = store.list_for_job("job-1", "42")

    assert [entry.action_id for entry in entries] == ["active"]
    assert not list(tmp_path.glob("*.tmp"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [item["action_id"] for item in payload["entries"]] == ["active"]


@pytest.fixture()
def action_api(tmp_path):
    from app.auth import SHARED_WORKSPACE_ID
    from app.dependencies import get_investigation_action_store, get_registry
    from app.main import app

    workdir = tmp_path / "job"
    workdir.mkdir()
    registry = JobRegistry()
    job = registry.create("job-1", str(workdir), owner_id=SHARED_WORKSPACE_ID, owner_login=SHARED_WORKSPACE_ID)
    job.records = [
        UnitRecord(
            unit_id="unit-1", serial_number="SN1", result="FAIL",
            product_code="P1", error_code="E1", error_message="password=secret failed",
            signature="sig-1",
        )
    ]
    store = DiskInvestigationActionStore(str(tmp_path / "actions.json"))
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_investigation_action_store] = lambda: store
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_registry, None)
        app.dependency_overrides.pop(get_investigation_action_store, None)


def test_action_api_create_list_update_and_conflict(action_api):
    headers = auth_headers(login="octocat", github_id="42")
    created_response = action_api.post(
        "/api/jobs/job-1/actions",
        headers=headers,
        json={
            "unit_id": "unit-1",
            "assignee": "Test team",
            "next_action": "Check password=secret fixture",
        },
    )
    assert created_response.status_code == 200
    created = created_response.json()
    assert "secret" not in created["next_action"]
    assert created["version"] == 1
    assert len(created["history"]) == 1

    listed = action_api.get("/api/jobs/job-1/actions", headers=headers).json()["entries"]
    assert [entry["action_id"] for entry in listed] == [created["action_id"]]

    updated_response = action_api.patch(
        f"/api/jobs/job-1/actions/{created['action_id']}",
        headers=headers,
        json={"expected_version": 1, "status": "resolved"},
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["version"] == 2
    assert updated_response.json()["status"] == "resolved"

    conflict = action_api.patch(
        f"/api/jobs/job-1/actions/{created['action_id']}",
        headers=headers,
        json={"expected_version": 1, "status": "blocked"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current"]["version"] == 2


def test_action_api_shares_workspace_but_validates_target(action_api):
    other = auth_headers(login="hubot", github_id="99")
    assert action_api.get("/api/jobs/job-1/actions", headers=other).status_code == 200
    response = action_api.post(
        "/api/jobs/job-1/actions",
        headers=auth_headers(),
        json={"unit_id": "missing", "next_action": "Inspect"},
    )
    assert response.status_code == 404
