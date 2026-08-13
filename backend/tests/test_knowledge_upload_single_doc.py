"""Regression tests for uploaded-doc ingestion scope and async/thread behavior."""
from __future__ import annotations

import asyncio
import io

import pytest
from fastapi.testclient import TestClient

from app.knowledge.models import KnowledgeManifest, ProductManifestEntry
from tests.auth_helpers import admin_auth_headers


def _manifest(product_code: str = "M79060-001") -> KnowledgeManifest:
    return KnowledgeManifest(
        generated_at="2026-07-31T00:00:00+00:00",
        global_hash="g",
        products=[ProductManifestEntry(product_code=product_code, section_count=1)],
    )


class StoreStub:
    def load_manifest(self):
        return None


class RetrieverStub:
    def __init__(self) -> None:
        self.invalidated = False

    def invalidate(self):
        self.invalidated = True


class BuildOnlyIngestion:
    def __init__(self) -> None:
        self.docs = []
        self.saw_running_loop = False

    def build(self, docs, progress=None):  # noqa: ARG002
        self.docs = list(docs)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.saw_running_loop = False
        else:
            self.saw_running_loop = True
        return _manifest(self.docs[0].product_code)


@pytest.fixture()
def client_env(tmp_path):
    import app.config as cfg

    cfg.settings.PRODUCT_KNOWLEDGE_DOCS_DIR = str(tmp_path / "product_docs")
    cfg.settings.PRODUCT_KNOWLEDGE_SOURCE_DIRS = [str(tmp_path / "other_docs")]

    from app.dependencies import (
        get_knowledge_ingestion,
        get_knowledge_retriever,
        get_knowledge_store,
    )
    from app.main import app as fastapi_app

    ingestion = BuildOnlyIngestion()
    retriever = RetrieverStub()
    fastapi_app.dependency_overrides[get_knowledge_store] = lambda: StoreStub()
    fastapi_app.dependency_overrides[get_knowledge_retriever] = lambda: retriever
    fastapi_app.dependency_overrides[get_knowledge_ingestion] = lambda: ingestion

    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield client, ingestion, retriever
    fastapi_app.dependency_overrides.clear()


def _auth(client) -> dict:  # noqa: ARG001
    return admin_auth_headers()


def test_upload_builds_only_the_uploaded_document_and_runs_off_event_loop(client_env):
    client, ingestion, retriever = client_env
    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("N32828-201_HLD.docx", io.BytesIO(b"fake docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert resp.status_code == 200
    assert len(ingestion.docs) == 1
    assert ingestion.docs[0].filename == "N32828-201_HLD.docx"
    assert ingestion.docs[0].product_code == "N32828-201"
    assert ingestion.saw_running_loop is False
    assert retriever.invalidated is True


def test_upload_xlsx_accepted_and_saved(client_env, tmp_path):
    client, ingestion, _ = client_env
    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("N32828_RFC.xlsx", io.BytesIO(b"PK fake xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "N32828_RFC.xlsx"


def test_upload_unsupported_extension_returns_400(client_env):
    client, _, _ = client_env
    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("readme.md", io.BytesIO(b"# hi"), "text/markdown")},
    )
    assert resp.status_code == 400
    assert "XLSX" in resp.json()["detail"]
