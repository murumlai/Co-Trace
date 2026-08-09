"""Safety-net smoke tests: FastAPI route shapes and auth enforcement.

Uses Starlette TestClient without running the lifespan so registry.load_from_disk
is not invoked. Tests only route-level contract: health, OAuth, and auth guards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import auth_headers

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
# GitHub OAuth routes
# ---------------------------------------------------------------------------

class TestGitHubOAuthRoutes:
    def test_authorize_redirects_to_github_and_sets_state_cookie(self, client, monkeypatch):
        import app.config as cfg

        monkeypatch.setattr(cfg.settings, "GITHUB_CLIENT_ID", "client-id")
        resp = client.get("/api/auth/github", follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"].startswith("https://github.com/login/oauth/authorize?")
        assert f"{cfg.settings.OAUTH_STATE_COOKIE_NAME}=" in resp.headers["set-cookie"]

    def test_callback_state_mismatch_redirects_with_error(self, client):
        resp = client.get(
            "/api/auth/github/callback?code=abc&state=bad",
            cookies={"github_oauth_state": "good"},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert "auth_error=state_mismatch" in resp.headers["location"]

    def test_callback_sets_session_cookie(self, client, monkeypatch):
        import app.config as cfg
        from app.auth import AuthenticatedUser, get_auth

        async def fake_authenticate_code(code: str) -> AuthenticatedUser:
            assert code == "abc"
            return AuthenticatedUser(login="octocat", github_id="42", is_admin=False)

        monkeypatch.setattr(cfg.settings, "FRONTEND_URL", "http://localhost:5173")
        monkeypatch.setattr(get_auth(), "authenticate_code", fake_authenticate_code)

        resp = client.get(
            "/api/auth/github/callback?code=abc&state=state123",
            cookies={"github_oauth_state": "state123"},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert resp.headers["location"] == "http://localhost:5173"
        assert "session=" in resp.headers["set-cookie"]


# ---------------------------------------------------------------------------
# Auth-guarded endpoints require a valid session cookie
# ---------------------------------------------------------------------------

class TestAuthGuards:
    def test_jobs_list_without_session_returns_401(self, client):
        """Unauthenticated job status request must be rejected."""
        client.cookies.clear()
        resp = client.get("/api/jobs/somejobid/status")
        assert resp.status_code == 401

    def test_upload_without_session_returns_401(self, client):
        import io
        client.cookies.clear()
        resp = client.post(
            "/api/upload",
            files={"files": ("test.txt", io.BytesIO(b"data"), "text/plain")},
            data={"paths": ["test.txt"]},
        )
        assert resp.status_code == 401

    def test_me_with_valid_session_returns_user_metadata(self, client):
        resp = client.get("/api/me", headers=auth_headers(login="octocat", github_id="42", is_admin=False))
        assert resp.status_code == 200
        assert resp.json().get("username") == "octocat"
        assert resp.json().get("github_id") == "42"
        assert resp.json().get("role") == "user"

    def test_me_with_invalid_session_returns_401(self, client):
        client.cookies.clear()
        resp = client.get("/api/me", cookies={"session": "invalid_token_xxx"})
        assert resp.status_code == 401

    def test_logout_clears_session_cookie(self, client):
        resp = client.post("/api/logout", headers=auth_headers(), follow_redirects=False)
        assert resp.status_code == 200
        assert "session=" in resp.headers["set-cookie"]
