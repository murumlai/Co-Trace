"""Test helpers for cookie-session authentication."""
from __future__ import annotations

from app.auth import AuthenticatedUser, SHARED_WORKSPACE_ID, get_auth
from app.config import settings


def auth_headers(login: str = "octocat", github_id: str = "42", is_admin: bool = False) -> dict[str, str]:
    token = get_auth().create_session_token(
        AuthenticatedUser(login=login, github_id=github_id, is_admin=is_admin),
        auth_method="github",
    )
    return {"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"}


def admin_auth_headers(login: str = "admin", github_id: str = "1") -> dict[str, str]:
    token = get_auth().create_session_token(
        AuthenticatedUser(login=login, github_id=SHARED_WORKSPACE_ID, is_admin=True),
        auth_method="admin_shared",
    )
    return {"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"}
