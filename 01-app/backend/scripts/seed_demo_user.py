"""Idempotently provision the demo Supabase Auth user and application profile.

Run this once after applying the SQL migration.  It is intentionally a
server-side script because it uses SUPABASE_SECRET_KEY.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import username_to_internal_email  # noqa: E402


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def request(method: str, url: str, key: str, **kwargs: Any) -> httpx.Response:
    headers = {"apikey": key, "Authorization": f"Bearer {key}", **kwargs.pop("headers", {})}
    response = httpx.request(method, url, headers=headers, timeout=20, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase request failed ({response.status_code})")
    return response


def main() -> None:
    if os.getenv("ENABLE_DEMO_USER", "true").strip().lower() not in {"1", "true", "yes"}:
        print("Demo user bootstrap disabled (ENABLE_DEMO_USER is false).")
        return
    base = required("SUPABASE_URL").rstrip("/")
    key = required("SUPABASE_SECRET_KEY")
    username = os.getenv("DEMO_USERNAME", "test")
    password = os.getenv("DEMO_PASSWORD", "test123")
    normalized = username_to_internal_email(username).split("@", 1)[0]
    email = username_to_internal_email(username)
    users_response = request("GET", f"{base}/auth/v1/admin/users", key, params={"page": 1, "per_page": 1000})
    body = users_response.json()
    users = body.get("users", body if isinstance(body, list) else [])
    auth_user = next((user for user in users if str(user.get("email", "")).casefold() == email.casefold()), None)
    if auth_user is None:
        auth_user = request("POST", f"{base}/auth/v1/admin/users", key, json={"email": email, "password": password, "email_confirm": True, "user_metadata": {"username": normalized}}).json()
        print("Created demo Auth user.")
    else:
        print("Demo Auth user already exists; password was not changed.")
    user_id = str(auth_user["id"])
    profile = {"id": user_id, "username": normalized, "display_name": "Demo Reviewer", "role": "reviewer"}
    request("POST", f"{base}/rest/v1/profiles", key, json=profile, headers={"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    print(f"Profile ready for User ID: {normalized}")


if __name__ == "__main__":
    main()
