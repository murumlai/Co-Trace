"""Pluggable auth. Placeholder implementation now; swap for SSO/AD later by
providing another AuthProvider and binding it in `get_auth()`."""
from __future__ import annotations

import secrets
import time
from typing import Protocol

from fastapi import Header, HTTPException, status

from .config import settings


class AuthProvider(Protocol):
    def login(self, username: str, password: str) -> str: ...
    def verify(self, token: str) -> str: ...


class SimpleAuth:
    """Hardcoded-credential + in-memory bearer token. Placeholder only."""

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}

    def login(self, username: str, password: str) -> str:
        ok_user = secrets.compare_digest(username, settings.APP_USERNAME)
        ok_pass = secrets.compare_digest(password, settings.APP_PASSWORD)
        if not (ok_user and ok_pass):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        token = secrets.token_urlsafe(32)
        self._tokens[token] = (username, time.time())
        return token

    def verify(self, token: str) -> str:
        entry = self._tokens.get(token)
        if not entry:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
        username, created = entry
        if time.time() - created > settings.SESSION_TTL_S:
            self._tokens.pop(token, None)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
        return username


_auth: AuthProvider = SimpleAuth()


def get_auth() -> AuthProvider:
    return _auth


def require_user(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: validate the Bearer token, return the username."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return _auth.verify(token)
