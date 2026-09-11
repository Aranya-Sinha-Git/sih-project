"""Supabase Auth verification and the single username-to-email mapping."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx
from fastapi import Request

INTERNAL_AUTH_DOMAIN = "users.sif-sentinel.invalid"
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 64
MAX_DISPLAY_NAME_LENGTH = 120
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    display_name: str
    role: str


def normalize_username(username: str) -> str:
    return " ".join((username or "").strip().casefold().split())


def username_to_internal_email(username: str) -> str:
    normalized = normalize_username(username)
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("User ID must be 3-64 characters and use only letters, numbers, dot, underscore, or hyphen.")
    return f"{normalized}@{INTERNAL_AUTH_DOMAIN}"


def _test_bypass_enabled() -> bool:
    environment = os.getenv("SIF_ENVIRONMENT", "").strip().lower()
    enabled = os.getenv("SIF_TEST_AUTH_BYPASS", "").strip().lower() in {"1", "true", "yes"}
    return enabled and environment in {"test", "testing"}


def reviewer_for_request(request: Request) -> AuthenticatedUser | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        if _test_bypass_enabled():
            return AuthenticatedUser("test-user", "test", "Test Reviewer", "reviewer")
        return None
    if _test_bypass_enabled() and token.strip() == "test-token":
        return AuthenticatedUser("test-user", "test", "Test Reviewer", "reviewer")
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not publishable_key:
        return None
    try:
        response = httpx.get(f"{url}/auth/v1/user", headers={"apikey": publishable_key, "Authorization": f"Bearer {token.strip()}"}, timeout=10)
        if response.status_code != 200:
            return None
        auth_user = response.json(); user_id = str(auth_user.get("id") or "")
        if not user_id:
            return None
        from .services.database import get_database
        profile = get_database().get_profile(user_id)
        if not profile:
            return None
        return AuthenticatedUser(user_id, profile["username"], profile.get("display_name") or profile["username"], profile.get("role") or "member")
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def validate_configuration() -> None:
    if _test_bypass_enabled():
        return
    required = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("Missing required Supabase configuration: " + ", ".join(missing))


class AuthProviderError(RuntimeError):
    """An internal Supabase Auth failure safe to translate into a generic API error."""

    def __init__(self, message: str = "Account registration failed.", *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


def create_auth_user(*, email: str, password: str, username: str, display_name: str) -> dict[str, str]:
    """Create an Auth user with the server-only Supabase administrator key."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret_key:
        raise AuthProviderError()
    try:
        response = httpx.post(
            f"{url}/auth/v1/admin/users",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"},
            json={"email": email, "password": password, "email_confirm": True, "user_metadata": {"username": username, "display_name": display_name}},
            timeout=20,
        )
    except httpx.HTTPError as error:
        raise AuthProviderError() from error
    if response.status_code in {409, 422}:
        raise AuthProviderError(conflict=True)
    if response.status_code >= 400:
        raise AuthProviderError()
    try:
        payload = response.json()
        user_id = str(payload.get("id") or "")
    except (ValueError, AttributeError):
        user_id = ""
    if not user_id:
        raise AuthProviderError()
    return {"id": user_id, "email": email}


def delete_auth_user(user_id: str) -> None:
    """Best-effort rollback for a registration whose profile could not be created."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret_key:
        return
    try:
        httpx.delete(
            f"{url}/auth/v1/admin/users/{user_id}",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            timeout=20,
        )
    except httpx.HTTPError:
        return
