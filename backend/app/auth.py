"""GitHub OAuth and signed session-cookie authentication."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from jwt import InvalidTokenError

from .config import settings


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


class GitHubOAuthAuth:
    def new_state(self) -> str:
        return secrets.token_urlsafe(32)

    def authorize_url(self, state: str) -> str:
        if not settings.GITHUB_CLIENT_ID:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GitHub OAuth is not configured")
        query = urlencode(
            {
                "client_id": settings.GITHUB_CLIENT_ID,
                "redirect_uri": settings.GITHUB_CALLBACK_URL,
                "scope": "read:user",
                "state": state,
                "allow_signup": "false",
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def authenticate_code(self, code: str) -> AuthenticatedUser:
        token = await self.exchange_code(code)
        payload = await self.fetch_github_user(token)
        return self.user_from_github_payload(payload)

    async def exchange_code(self, code: str) -> str:
        if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GitHub OAuth is not configured")
        async with httpx.AsyncClient(timeout=settings.GITHUB_OAUTH_TIMEOUT_S) as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.GITHUB_CALLBACK_URL,
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub token exchange failed")
        data = response.json()
        if data.get("error"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, data.get("error_description") or "GitHub token exchange failed")
        access_token = data.get("access_token")
        if not access_token:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub token response did not include an access token")
        return str(access_token)

    async def fetch_github_user(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.GITHUB_OAUTH_TIMEOUT_S) as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub identity lookup failed")
        return response.json()

    def user_from_github_payload(self, payload: dict[str, Any]) -> AuthenticatedUser:
        login = str(payload.get("login") or "").strip()
        github_id = str(payload.get("id") or "").strip()
        if not login or not github_id:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub identity response was incomplete")
        return AuthenticatedUser(
            login=login,
            github_id=github_id,
            is_admin=self.is_admin(login),
            name=payload.get("name"),
            avatar_url=payload.get("avatar_url"),
        )

    def create_session_token(self, user: AuthenticatedUser) -> str:
        now = int(time.time())
        payload = {
            "sub": user.github_id,
            "login": user.login,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "is_admin": user.is_admin,
            "iat": now,
            "exp": now + settings.SESSION_TTL_S,
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

    def verify_session_token(self, token: str) -> AuthenticatedUser:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        except InvalidTokenError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc
        login = str(payload.get("login") or "").strip()
        github_id = str(payload.get("sub") or "").strip()
        if not login or not github_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
        return AuthenticatedUser(
            login=login,
            github_id=github_id,
            is_admin=self.is_admin(login),
            name=payload.get("name"),
            avatar_url=payload.get("avatar_url"),
        )

    def is_admin(self, login: str) -> bool:
        admins = {item.strip().lower() for item in settings.GITHUB_ADMIN_USERS if item.strip()}
        return login.lower() in admins


_auth = GitHubOAuthAuth()


def get_auth() -> GitHubOAuthAuth:
    return _auth


def require_user(session: str | None = Cookie(default=None, alias=settings.SESSION_COOKIE_NAME)) -> AuthenticatedUser:
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing session cookie")
    return _auth.verify_session_token(session)


def require_admin(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
