"""Supabase Auth verification and the single username-to-email mapping."""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from fastapi import Request

INTERNAL_AUTH_DOMAIN = "users.sif-sentinel.invalid"


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
    if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in normalized):
        raise ValueError("User ID may contain letters, numbers, dot, underscore, or hyphen.")
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
        return AuthenticatedUser(user_id, profile["username"], profile.get("display_name") or profile["username"], profile.get("role") or "demo")
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def validate_configuration() -> None:
    if _test_bypass_enabled():
        return
    required = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("Missing required Supabase configuration: " + ", ".join(missing))
