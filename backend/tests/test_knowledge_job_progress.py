"""Progress endpoint contract for background knowledge upload jobs."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.knowledge.models import KnowledgeManifest, ProductManifestEntry


class StoreStub:
    def load_manifest(self):
        return None


class RetrieverStub:
    def invalidate(self):
        return None


class ProgressIngestion:
    def build(self, docs, progress=None):
        if progress:
            progress(0, 2, "Summarizing section 0/2")
            progress(1, 2, "Summarizing section 1/2")
            progress(2, 2, "Summarizing section 2/2")
        return KnowledgeManifest(
            generated_at="2026-07-31T00:00:00+00:00",
            global_hash="g",
            products=[ProductManifestEntry(product_code=docs[0].product_code, section_count=2)],
        )


@pytest.fixture()
def client_env(tmp_path):
    import app.config as cfg

    cfg.settings.PRODUCT_KNOWLEDGE_DOCS_DIR = str(tmp_path / "product_docs")

    from app.dependencies import (
        get_knowledge_ingestion,
        get_knowledge_retriever,
        get_knowledge_store,
    )
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_knowledge_store] = lambda: StoreStub()
    fastapi_app.dependency_overrides[get_knowledge_retriever] = lambda: RetrieverStub()
    fastapi_app.dependency_overrides[get_knowledge_ingestion] = lambda: ProgressIngestion()

    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield client
    fastapi_app.dependency_overrides.clear()


def _auth(client) -> dict:
    token = client.post("/api/login", json={"username": "admin", "password": "admin"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_returns_pollable_job_status(client_env):
    client = client_env
    upload = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("M79060-001_Debug.pdf", io.BytesIO(b"fake"), "application/pdf")},
    ).json()

    assert upload["job_id"]
    status = client.get(f"/api/knowledge/jobs/{upload['job_id']}", headers=_auth(client)).json()
    assert status["status"] == "done"
    assert status["progress"] == {"processed": 1, "total": 1}
    assert status["manifest"]["global_hash"] == "g"


def test_unknown_job_returns_404(client_env):
    client = client_env
    resp = client.get("/api/knowledge/jobs/missing", headers=_auth(client))
    assert resp.status_code == 404
