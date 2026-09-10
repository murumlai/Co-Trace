"""Regression tests for uploaded-doc ingestion scope and async/thread behavior."""
from __future__ import annotations

import asyncio
import io

import pytest
from fastapi.testclient import TestClient

from app.knowledge.models import KnowledgeManifest, ProductManifestEntry, SourceDocumentMeta
from tests.auth_helpers import admin_auth_headers


def _manifest(product_code: str = "M79060-001") -> KnowledgeManifest:
    return KnowledgeManifest(
        generated_at="2026-07-31T00:00:00+00:00",
        global_hash="g",
        products=[ProductManifestEntry(product_code=product_code, section_count=1)],
    )


class StoreStub:
    def __init__(self) -> None:
        self.manifest = None

    def load_manifest(self):
        return self.manifest


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

    store = StoreStub()
    ingestion = BuildOnlyIngestion()
    retriever = RetrieverStub()
    fastapi_app.dependency_overrides[get_knowledge_store] = lambda: store
    fastapi_app.dependency_overrides[get_knowledge_retriever] = lambda: retriever
    fastapi_app.dependency_overrides[get_knowledge_ingestion] = lambda: ingestion

    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield client, ingestion, retriever, store
    fastapi_app.dependency_overrides.clear()


def _auth(client) -> dict:  # noqa: ARG001
    return admin_auth_headers()


def test_upload_rebuilds_pack_with_existing_source_documents_off_event_loop(client_env, tmp_path):
    client, ingestion, retriever, _ = client_env
    other_docs = tmp_path / "other_docs"
    other_docs.mkdir(parents=True, exist_ok=True)
    (other_docs / "M79060-001_Debug.pdf").write_bytes(b"%PDF-1.4 fake")

    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("N32828-201_HLD.docx", io.BytesIO(b"fake docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert resp.status_code == 200
    assert {doc.filename for doc in ingestion.docs} == {
        "M79060-001_Debug.pdf",
        "N32828-201_HLD.docx",
    }
    assert {doc.product_code for doc in ingestion.docs} == {"M79060-001", "N32828-201"}
    assert ingestion.saw_running_loop is False
    assert retriever.invalidated is True


def test_upload_xlsx_accepted_and_saved(client_env, tmp_path):
    client, ingestion, _, _ = client_env
    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("N32828_RFC.xlsx", io.BytesIO(b"PK fake xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "N32828_RFC.xlsx"


def test_upload_unsupported_extension_returns_400(client_env):
    client, _, _, _ = client_env
    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": ("readme.md", io.BytesIO(b"# hi"), "text/markdown")},
    )
    assert resp.status_code == 400
    assert "XLSX" in resp.json()["detail"]


def _seed_existing_doc(tmp_path, name="N32828-201_HLD.docx", content=b"old"):
    docs_dir = tmp_path / "product_docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / name
    path.write_bytes(content)
    return path


def test_upload_check_reports_existing_file_and_pack_state(client_env, tmp_path):
    client, _, _, store = client_env
    from app.knowledge import parsing

    path = _seed_existing_doc(tmp_path)
    doc = parsing.describe_document(str(path))
    store.manifest = KnowledgeManifest(
        generated_at="2026-07-31T00:00:00+00:00",
        global_hash="g",
        documents=[SourceDocumentMeta(doc_id=doc.doc_id, filename=doc.filename)],
    )

    resp = client.get(
        "/api/knowledge/upload/check",
        headers=_auth(client),
        params={"filename": path.name},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["exists"] is True
    assert body["knowledge_exists"] is True
    assert body["doc_id"] == doc.doc_id


def test_duplicate_upload_without_policy_returns_409_and_keeps_old_file(client_env, tmp_path):
    client, ingestion, _, _ = client_env
    path = _seed_existing_doc(tmp_path, content=b"old")

    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        files={"file": (path.name, io.BytesIO(b"new"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert resp.status_code == 409
    assert path.read_bytes() == b"old"
    assert ingestion.docs == []


def test_duplicate_upload_replace_overwrites_and_ingests(client_env, tmp_path):
    client, ingestion, retriever, _ = client_env
    path = _seed_existing_doc(tmp_path, content=b"old")

    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        data={"duplicate_policy": "replace"},
        files={"file": (path.name, io.BytesIO(b"new"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert resp.status_code == 200
    assert path.read_bytes() == b"new"
    assert [doc.filename for doc in ingestion.docs] == [path.name]
    assert retriever.invalidated is True


def test_duplicate_upload_keep_old_with_existing_knowledge_skips_ingestion(client_env, tmp_path):
    client, ingestion, retriever, store = client_env
    from app.knowledge import parsing

    path = _seed_existing_doc(tmp_path, content=b"old")
    doc = parsing.describe_document(str(path))
    store.manifest = KnowledgeManifest(
        generated_at="2026-07-31T00:00:00+00:00",
        global_hash="g",
        documents=[SourceDocumentMeta(doc_id=doc.doc_id, filename=doc.filename)],
    )

    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        data={"duplicate_policy": "keep"},
        files={"file": (path.name, io.BytesIO(b"new"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] is None
    assert body["kept_existing"] is True
    assert body["knowledge_exists"] is True
    assert path.read_bytes() == b"old"
    assert ingestion.docs == []
    assert retriever.invalidated is False


def test_duplicate_upload_keep_old_without_knowledge_ingests_existing_file(client_env, tmp_path):
    client, ingestion, retriever, _ = client_env
    path = _seed_existing_doc(tmp_path, content=b"old")

    resp = client.post(
        "/api/knowledge/upload",
        headers=_auth(client),
        data={"duplicate_policy": "keep"},
        files={"file": (path.name, io.BytesIO(b"new"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert resp.status_code == 200
    assert resp.json()["kept_existing"] is True
    assert resp.json()["knowledge_exists"] is False
    assert path.read_bytes() == b"old"
    assert [doc.filename for doc in ingestion.docs] == [path.name]
    assert retriever.invalidated is True
