from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analyzer import analyze_job, reanalyze_unit
from app.job_registry import Job
from app.knowledge.models import PlaybookCreateRequest
from app.knowledge.playbook_store import AdminPlaybookStore
from app.knowledge.retriever import LexicalKnowledgeRetriever
from app.knowledge.service import KnowledgeIngestionService
from app.knowledge.storage import KnowledgeStore
from app.models import UnitRecord
from app.record_views import signature_for
from tests.auth_helpers import admin_auth_headers, auth_headers


class CountingCache:
    def __init__(self) -> None:
        self.get_calls = 0
        self.put_calls = 0

    def make_key(self, **kwargs: Any) -> str:  # noqa: ARG002
        return "cache-key"

    def get(self, cache_key: str) -> dict[str, Any] | None:  # noqa: ARG002
        self.get_calls += 1
        return {"root_cause": "stale cache", "suggested_solution": "stale action"}

    def put(self, cache_key: str, **kwargs: Any) -> None:  # noqa: ARG002
        self.put_calls += 1


def _record(unit_id: str = "u1") -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id,
        serial_number=unit_id,
        product_code="P1",
        result="FAIL",
        error_code="E1",
        error_message="Voltage fault 17",
        run_folder=unit_id,
    )


def _create_playbook(
    store: AdminPlaybookStore,
    record: UnitRecord,
    *,
    status: str = "reviewed",
):
    return store.create(
        "playbook-1",
        PlaybookCreateRequest(
            product_code="P1",
            log_signature=signature_for(record),
            root_cause="Known fixture contact",
            corrective_action="Replace the worn pogo pin",
            review_status=status,
        ),
        owner="admin",
    )


def test_reviewed_playbook_precedes_cache_and_llm(tmp_path) -> None:
    record = _record()
    store = AdminPlaybookStore(str(tmp_path / "playbooks.json"))
    playbook = _create_playbook(store, record)
    cache = CountingCache()
    calls = 0
    progress: list[tuple[int, int, str, str]] = []

    def should_not_call(*args: Any):  # noqa: ANN202, ARG001
        nonlocal calls
        calls += 1
        raise AssertionError("LLM should not run for a reviewed playbook")

    job = Job(job_id="job", records=[record])
    analyze_job(
        job,
        analyze_failure=should_not_call,
        cache=cache,
        playbook_store=store,
        progress_callback=lambda processed, total, message, stage: progress.append(
            (processed, total, message, stage)
        ),
    )

    assert calls == 0
    assert cache.get_calls == 0
    assert cache.put_calls == 0
    assert record.analysis_source == "playbook"
    assert record.playbook_id == playbook.playbook_id
    assert record.analysis_cache_key is None
    assert job.llm_metrics.playbook_hits == 1
    assert job.llm_metrics.calls_skipped_by_cache == 1
    assert job.llm_metrics.disk_cache_hits == 0
    assert job.llm_metrics.local_cache_hits == 0
    assert progress[-1][2] == "Matched known failure for signature 1/1"
    assert progress[-1][3] == "playbook"


def test_duplicate_signature_keeps_playbook_provenance(tmp_path) -> None:
    first = _record("u1")
    second = _record("u2")
    store = AdminPlaybookStore(str(tmp_path / "playbooks.json"))
    _create_playbook(store, first)
    job = Job(job_id="job", records=[first, second])

    analyze_job(job, cache=CountingCache(), playbook_store=store)

    assert first.analysis_source == second.analysis_source == "playbook"
    assert first.playbook_id == second.playbook_id == "playbook-1"
    assert job.llm_metrics.playbook_hits == 2
    assert job.llm_metrics.cache_hits == 0


def test_draft_playbook_does_not_override_analysis(tmp_path) -> None:
    record = _record()
    store = AdminPlaybookStore(str(tmp_path / "playbooks.json"))
    _create_playbook(store, record, status="draft")

    analyze_job(
        Job(job_id="job", records=[record]),
        analyze_failure=lambda *args: ("live root", "live action", "stub"),
        cache=CountingCache(),
        playbook_store=store,
    )

    assert record.analysis_source == "local-cache"
    assert record.root_cause == "stale cache"


def test_retired_playbook_falls_through_on_reanalysis(tmp_path) -> None:
    record = _record()
    store = AdminPlaybookStore(str(tmp_path / "playbooks.json"))
    _create_playbook(store, record)
    job = Job(job_id="job", records=[record])
    analyze_job(job, cache=CountingCache(), playbook_store=store)
    store.retire("playbook-1")

    reanalyze_unit(
        job,
        record.unit_id,
        analyze_failure=lambda *args: ("fresh root", "fresh action", "stub"),
        playbook_store=store,
    )

    assert record.analysis_source == "stub"
    assert record.playbook_id is None
    assert record.root_cause == "fresh root"


def test_playbook_survives_knowledge_rebuild(tmp_path) -> None:
    record = _record()
    playbook_path = str(tmp_path / "playbooks.json")
    playbooks = AdminPlaybookStore(playbook_path)
    _create_playbook(playbooks, record)
    knowledge = KnowledgeStore(
        str(tmp_path / "manifest.json"),
        str(tmp_path / "index.json"),
        str(tmp_path / "sections.jsonl"),
    )

    KnowledgeIngestionService(knowledge).build([])

    assert AdminPlaybookStore(playbook_path).find_reviewed(
        signature=signature_for(record), product_code="P1"
    ) is not None


def test_retrieval_exposes_reviewed_playbooks_without_generated_pack(tmp_path) -> None:
    record = _record()
    playbooks = AdminPlaybookStore(str(tmp_path / "playbooks.json"))
    _create_playbook(playbooks, record)
    knowledge = KnowledgeStore(
        str(tmp_path / "missing-manifest.json"),
        str(tmp_path / "missing-index.json"),
        str(tmp_path / "missing-sections.jsonl"),
    )

    context = LexicalKnowledgeRetriever(knowledge, playbooks).retrieve(record)

    assert [entry.playbook_id for entry in context.admin_playbooks] == ["playbook-1"]


@pytest.fixture()
def playbook_client(tmp_path):
    from app.dependencies import get_playbook_store
    from app.main import app

    store = AdminPlaybookStore(str(tmp_path / "playbooks.json"))
    app.dependency_overrides[get_playbook_store] = lambda: store
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_playbook_routes_enforce_admin_mutation_and_support_retirement(playbook_client) -> None:
    payload = {
        "product_code": "P1",
        "log_signature": "0123456789abcdef",
        "root_cause": "Known root",
        "corrective_action": "Known action",
        "review_status": "draft",
    }
    forbidden = playbook_client.post(
        "/api/knowledge/playbooks",
        headers=auth_headers(),
        json=payload,
    )
    assert forbidden.status_code == 403

    created = playbook_client.post(
        "/api/knowledge/playbooks",
        headers=admin_auth_headers(),
        json=payload,
    )
    assert created.status_code == 200
    playbook_id = created.json()["playbook_id"]

    listed = playbook_client.get(
        "/api/knowledge/playbooks",
        headers=auth_headers(),
    )
    assert [entry["playbook_id"] for entry in listed.json()["entries"]] == [playbook_id]

    reviewed = playbook_client.patch(
        f"/api/knowledge/playbooks/{playbook_id}",
        headers=admin_auth_headers(),
        json={"review_status": "reviewed"},
    )
    assert reviewed.json()["review_status"] == "reviewed"

    retired = playbook_client.delete(
        f"/api/knowledge/playbooks/{playbook_id}",
        headers=admin_auth_headers(),
    )
    assert retired.json()["review_status"] == "retired"