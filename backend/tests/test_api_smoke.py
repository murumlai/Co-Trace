"""Safety-net smoke tests: FastAPI route shapes and auth enforcement.

Uses Starlette TestClient without running the lifespan so registry.load_from_disk
is not invoked. Tests only route-level contract: health, login, and auth guards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Patch settings before importing main so makedirs uses a safe default.
# (settings.WORK_DIR is already cwd/.cotrace_work which is harmless, but
#  we redirect ANALYSIS_CACHE_FILE to avoid touching a real cache.)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("smoke")
    import app.config as cfg
    cfg.settings.ANALYSIS_CACHE_FILE = str(tmp / "cache.json")
    # Import app after patching; this also runs module-level makedirs.
    from app.main import app as fastapi_app
    # Use TestClient without context manager to skip lifespan (no load_from_disk).
    return TestClient(fastapi_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_response_has_status_ok(self, client):
        data = client.get("/api/health").json()
        assert data["status"] == "ok"

    def test_response_has_llm_provider_key(self, client):
        data = client.get("/api/health").json()
        assert "llm_provider" in data

    def test_response_has_debug_key(self, client):
        data = client.get("/api/health").json()
        assert "debug" in data


# ---------------------------------------------------------------------------
# POST /api/login
# ---------------------------------------------------------------------------

class TestLoginEndpoint:
    def test_valid_credentials_return_200(self, client):
        resp = client.post("/api/login", json={"username": "admin", "password": "admin"})
        assert resp.status_code == 200

    def test_valid_credentials_return_token(self, client):
        data = client.post("/api/login",
                           json={"username": "admin", "password": "admin"}).json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 10

    def test_valid_credentials_return_username(self, client):
        data = client.post("/api/login",
                           json={"username": "admin", "password": "admin"}).json()
        assert data.get("username") == "admin"

    def test_invalid_credentials_return_401(self, client):
        resp = client.post("/api/login",
                           json={"username": "admin", "password": "wrongpassword"})
        assert resp.status_code == 401

    def test_missing_body_returns_error(self, client):
        resp = client.post("/api/login", json={})
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Auth-guarded endpoints require a valid bearer token
# ---------------------------------------------------------------------------

class TestAuthGuards:
    def _get_token(self, client) -> str:
        data = client.post("/api/login",
                           json={"username": "admin", "password": "admin"}).json()
        return data["token"]

    def test_jobs_list_without_token_returns_401(self, client):
        """Unauthenticated job status request must be rejected."""
        resp = client.get("/api/jobs/somejobid/status")
        assert resp.status_code == 401

    def test_upload_without_token_returns_401(self, client):
        import io
        resp = client.post(
            "/api/upload",
            files={"files": ("test.txt", io.BytesIO(b"data"), "text/plain")},
            data={"paths": ["test.txt"]},
        )
        assert resp.status_code == 401

    def test_me_with_valid_token_returns_username(self, client):
        token = self._get_token(client)
        resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json().get("username") == "admin"

    def test_me_with_invalid_token_returns_401(self, client):
        resp = client.get("/api/me",
                          headers={"Authorization": "Bearer invalid_token_xxx"})
        assert resp.status_code == 401
