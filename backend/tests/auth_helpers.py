"""Test helpers for cookie-session authentication."""
from __future__ import annotations

from app.auth import AuthenticatedUser, get_auth
from app.config import settings


def auth_headers(login: str = "octocat", github_id: str = "42", is_admin: bool = False) -> dict[str, str]:
    token = get_auth().create_session_token(
        AuthenticatedUser(login=login, github_id=github_id, is_admin=is_admin)
    )
    return {"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"}


def admin_auth_headers(login: str = "admin", github_id: str = "1") -> dict[str, str]:
    if login not in settings.GITHUB_ADMIN_USERS:
        settings.GITHUB_ADMIN_USERS = [*settings.GITHUB_ADMIN_USERS, login]
    return auth_headers(login=login, github_id=github_id, is_admin=True)
