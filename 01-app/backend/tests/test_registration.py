from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("SIF_TEST_AUTH_BYPASS", "1")
os.environ.setdefault("SIF_ENVIRONMENT", "test")
test_dir = Path(tempfile.mkdtemp(prefix="sif_registration_tests_"))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = f"sqlite:///{(test_dir / 'registration.db').as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.auth import username_to_internal_email  # noqa: E402


client = TestClient(main.app)


class FakeDatabase:
    def __init__(self, existing: dict | None = None, fail_profile: bool = False):
        self.existing = existing
        self.fail_profile = fail_profile
        self.profiles: list[dict] = []

    def get_profile_by_username(self, username: str):
        return self.existing if self.existing and self.existing["username"] == username else None

    def create_profile(self, profile: dict):
        if self.fail_profile:
            raise RuntimeError("profile unavailable")
        self.profiles.append(profile)
        return profile


def reset_attempts():
    main._registration_attempts.clear()
    os.environ["REGISTRATION_RATE_LIMIT"] = "20"


def test_registration_is_public_creates_member_and_ignores_client_role(monkeypatch):
    reset_attempts()
    database = FakeDatabase()
    created: list[dict] = []
    monkeypatch.setattr(main, "get_database", lambda: database)
    monkeypatch.setattr(main, "create_auth_user", lambda **kwargs: created.append(kwargs) or {"id": "auth-1", "email": kwargs["email"]})
    response = client.post("/auth/register", json={"user_id": "  New.User ", "display_name": "New User", "password": "StrongPassword1!", "password_confirmation": "StrongPassword1!", "role": "admin"})
    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert created[0]["email"] == username_to_internal_email("new.user")
    assert database.profiles[-1]["role"] == "member"


def test_registration_validation_rejects_invalid_user_id_weak_and_mismatched_passwords():
    reset_attempts()
    assert client.post("/auth/register", json={"user_id": "bad id", "display_name": "User", "password": "short", "password_confirmation": "short"}).status_code == 422
    assert client.post("/auth/register", json={"user_id": "valid-user", "display_name": "User", "password": "StrongPassword1!", "password_confirmation": "DifferentPassword1!"}).status_code == 422


def test_duplicate_user_id_is_generic_conflict(monkeypatch):
    reset_attempts()
    database = FakeDatabase({"username": "existing-user", "id": "auth-existing"})
    monkeypatch.setattr(main, "get_database", lambda: database)
    response = client.post("/auth/register", json={"user_id": "EXISTING-USER", "display_name": "User", "password": "StrongPassword1!", "password_confirmation": "StrongPassword1!"})
    assert response.status_code == 409 and response.json()["detail"] == "That User ID is already registered."


def test_profile_failure_rolls_back_auth_user(monkeypatch):
    reset_attempts()
    database = FakeDatabase(fail_profile=True)
    deleted: list[str] = []
    monkeypatch.setattr(main, "get_database", lambda: database)
    monkeypatch.setattr(main, "create_auth_user", lambda **kwargs: {"id": "auth-partial", "email": kwargs["email"]})
    monkeypatch.setattr(main, "delete_auth_user", deleted.append)
    response = client.post("/auth/register", json={"user_id": "partial-user", "display_name": "User", "password": "StrongPassword1!", "password_confirmation": "StrongPassword1!"})
    assert response.status_code == 500 and response.json()["detail"] == "Registration could not be completed."
    assert deleted == ["auth-partial"]


def test_registration_is_the_only_public_application_route(monkeypatch):
    reset_attempts()
    monkeypatch.setattr(main, "reviewer_for_request", lambda request: None)
    assert client.post("/auth/register", json={"user_id": "public-user", "display_name": "User", "password": "StrongPassword1!", "password_confirmation": "StrongPassword1!"}).status_code in {500, 409}
    assert client.get("/dashboard/summary").status_code == 401


def test_member_cannot_submit_review(monkeypatch):
    monkeypatch.setattr(main, "reviewer_for_request", lambda request: main.AuthenticatedUser("member-1", "member", "Member", "member"))
    assert client.post("/reviews/unknown", json={"outcome": "Confirm SIF", "reviewer": "Member"}).status_code == 403


def test_registration_rate_limit_is_enforced(monkeypatch):
    reset_attempts()
    os.environ["REGISTRATION_RATE_LIMIT"] = "2"
    monkeypatch.setattr(main, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(main, "create_auth_user", lambda **kwargs: {"id": "auth-rate", "email": kwargs["email"]})
    payload = {"user_id": "rate-user", "display_name": "User", "password": "StrongPassword1!", "password_confirmation": "StrongPassword1!"}
    assert client.post("/auth/register", json=payload).status_code == 201
    payload["user_id"] = "rate-user-two"
    assert client.post("/auth/register", json=payload).status_code == 201
    payload["user_id"] = "rate-user-three"
    assert client.post("/auth/register", json=payload).status_code == 429
