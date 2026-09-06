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
