"""Safety-net smoke tests: FastAPI route shapes and auth enforcement.

Uses Starlette TestClient without running the lifespan so registry.load_from_disk
is not invoked. Tests only route-level contract: health, OAuth, and auth guards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.auth import SHARED_WORKSPACE_ID

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
        }
        assert all(isinstance(value, bool) for value in data["llm_auth"].values())


# ---------------------------------------------------------------------------
# GitHub OAuth routes
# ---------------------------------------------------------------------------

class TestGitHubOAuthRoutes:
    @pytest.mark.parametrize("path", ["/api/auth/github", "/api/auth/github/callback?code=old&state=old"])
    def test_old_login_routes_are_disabled(self, client, path):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 410
        assert "set-cookie" not in response.headers


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
    @pytest.mark.parametrize("session", [None, "invalid_token_xxx"])
    def test_shared_workspace_needs_no_valid_session(self, client, session):
        client.cookies.clear()
        headers = {"Cookie": f"session={session}"} if session else {}
        response = client.get("/api/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["workspace_id"] == "shared-workspace"
        assert response.json()["is_admin"] is False

    def test_legacy_github_admin_cannot_elevate_shared_workspace(self, client):
        client.cookies.clear()
        response = client.get("/api/me", headers=auth_headers(is_admin=True))
        assert response.status_code == 200
        assert response.json()["workspace_id"] == "shared-workspace"
        assert response.json()["is_admin"] is False

    def test_missing_job_without_session_returns_404(self, client):
        client.cookies.clear()
        resp = client.get("/api/jobs/somejobid/status")
        assert resp.status_code == 404

    def test_upload_without_session_reaches_input_validation(self, client):
        client.cookies.clear()
        resp = client.post("/api/upload")
        assert resp.status_code == 422

    def test_me_ignores_legacy_user_identity(self, client):
        resp = client.get("/api/me", headers=auth_headers(login="octocat", github_id="42", is_admin=False))
        assert resp.status_code == 200
        assert resp.json().get("username") == SHARED_WORKSPACE_ID
        assert resp.json().get("github_id") == SHARED_WORKSPACE_ID
        assert resp.json().get("role") == "user"

    def test_invalid_session_cannot_delete_cache(self, client):
        client.cookies.clear()
        resp = client.delete("/api/cache/analysis/somekey", headers={"Cookie": "session=invalid_token_xxx"})
        assert resp.status_code == 403

    def test_logout_clears_session_cookie(self, client):
        resp = client.post("/api/logout", headers=auth_headers(), follow_redirects=False)
        assert resp.status_code == 200
        assert "session=" in resp.headers["set-cookie"]
        assert client.get("/api/me").json()["is_admin"] is False


class TestJobOwnership:
    @pytest.fixture()
    def registry_with_owned_job(self, client, tmp_path):
        from app.dependencies import get_registry
        from app.job_registry import JobRegistry

        reg = JobRegistry()
        workdir = tmp_path / "owned-job"
        workdir.mkdir()
        reg.create("owned-job", str(workdir), owner_id=SHARED_WORKSPACE_ID, owner_login=SHARED_WORKSPACE_ID)
        reg.create("legacy-job", str(tmp_path / "legacy-job"), owner_id="42", owner_login="octocat")
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

    def test_owner_lists_only_owned_job_summaries(self, client, registry_with_owned_job, tmp_path):
        registry_with_owned_job.create(
            "other-job",
            str(tmp_path / "other-job"),
            owner_id="99",
            owner_login="hubot",
        )

        resp = client.get(
            "/api/jobs",
            headers=auth_headers(login="octocat", github_id="42"),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [item["job_id"] for item in body["items"]] == ["owned-job"]
        assert body["items"][0]["display_name"] == "Batch owned-jo"
        assert body["items"][0]["result_available"] is False
        assert "records" not in body["items"][0]

    def test_jobs_list_rejects_invalid_cursor(self, client, registry_with_owned_job):
        resp = client.get(
            "/api/jobs?cursor=not-json",
            headers=auth_headers(login="octocat", github_id="42"),
        )

        assert resp.status_code == 400

    def test_manager_route_applies_repeated_scope_filters(self, client, registry_with_owned_job):
        from app.models import BatchMetadata, UnitRecord

        job = registry_with_owned_job.get("owned-job")
        assert job is not None
        job.batch = BatchMetadata(display_name="Scoped batch", product_codes=["P1", "P2"])
        job.records = [
            UnitRecord(unit_id="p1", serial_number="SN1", result="PASS", product_code="P1"),
            UnitRecord(unit_id="p2", serial_number="SN2", result="FAIL", product_code="P2"),
        ]

        resp = client.get(
            "/api/jobs/owned-job/manager?product=P1&product=NO-MATCH",
            headers=auth_headers(login="octocat", github_id="42"),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"]["attempt_ids"] == ["p1"]
        assert body["scope"]["filters"]["products"] == ["NO-MATCH", "P1"]
        assert body["batch"]["display_name"] == "Scoped batch"

    def test_manager_route_rejects_invalid_time_scope(self, client, registry_with_owned_job):
        resp = client.get(
            "/api/jobs/owned-job/manager?start_time=not-a-time",
            headers=auth_headers(login="octocat", github_id="42"),
        )

        assert resp.status_code == 400
        assert "Invalid ISO timestamp" in resp.json()["detail"]

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/jobs/owned-job/status"),
            ("POST", "/api/jobs/owned-job/stop"),
            ("GET", "/api/jobs/owned-job/units"),
            ("GET", "/api/jobs/owned-job/clusters"),
            ("GET", "/api/jobs/owned-job/debug-packet?unit_id=u1"),
            ("POST", "/api/jobs/owned-job/units/u1/reanalyze"),
            ("GET", "/api/jobs/owned-job/manager"),
            ("GET", "/api/jobs/owned-job/comparison"),
        ],
    )
    def test_legacy_jobs_stay_private(self, client, registry_with_owned_job, method, path):
        resp = client.request(
            method,
            path.replace("owned-job", "legacy-job"),
            headers=auth_headers(login="hubot", github_id="99"),
        )

        assert resp.status_code == 404

    def test_non_admin_owner_cannot_clear_job_cache(self, client, registry_with_owned_job):
        resp = client.delete(
            "/api/jobs/owned-job/cache",
            headers=auth_headers(login="octocat", github_id="42"),
        )
        assert resp.status_code == 403

    def test_admin_owner_can_clear_job_cache(self, client, registry_with_owned_job):
        resp = client.delete(
            "/api/jobs/owned-job/cache",
            headers=admin_auth_headers(),
        )
        assert resp.status_code == 200

    def test_two_browsers_and_admin_see_same_workspace(self, client, registry_with_owned_job):
        client.cookies.clear()
        second = TestClient(client.app)
        assert client.get("/api/jobs/owned-job/status").status_code == 200
        assert second.get("/api/jobs/owned-job/status").status_code == 200
        guest = second.get("/api/jobs").json()["items"]
        elevated = client.get("/api/jobs", headers=admin_auth_headers()).json()["items"]
        assert [item["job_id"] for item in guest] == [item["job_id"] for item in elevated] == ["owned-job"]


class TestAnalysisCacheDeletionAdminOnly:
    @pytest.mark.parametrize("path", ["/api/cache/analysis/cache-key", "/api/jobs/cache-job/cache"])
    def test_only_admin_reaches_cache_deletion(self, client, tmp_path, path):
        from app.dependencies import get_analysis_cache, get_registry
        from app.job_registry import JobRegistry
        from app.models import UnitRecord

        class TestCache:
            def __init__(self):
                self.keys = {"cache-key"}

            def delete_entry(self, key, *, actor_id=None, actor_is_admin=False):
                assert actor_id == SHARED_WORKSPACE_ID
                assert actor_is_admin is True
                self.keys.remove(key)
                return True

        cache = TestCache()
        registry = JobRegistry()
        job = registry.create("cache-job", str(tmp_path / "cache-job"), owner_id=SHARED_WORKSPACE_ID)
        job.records = [UnitRecord(unit_id="unit-1", result="FAIL", analysis_cache_key="cache-key")]
        client.app.dependency_overrides[get_registry] = lambda: registry
        client.app.dependency_overrides[get_analysis_cache] = lambda: cache
        client.cookies.clear()
        try:
            assert client.delete(path).status_code == 403
            assert cache.keys == {"cache-key"}
            assert job.records[0].analysis_cache_key == "cache-key"
            assert client.delete(path, headers=admin_auth_headers()).status_code == 200
            assert cache.keys == set()
        finally:
            client.app.dependency_overrides.pop(get_registry, None)
            client.app.dependency_overrides.pop(get_analysis_cache, None)

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
        client.cookies.clear()
        from app.config import settings
        previous_work_dir = settings.WORK_DIR
        settings.WORK_DIR = str(tmp_path / "uploads")
        client.app.dependency_overrides[get_registry] = lambda: reg
        client.app.dependency_overrides[get_orchestrator] = lambda: NoopOrchestrator()
        try:
            resp = client.post(
                "/api/upload",
                files={"files": ("test.txt", io.BytesIO(b"data"), "text/plain")},
                data={"paths": ["test.txt"], "force_refresh": "true"},
            )
        finally:
            settings.WORK_DIR = previous_work_dir
            client.app.dependency_overrides.pop(get_registry, None)
            client.app.dependency_overrides.pop(get_orchestrator, None)

        assert resp.status_code == 200
        job = reg.get(resp.json()["job_id"])
        assert job is not None
        assert job.force_refresh is True
        assert job.owner_id == SHARED_WORKSPACE_ID
        assert job.batch.display_name == "test.txt"
        assert job.batch.source_file_count == 1
        assert job.batch.source_zip_count == 0


class TestSharedWorkspaceSecurity:
    def test_weak_signing_configuration_cannot_grant_admin(self, client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "JWT_SECRET", "dev-only-change-me")
        client.cookies.clear()
        response = client.post("/api/auth/admin/login", json={
            "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD,
        })
        assert response.status_code == 503
        assert client.get("/api/me", headers=admin_auth_headers()).json()["is_admin"] is False

    def test_tampered_admin_cookie_is_read_only_for_maintenance(self, client):
        import jwt
        import time

        token = jwt.encode({
            "sub": SHARED_WORKSPACE_ID, "login": "admin", "amr": "admin_shared",
            "is_admin": True, "exp": int(time.time()) + 3600,
        }, "not-the-server-secret-" * 3, algorithm="HS256")
        assert client.delete("/api/cache/analysis/key", headers={"Cookie": f"session={token}"}).status_code == 403

    @pytest.mark.parametrize("path", ["/api/cache/analysis/key", "/api/jobs/shared/cache", "/api/knowledge"])
    def test_guest_cannot_delete_maintenance_data(self, client, path):
        client.cookies.clear()
        assert client.delete(path).status_code == 403

    def test_expired_admin_session_keeps_workspace_but_denies_cleanup(self, client):
        import jwt
        import time
        from app.config import settings

        token = jwt.encode({
            "sub": SHARED_WORKSPACE_ID, "login": settings.ADMIN_USERNAME,
            "amr": "admin_shared", "is_admin": True, "exp": int(time.time()) - 1,
        }, settings.JWT_SECRET, algorithm="HS256")
        headers = {"Cookie": f"session={token}"}
        assert client.get("/api/me", headers=headers).json()["is_admin"] is False
        assert client.delete("/api/cache/analysis/key", headers=headers).status_code == 403

    @pytest.mark.parametrize("headers", [{"Origin": "https://untrusted.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}])
    def test_cross_site_mutations_are_rejected(self, client, headers):
        response = client.post("/api/upload", headers=headers)
        assert response.status_code == 403

    def test_allowed_frontend_origin_can_submit_requests(self, client):
        from app.config import settings
        response = client.post("/api/upload", headers={"Origin": settings.FRONTEND_URL})
        assert response.status_code == 422
