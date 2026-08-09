"""API tests for the acronym glossary review/maintenance routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import auth_headers


@pytest.fixture()
def env(tmp_path):
    import app.config as cfg

    cfg.settings.ANALYSIS_CACHE_FILE = str(tmp_path / "cache.json")

    from app.dependencies import get_acronym_glossary_store
    from app.knowledge.acronym_glossary import AcronymGlossaryStore
    from app.main import app as fastapi_app

    store = AcronymGlossaryStore(path=str(tmp_path / "product_acronyms.json"))
    fastapi_app.dependency_overrides[get_acronym_glossary_store] = lambda: store
    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield client, store
    fastapi_app.dependency_overrides.clear()


def _auth(client) -> dict:  # noqa: ARG001
    return auth_headers()


class TestAcronymRoutesAuth:
    def test_list_without_session_401(self, env):
        client, _ = env
        assert client.get("/api/knowledge/acronyms").status_code == 401

    def test_upsert_without_session_401(self, env):
        client, _ = env
        assert client.post("/api/knowledge/acronyms", json={"acronym": "PAN"}).status_code == 401


class TestAcronymRoutes:
    def test_list_empty(self, env):
        client, _ = env
        resp = client.get("/api/knowledge/acronyms", headers=_auth(client))
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []
        assert "enabled" in body

    def test_upsert_approved_persists(self, env):
        client, store = env
        resp = client.post(
            "/api/knowledge/acronyms",
            headers=_auth(client),
            json={"acronym": "pan", "definition": "Board assembly",
                  "product_code": "M79060-001", "status": "approved"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["acronym"] == "PAN"
        assert body["status"] == "approved"
        assert body["source"] == "manual"
        assert len(store.list_entries()) == 1

    def test_approve_requires_definition(self, env):
        client, _ = env
        resp = client.post(
            "/api/knowledge/acronyms",
            headers=_auth(client),
            json={"acronym": "PAN", "status": "approved"},
        )
        assert resp.status_code == 400

    def test_reject_needs_no_definition(self, env):
        client, store = env
        resp = client.post(
            "/api/knowledge/acronyms",
            headers=_auth(client),
            json={"acronym": "WW", "status": "rejected"},
        )
        assert resp.status_code == 200
        assert store.list_entries()[0].status == "rejected"

    def test_empty_acronym_rejected(self, env):
        client, _ = env
        resp = client.post(
            "/api/knowledge/acronyms",
            headers=_auth(client),
            json={"acronym": "   ", "status": "needs_review"},
        )
        assert resp.status_code == 400

    def test_filter_by_status(self, env):
        client, store = env
        store.upsert_entry(acronym="AIC", definition="Add-In Card", product_code=None, status="approved")
        store.upsert_entry(acronym="XYZ", definition=None, product_code="P1", status="needs_review")
        resp = client.get("/api/knowledge/acronyms?status=needs_review", headers=_auth(client))
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert [e["acronym"] for e in entries] == ["XYZ"]

    def test_delete_entry(self, env):
        client, store = env
        store.upsert_entry(acronym="ABC", definition="A B C", product_code="P1", status="approved")
        resp = client.delete("/api/knowledge/acronyms?acronym=ABC&product=P1", headers=_auth(client))
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "ABC"
        assert store.list_entries() == []

    def test_delete_missing_returns_404(self, env):
        client, _ = env
        resp = client.delete("/api/knowledge/acronyms?acronym=NOPE", headers=_auth(client))
        assert resp.status_code == 404
