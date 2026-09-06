"""One-time, restartable migration from the legacy SQLite store.

The script is deliberately separate from application startup.  It uses the
server-only Supabase key and refuses to overwrite an existing differing row.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import username_to_internal_email  # noqa: E402,F401


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"')


def sqlite_path(value: str | None) -> Path:
    raw = value or os.getenv("SQLITE_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///./data/sif_sentinel.db")
    raw = raw.removeprefix("sqlite:///")
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            pass
        return {"model_mode": "Unknown legacy analysis", "legacy_raw_analysis": value, "screening": {"decision": "UNKNOWN", "failure_reason": "analysis_json_invalid"}}
    return {"model_mode": "Unknown legacy analysis", "screening": {"decision": "UNKNOWN", "failure_reason": "analysis_missing"}}


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def canonical_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class SupabaseMigrationClient:
    def __init__(self) -> None:
        self.base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        self.key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not self.base or not self.key:
            raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY are required.")

    def request(self, method: str, table: str, *, params: dict[str, Any] | None = None, payload: Any = None, prefer: str | None = None) -> Any:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        response = httpx.request(method, f"{self.base}/rest/v1/{table}", params=params, json=payload, headers=headers, timeout=30)
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase request failed ({response.status_code})")
        return response.json() if response.content else None

    def existing(self, table: str, column: str, value: Any) -> list[dict[str, Any]]:
        return self.request("GET", table, params={column: f"eq.{value}", "select": "*"}) or []

    def insert(self, table: str, payload: dict[str, Any]) -> None:
        self.request("POST", table, payload=payload, prefer="return=minimal")

    def rpc(self, function: str, payload: dict[str, Any] | None = None) -> Any:
        return self.request("POST", f"rpc/{function}", payload=payload or {}, prefer="return=minimal")

    def all_rows(self, table: str, select: str = "*") -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.request("GET", table, params={"select": select, "limit": 500, "offset": offset}) or []
            result.extend(page)
            if len(page) < 500:
                return result
            offset += 500


def incident_payload(row: sqlite3.Row) -> dict[str, Any]:
    analysis = json_object(row["analysis"])
    provenance = analysis.get("provenance") or {}
    source_id = row["source_id"] if "source_id" in row.keys() else provenance.get("source_report_id")
    return {"id": row["id"], "report_date": row["report_date"], "site": row["site"], "activity": row["activity"], "narrative": row["narrative"], "source": row["source"], "source_id": source_id, "normalized_narrative": " ".join((row["narrative"] or "").casefold().split()), "sif_probability": row["sif_probability"], "risk": row["risk"], "high_potential": bool_or_none(row["high_potential"]), "sif_potential": bool_or_none(row["sif_potential"]), "sif_label_status": row["sif_label_status"], "analysis": analysis, "review_status": row["review_status"], "reviewer": row["reviewer"], "review_comment": row["review_comment"], "created_at": canonical_timestamp(row["created_at"]), "report_type": row["report_type"] or "Unspecified", "import_batch_id": row["import_batch_id"]}


def comparable_incident(row: dict[str, Any], payload: dict[str, Any]) -> bool:
    fields = ("id", "report_date", "site", "activity", "narrative", "source", "source_id", "sif_probability", "risk", "high_potential", "sif_potential", "sif_label_status", "analysis", "review_status", "reviewer", "review_comment", "created_at", "report_type", "import_batch_id")
    return all((canonical_timestamp(row.get(field)) if field == "created_at" else row.get(field)) == (canonical_timestamp(payload.get(field)) if field == "created_at" else payload.get(field)) for field in fields)


def alert_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "title": row["title"], "detail": row["detail"], "severity": row["severity"], "status": row["status"], "site": row["site"], "created_at": canonical_timestamp(row["created_at"])}


def summary(rows: list[dict[str, Any]], history_count: int) -> dict[str, Any]:
    return {"total_reports": len(rows), "status_counts": dict(Counter(str(row.get("review_status")) for row in rows)), "sif_disposition_counts": {"true": sum(row.get("sif_potential") is True or row.get("sif_potential") == 1 for row in rows), "false": sum(row.get("sif_potential") is False or row.get("sif_potential") == 0 for row in rows), "null": sum(row.get("sif_potential") is None for row in rows)}, "review_history_count": history_count}


def migrate(source: Path, client: SupabaseMigrationClient) -> dict[str, int]:
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    incidents = connection.execute("SELECT * FROM incidents ORDER BY id").fetchall()
    history = connection.execute("SELECT * FROM review_history ORDER BY id").fetchall()
    try:
        alerts = connection.execute("SELECT * FROM alerts ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        alerts = []
    source_summary = summary([dict(row) for row in incidents], len(history))
    counts = Counter(read=len(incidents), inserted=0, skipped=0, failed=0, history_read=len(history), history_inserted=0, history_skipped=0, history_failed=0, alerts_read=len(alerts), alerts_inserted=0, alerts_skipped=0, alerts_failed=0)
    for row in incidents:
        payload = incident_payload(row)
        try:
            existing = client.existing("incidents", "id", row["id"])
            if existing:
                if not comparable_incident(existing[0], payload):
                    raise RuntimeError(f"Existing incident differs: {row['id']}")
                counts["skipped"] += 1
            else:
                client.insert("incidents", payload); counts["inserted"] += 1
        except Exception as error:
            counts["failed"] += 1; print(f"FAILED incident {row['id']}: {error}")
    for row in history:
        payload = {"id": row["id"], "incident_id": row["incident_id"], "outcome": row["outcome"], "reviewer": row["reviewer"], "comment": row["comment"], "timestamp": canonical_timestamp(row["timestamp"]), "previous_outcome": row["previous_outcome"], "new_outcome": row["new_outcome"], "screening_version": row["screening_version"]}
        try:
            existing = client.existing("review_history", "id", row["id"])
            if existing:
                if any((canonical_timestamp(existing[0].get(field)) if field == "timestamp" else existing[0].get(field)) != (canonical_timestamp(payload.get(field)) if field == "timestamp" else payload.get(field)) for field in payload):
                    raise RuntimeError(f"Existing review history row differs: {row['id']}")
                counts["history_skipped"] += 1
            else:
                client.insert("review_history", payload); counts["history_inserted"] += 1
        except Exception as error:
            counts["history_failed"] += 1; print(f"FAILED review history {row['id']}: {error}")
    for row in alerts:
        payload = alert_payload(row)
        try:
            existing = client.existing("alerts", "id", row["id"])
            if existing:
                if any((canonical_timestamp(existing[0].get(field)) if field == "created_at" else existing[0].get(field)) != (canonical_timestamp(payload.get(field)) if field == "created_at" else payload.get(field)) for field in payload):
                    raise RuntimeError(f"Existing alert differs: {row['id']}")
                counts["alerts_skipped"] += 1
            else:
                client.insert("alerts", payload); counts["alerts_inserted"] += 1
        except Exception as error:
            counts["alerts_failed"] += 1; print(f"FAILED alert {row['id']}: {error}")
    if history:
        try:
            client.rpc("sync_review_history_identity")
        except Exception as error:
            counts["history_failed"] += 1; print(f"FAILED review history sequence sync: {error}")
    connection.close()
    print("Migration counts:", " ".join(f"{key}={value}" for key, value in counts.items()))
    try:
        migrated_incidents = client.all_rows("incidents", "review_status,sif_potential")
        migrated_history = client.all_rows("review_history", "id")
        destination_summary = summary(migrated_incidents, len(migrated_history))
        print("Source comparison:", json.dumps(source_summary, sort_keys=True))
        print("Supabase comparison:", json.dumps(destination_summary, sort_keys=True))
        if source_summary["total_reports"] > destination_summary["total_reports"] or source_summary["review_history_count"] > destination_summary["review_history_count"]:
            print("WARNING: Supabase totals are below the SQLite source; inspect failed rows before cutover.")
    except Exception as error:
        print(f"Comparison unavailable: {error}")
    return dict(counts)


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", help="SQLite URL or path; defaults to SQLITE_DATABASE_URL or DATABASE_URL")
    args = parser.parse_args()
    source = sqlite_path(args.sqlite)
    if not source.exists():
        raise SystemExit(f"SQLite database not found: {source}")
    counts = migrate(source, SupabaseMigrationClient())
    if any(counts.get(key, 0) for key in ("failed", "history_failed", "alerts_failed")):
        raise SystemExit("Migration completed with failures; inspect the failed rows above.")


if __name__ == "__main__":
    main()
