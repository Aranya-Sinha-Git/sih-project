import os

from fastapi import Request

from app.auth import normalize_username, username_to_internal_email


def test_username_mapping_is_normalized_and_deterministic():
    assert normalize_username("  TEST  ") == "test"
    assert username_to_internal_email("  TEST  ") == "test@users.sif-sentinel.invalid"
    assert username_to_internal_email("test") == username_to_internal_email(" TEST ")


def test_username_mapping_rejects_email_like_or_unsafe_input():
    try:
        username_to_internal_email("user@example.com")
    except ValueError:
        pass
    else:
        raise AssertionError("email-shaped User IDs must not be accepted")


def test_missing_auth_is_not_accepted(monkeypatch):
    monkeypatch.delenv("SIF_TEST_AUTH_BYPASS", raising=False)
    from app.auth import reviewer_for_request
    scope = {"type": "http", "headers": [], "method": "GET", "path": "/incidents", "query_string": b"", "server": ("test", 80), "scheme": "http", "client": ("test", 1), "root_path": "", "http_version": "1.1"}
    assert reviewer_for_request(Request(scope)) is None


def test_invalid_jwt_is_not_accepted(monkeypatch):
    monkeypatch.delenv("SIF_TEST_AUTH_BYPASS", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "public-test-key")

    class Response:
        status_code = 401

        def json(self):
            return {}

    import app.auth as auth
    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: Response())
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer invalid")], "method": "GET", "path": "/incidents", "query_string": b"", "server": ("test", 80), "scheme": "http", "client": ("test", 1), "root_path": "", "http_version": "1.1"}
    assert auth.reviewer_for_request(Request(scope)) is None


def test_authenticated_request_resolves_profile(monkeypatch):
    monkeypatch.delenv("SIF_TEST_AUTH_BYPASS", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "public-test-key")

    class Response:
        status_code = 200

        def json(self):
            return {"id": "00000000-0000-0000-0000-000000000001"}

    import app.auth as auth
    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.services.database.get_database", lambda: type("Database", (), {"get_profile": lambda self, user_id: {"username": "test", "display_name": "Test Reviewer", "role": "reviewer"}})())
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer valid")], "method": "GET", "path": "/incidents", "query_string": b"", "server": ("test", 80), "scheme": "http", "client": ("test", 1), "root_path": "", "http_version": "1.1"}
    user = auth.reviewer_for_request(Request(scope))
    assert user and user.id.endswith("0001") and user.username == "test" and user.role == "reviewer"
