from __future__ import annotations

from app.services.database import SupabaseDatabase


def make_database(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-test-key")
    return SupabaseDatabase()


def test_complete_incident_reads_are_paginated(monkeypatch):
    database = make_database(monkeypatch)
    calls = []

    def request(method, table, *, params=None, payload=None, prefer=None):
        calls.append(params)
        offset = params.get("offset", 0)
        return ([{"id": str(index)} for index in range(offset, offset + 500)]
                if offset == 0 else [{"id": "500"}])

    monkeypatch.setattr(database, "_request", request)
    rows = database.list_incidents()
    assert len(rows) == 501
    assert calls[0]["limit"] == 500 and calls[0]["offset"] == 0
    assert calls[1]["limit"] == 500 and calls[1]["offset"] == 500


def test_review_uses_atomic_rpc(monkeypatch):
    database = make_database(monkeypatch)
    rpc_calls = []

    monkeypatch.setattr(database, "_request", lambda method, table, **kwargs: [{"id": "ANL-1", "review_status": "Pending"}])

    def rpc(function, payload):
        rpc_calls.append((function, payload))

    monkeypatch.setattr(database, "_rpc", rpc)
    result = database.apply_review("ANL-1", {
        "status": "Reviewed", "reviewer": "Reviewer", "comment": "Confirmed",
        "sif_potential": True, "label_status": "manual_reviewed",
        "outcome": "Confirm SIF", "timestamp": "2026-09-07T00:00:00+00:00",
        "previous_outcome": None, "screening_version": "sif-v0.1",
        "reviewer_user_id": "00000000-0000-0000-0000-000000000001",
    })
    assert result["id"] == "ANL-1"
    assert rpc_calls[0][0] == "apply_incident_review"
    assert rpc_calls[0][1]["p_incident_id"] == "ANL-1"
    assert rpc_calls[0][1]["p_reviewer_user_id"].endswith("0001")


def test_batch_insert_sends_one_bulk_request(monkeypatch):
    database = make_database(monkeypatch)
    calls = []
    monkeypatch.setattr(database, "_request", lambda method, table, **kwargs: calls.append((method, table, kwargs)) or None)
    database.insert_incidents_batch([{"id": "A", "narrative": "first"}, {"id": "B", "narrative": "second"}])
    assert len(calls) == 1 and calls[0][0:2] == ("POST", "incidents")
    assert [row["id"] for row in calls[0][2]["payload"]] == ["A", "B"]
