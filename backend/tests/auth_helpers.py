"""Test helpers for cookie-session authentication."""
from __future__ import annotations

from app.auth import AuthenticatedUser, get_auth
from app.config import settings


def auth_headers(login: str = "admin", github_id: str = "1", is_admin: bool = True) -> dict[str, str]:
    token = get_auth().create_session_token(
        AuthenticatedUser(login=login, github_id=github_id, is_admin=is_admin)
    )
    return {"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"}
