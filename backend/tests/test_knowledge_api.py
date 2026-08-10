"""API tests for the knowledge management routes (auth + validation + fakes)."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.knowledge.models import KnowledgeManifest, ProductManifestEntry
from app.knowledge.summarizer import ProductKnowledgeError
from tests.auth_helpers import admin_auth_headers, auth_headers


def _manifest() -> KnowledgeManifest:
    return KnowledgeManifest(
        generated_at="2026-07-31T00:00:00+00:00",
        global_hash="g",
        products=[ProductManifestEntry(product_code="M79060-001", section_count=2)],
        category_counts={"debug_learning": 2},
    )


class FakeStore:
    def load_manifest(self):
        return _manifest()

    def iter_sections(self):
        return []

    def delete_pack(self):
        self.deleted = True


class FakeRetriever:
    def invalidate(self):
        self.invalidated = True


class FakeIngestion:
    def __init__(self):
        self.raise_error = False
        self.rebuilt = 0

    def rebuild(self, progress=None):  # noqa: ARG002
        if self.raise_error:
            raise ProductKnowledgeError("no llm")
        self.rebuilt += 1
        return _manifest()


@pytest.fixture()
def env(tmp_path):
    import app.config as cfg

    cfg.settings.ANALYSIS_CACHE_FILE = str(tmp_path / "cache.json")
    cfg.settings.PRODUCT_KNOWLEDGE_DOCS_DIR = str(tmp_path / "product_docs")
    cfg.settings.PRODUCT_KNOWLEDGE_SOURCE_DIRS = [str(tmp_path / "empty_src")]

    from app.dependencies import (
        get_knowledge_ingestion,
        get_knowledge_retriever,
        get_knowledge_store,
    )
    from app.main import app as fastapi_app

    ingestion = FakeIngestion()
    app_state = {"ingestion": ingestion}
    fastapi_app.dependency_overrides[get_knowledge_store] = lambda: FakeStore()
    fastapi_app.dependency_overrides[get_knowledge_retriever] = lambda: FakeRetriever()
    fastapi_app.dependency_overrides[get_knowledge_ingestion] = lambda: ingestion

    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield client, app_state
    fastapi_app.dependency_overrides.clear()


def _auth(client) -> dict:  # noqa: ARG001
    return auth_headers()


def _admin_auth(client) -> dict:  # noqa: ARG001
    return admin_auth_headers()


class TestKnowledgeRoutesAuth:
    def test_status_without_session_401(self, env):
        client, _ = env
        assert client.get("/api/knowledge").status_code == 401

    def test_rebuild_without_session_401(self, env):
        client, _ = env
        assert client.post("/api/knowledge/rebuild").status_code == 401


class TestKnowledgeRoutes:
    def test_status_ok(self, env):
        client, _ = env
        resp = client.get("/api/knowledge", headers=_auth(client))
        assert resp.status_code == 200
        body = resp.json()
        assert "enabled" in body
        assert body["manifest"]["products"][0]["product_code"] == "M79060-001"

    def test_scan_ok(self, env):
        client, _ = env
        resp = client.get("/api/knowledge/scan", headers=_auth(client))
        assert resp.status_code == 200
        assert resp.json()["documents"] == []

    def test_sections_ok(self, env):
        client, _ = env
        resp = client.get("/api/knowledge/sections", headers=_auth(client))
        assert resp.status_code == 200
        assert resp.json()["sections"] == []

    def test_rebuild_ok(self, env):
        client, state = env
        resp = client.post("/api/knowledge/rebuild", headers=_admin_auth(client))
        assert resp.status_code == 200
        assert resp.json()["manifest"]["global_hash"] == "g"
        assert state["ingestion"].rebuilt == 1

    def test_rebuild_without_llm_returns_503(self, env):
        client, state = env
        state["ingestion"].raise_error = True
        resp = client.post("/api/knowledge/rebuild", headers=_admin_auth(client))
        assert resp.status_code == 503

    def test_non_admin_rebuild_forbidden(self, env):
        client, state = env
        resp = client.post("/api/knowledge/rebuild", headers=_auth(client))
        assert resp.status_code == 403
        assert state["ingestion"].rebuilt == 0

    def test_upload_rejects_unsupported_type(self, env):
        client, _ = env
        resp = client.post(
            "/api/knowledge/upload",
            headers=_admin_auth(client),
            files={"file": ("notes.txt", io.BytesIO(b"data"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_pdf_saves_and_rebuilds(self, env, tmp_path):
        client, state = env
        resp = client.post(
            "/api/knowledge/upload",
            headers=_admin_auth(client),
            files={"file": ("M79060-001_Debug.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "M79060-001_Debug.pdf"
        assert state["ingestion"].rebuilt == 1
        saved = tmp_path / "product_docs" / "M79060-001_Debug.pdf"
        assert saved.exists()

    def test_delete_pack_ok(self, env):
        client, _ = env
        resp = client.delete("/api/knowledge", headers=_admin_auth(client))
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_non_admin_delete_pack_forbidden(self, env):
        client, _ = env
        resp = client.delete("/api/knowledge", headers=_auth(client))
        assert resp.status_code == 403
