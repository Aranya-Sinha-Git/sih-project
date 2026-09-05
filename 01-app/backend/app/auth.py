"""Small, server-side bearer-token authentication for the prototype API."""
from __future__ import annotations

import hmac
import os
from fastapi import Request


def local_demo_enabled() -> bool:
    return os.getenv("SIF_LOCAL_DEMO", "").strip().lower() in {"1", "true", "yes"}


def configured_tokens() -> dict[str, str]:
    raw = os.getenv("SIF_AUTH_TOKENS", "").strip()
    if not raw:
        return {}
    # JSON is convenient for deployment; token=name is convenient for a local
    # secret store.  Neither value is ever sent to the browser by the server.
    if raw.startswith("{"):
        import json
        parsed = json.loads(raw)
        return {str(token): str(name) for token, name in parsed.items() if str(token) and str(name)}
    result: dict[str, str] = {}
    for entry in raw.split(","):
        token, separator, name = entry.partition("=")
        if separator and token.strip() and name.strip():
            result[token.strip()] = name.strip()
    return result


def reviewer_for_request(request: Request) -> str | None:
    if local_demo_enabled():
        return None
    authorization = request.headers.get("authorization", "")
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return None
    for token, reviewer in configured_tokens().items():
        if hmac.compare_digest(token, presented):
            return reviewer
    return None


def validate_configuration() -> None:
    if not local_demo_enabled() and not configured_tokens():
        raise RuntimeError(
            "SIF_AUTH_TOKENS must be configured, or SIF_LOCAL_DEMO=1 must be explicitly enabled for loopback demo use."
        )
