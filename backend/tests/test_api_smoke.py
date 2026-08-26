"""Safety-net smoke tests: FastAPI route shapes and auth enforcement.

Uses Starlette TestClient without running the lifespan so registry.load_from_disk
is not invoked. Tests only route-level contract: health, OAuth, and auth guards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import admin_auth_headers, auth_headers

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

    def test_response_has_non_secret_llm_auth_flags(self, client):
        data = client.get("/api/health").json()
        assert set(data["llm_auth"]) == {
            "copilot_sdk_available",
            "copilot_token_configured",
            "github_models_token_configured",
        }
        assert all(isinstance(value, bool) for value in data["llm_auth"].values())


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


class TestAdminLoginRoute:
    def test_admin_login_success_sets_session_and_is_admin(self, client, monkeypatch):
        import app.config as cfg

        monkeypatch.setattr(cfg.settings, "ADMIN_USERNAME", "maint")
        monkeypatch.setattr(cfg.settings, "ADMIN_PASSWORD", "s3cret")

        resp = client.post(
            "/api/auth/admin/login",
            json={"username": "maint", "password": "s3cret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["user"]["is_admin"] is True
        assert "session=" in resp.headers["set-cookie"]

        # The admin grant must persist across requests (not recomputed away).
        me = client.get("/api/me")
        assert me.status_code == 200
        assert me.json()["is_admin"] is True

    def test_admin_login_wrong_password_401(self, client, monkeypatch):
        import app.config as cfg

        monkeypatch.setattr(cfg.settings, "ADMIN_USERNAME", "maint")
        monkeypatch.setattr(cfg.settings, "ADMIN_PASSWORD", "s3cret")
        client.cookies.clear()

        resp = client.post(
            "/api/auth/admin/login",
            json={"username": "maint", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_admin_login_disabled_when_no_password_503(self, client, monkeypatch):
        import app.config as cfg

        monkeypatch.setattr(cfg.settings, "ADMIN_PASSWORD", "")
        client.cookies.clear()

        resp = client.post(
            "/api/auth/admin/login",
            json={"username": "admin", "password": "anything"},
        )
        assert resp.status_code == 503


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


class TestJobOwnership:
    @pytest.fixture()
    def registry_with_owned_job(self, client, tmp_path):
        from app.dependencies import get_registry
        from app.job_registry import JobRegistry

        reg = JobRegistry()
        workdir = tmp_path / "owned-job"
        workdir.mkdir()
        reg.create("owned-job", str(workdir), owner_id="42", owner_login="octocat")
        client.app.dependency_overrides[get_registry] = lambda: reg
        try:
            yield reg
        finally:
            client.app.dependency_overrides.pop(get_registry, None)

    def test_owner_can_read_job_status(self, client, registry_with_owned_job):
        resp = client.get(
            "/api/jobs/owned-job/status",
            headers=auth_headers(login="octocat", github_id="42"),
        )

        assert resp.status_code == 200
        assert resp.json()["job_id"] == "owned-job"

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/jobs/owned-job/status"),
            ("POST", "/api/jobs/owned-job/stop"),
            ("GET", "/api/jobs/owned-job/units"),
            ("POST", "/api/jobs/owned-job/units/u1/reanalyze"),
            ("GET", "/api/jobs/owned-job/manager"),
        ],
    )
    def test_other_user_cannot_access_job_routes(self, client, registry_with_owned_job, method, path):
        resp = client.request(
            method,
            path,
            headers=auth_headers(login="hubot", github_id="99"),
        )

        assert resp.status_code == 404

    def test_non_admin_owner_cannot_clear_job_cache(self, client, registry_with_owned_job):
        resp = client.delete(
            "/api/jobs/owned-job/cache",
            headers=auth_headers(login="octocat", github_id="42"),
        )
        assert resp.status_code == 403

    def test_admin_owner_can_clear_job_cache(self, client, registry_with_owned_job, monkeypatch):
        import app.config as cfg

        monkeypatch.setattr(cfg.settings, "GITHUB_ADMIN_USERS", ["octocat"])
        resp = client.delete(
            "/api/jobs/owned-job/cache",
            headers=auth_headers(login="octocat", github_id="42", is_admin=True),
        )
        assert resp.status_code == 200


class TestAnalysisCacheDeletionAdminOnly:
    def test_non_admin_cannot_delete_analysis_cache(self, client):
        client.cookies.clear()
        resp = client.delete(
            "/api/cache/analysis/somekey",
            headers=auth_headers(login="octocat", github_id="42"),
        )
        assert resp.status_code == 403

    def test_admin_can_delete_analysis_cache(self, client):
        client.cookies.clear()
        resp = client.delete("/api/cache/analysis/somekey", headers=admin_auth_headers())
        assert resp.status_code == 200


class TestUploadOptions:
    def test_upload_records_force_refresh_option(self, client, tmp_path):
        import io
        from app.dependencies import get_orchestrator, get_registry
        from app.job_registry import JobRegistry

        class NoopOrchestrator:
            def run_job(self, job_id):  # noqa: ARG002
                return None

        reg = JobRegistry()
        client.app.dependency_overrides[get_registry] = lambda: reg
        client.app.dependency_overrides[get_orchestrator] = lambda: NoopOrchestrator()
        try:
            resp = client.post(
                "/api/upload",
                headers=auth_headers(login="octocat", github_id="42"),
                files={"files": ("test.txt", io.BytesIO(b"data"), "text/plain")},
                data={"paths": ["test.txt"], "force_refresh": "true"},
            )
        finally:
            client.app.dependency_overrides.pop(get_registry, None)
            client.app.dependency_overrides.pop(get_orchestrator, None)

        assert resp.status_code == 200
        job = reg.get(resp.json()["job_id"])
        assert job is not None
        assert job.force_refresh is True
        assert job.owner_id == "42"
