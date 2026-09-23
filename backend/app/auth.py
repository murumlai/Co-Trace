"""Shared prototype workspace with signed maintenance sessions."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from jwt import InvalidTokenError

from .config import settings

SHARED_WORKSPACE_ID = "shared-workspace"


@dataclass(frozen=True)
class AuthenticatedUser:
    login: str
    github_id: str
    is_admin: bool = False
    name: str | None = None
    avatar_url: str | None = None

    @property
    def username(self) -> str:
        return self.login


class WorkspaceAuth:
    def create_session_token(self, user: AuthenticatedUser, auth_method: str = "admin_shared") -> str:
        now = int(time.time())
        payload = {
            "sub": user.github_id,
            "login": user.login,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "is_admin": user.is_admin,
            "amr": auth_method,
            "iat": now,
            "exp": now + settings.SESSION_TTL_S,
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

    def authenticate_admin(self, username: str, password: str) -> AuthenticatedUser:
        if not settings.ADMIN_PASSWORD:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Local admin login is not configured")
        if len(settings.JWT_SECRET.encode("utf-8")) < 32:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Admin session signing is not securely configured")
        expected_user = settings.ADMIN_USERNAME or "admin"
        user_ok = secrets.compare_digest(username or "", expected_user)
        pass_ok = secrets.compare_digest(password or "", settings.ADMIN_PASSWORD)
        if not (user_ok and pass_ok):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin credentials")
        return AuthenticatedUser(
            login=expected_user,
            github_id=SHARED_WORKSPACE_ID,
            is_admin=True,
            name="Administrator",
        )

_auth = WorkspaceAuth()


def get_auth() -> WorkspaceAuth:
    return _auth


def require_user(session: str | None = Cookie(default=None, alias=settings.SESSION_COOKIE_NAME)) -> AuthenticatedUser:
    if session and settings.ADMIN_PASSWORD and len(settings.JWT_SECRET.encode("utf-8")) >= 32:
        try:
            payload = jwt.decode(
                session, settings.JWT_SECRET, algorithms=["HS256"],
                options={"require": ["exp", "sub", "login", "amr", "is_admin"]},
            )
            if (
                payload.get("amr") == "admin_shared"
                and payload.get("sub") == SHARED_WORKSPACE_ID
                and payload.get("login") == (settings.ADMIN_USERNAME or "admin")
                and payload.get("is_admin") is True
            ):
                return AuthenticatedUser(
                    login=settings.ADMIN_USERNAME or "admin",
                    github_id=SHARED_WORKSPACE_ID,
                    is_admin=True,
                    name="Administrator",
                )
        except InvalidTokenError:
            pass
    return AuthenticatedUser(
        login=SHARED_WORKSPACE_ID,
        github_id=SHARED_WORKSPACE_ID,
        name="Shared workspace",
    )


def require_admin(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
