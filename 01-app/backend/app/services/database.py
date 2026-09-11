"""Persistence boundary for SIF Sentinel.

Supabase is the production backend.  The small SQLite implementation is kept
only for the existing hermetic test suite and explicit legacy migration work;
it is never selected when Supabase server configuration is present.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import httpx


INCIDENT_COLUMNS = (
    "id", "report_date", "site", "activity", "narrative", "source",
    "source_id", "normalized_narrative", "sif_probability", "risk",
    "high_potential", "sif_potential", "sif_label_status", "analysis",
    "review_status", "reviewer", "review_comment", "created_at",
    "created_by_user_id", "report_type", "import_batch_id",
)


def _sqlite_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    raw = os.getenv("DATABASE_URL", "sqlite:///./data/sif_sentinel.db")
    raw = raw.removeprefix("sqlite:///")
    path = Path(raw) if Path(raw).is_absolute() else root / raw
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = root / "data" / "sif_sentinel.seed.db"
    if raw == "data/sif_sentinel.db" and not path.exists() and seed.exists():
        import shutil
        shutil.copy2(seed, path)
    return path


def supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_SECRET_KEY", "").strip())


def sqlite_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(_sqlite_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_sqlite() -> None:
    connection = sqlite_connection()
    connection.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, report_date TEXT, site TEXT, activity TEXT, narrative TEXT, source TEXT, sif_probability REAL, risk TEXT, high_potential INTEGER, sif_potential INTEGER, sif_label_status TEXT, analysis TEXT, review_status TEXT, reviewer TEXT, review_comment TEXT, created_at TEXT, report_type TEXT, import_batch_id TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY,title TEXT,detail TEXT,severity TEXT,status TEXT,site TEXT,created_at TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS review_history (id INTEGER PRIMARY KEY AUTOINCREMENT,incident_id TEXT,outcome TEXT,reviewer TEXT,reviewer_user_id TEXT,comment TEXT,timestamp TEXT,previous_outcome TEXT,new_outcome TEXT,screening_version TEXT)")
    incident_columns = {row["name"] for row in connection.execute("PRAGMA table_info(incidents)").fetchall()}
    for column in ("source_id", "normalized_narrative", "created_by_user_id"):
        if column not in incident_columns:
            connection.execute(f"ALTER TABLE incidents ADD COLUMN {column} TEXT")
    history_columns = {row["name"] for row in connection.execute("PRAGMA table_info(review_history)").fetchall()}
    if "reviewer_user_id" not in history_columns:
        connection.execute("ALTER TABLE review_history ADD COLUMN reviewer_user_id TEXT")
    connection.commit()
    connection.close()


class DatabaseError(RuntimeError):
    pass


class SQLiteDatabase:
    kind = "sqlite-test"

    def __init__(self) -> None:
        init_sqlite()

    def healthcheck(self) -> dict[str, str]:
        connection = sqlite_connection()
        try:
            connection.execute("SELECT 1").fetchone()
            return {"status": "READY"}
        finally:
            connection.close()

    @staticmethod
    def _decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        if isinstance(result.get("analysis"), str):
            try:
                result["analysis"] = json.loads(result["analysis"])
            except json.JSONDecodeError:
                # Keep the original string available to the legacy reader.
                result["analysis"] = result["analysis"]
        return result

    def list_incidents(self) -> list[dict[str, Any]]:
        connection = sqlite_connection()
        try:
            return [self._decode(row) for row in connection.execute("SELECT * FROM incidents ORDER BY report_date DESC, created_at DESC, id DESC").fetchall()]
        finally:
            connection.close()

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        connection = sqlite_connection()
        try:
            row = connection.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
            return self._decode(row) if row else None
        finally:
            connection.close()

    def list_incidents_page(self, *, search: str = "", site: str | None = None, activity: str | None = None, risk: str | None = None, review: str | None = None, source: str | None = None, page: int = 1, page_size: int = 25) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []
        if search.strip():
            like = f"%{search.strip()}%"
            clauses.append("(id LIKE ? OR narrative LIKE ? OR site LIKE ? OR activity LIKE ?)")
            values.extend([like] * 4)
        for column, value in (("site", site), ("activity", activity), ("risk", risk), ("review_status", review), ("source", source)):
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        connection = sqlite_connection()
        try:
            total = connection.execute(f"SELECT COUNT(*) FROM incidents{where}", values).fetchone()[0]
            values.extend([page_size, (page - 1) * page_size])
            rows = connection.execute(f"SELECT * FROM incidents{where} ORDER BY report_date DESC, created_at DESC, id DESC LIMIT ? OFFSET ?", values).fetchall()
            return [self._decode(row) for row in rows], total
        finally:
            connection.close()

    def insert_incident(self, record: dict[str, Any], connection: sqlite3.Connection | None = None) -> None:
        owned = connection is None
        connection = connection or sqlite_connection()
        values = {column: record.get(column) for column in INCIDENT_COLUMNS}
        values["analysis"] = json.dumps(values["analysis"]) if isinstance(values["analysis"], dict) else values["analysis"]
        columns = [column for column in INCIDENT_COLUMNS if column in {row[1] for row in connection.execute("PRAGMA table_info(incidents)").fetchall()}]
        try:
            connection.execute(f"INSERT INTO incidents ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [values[column] for column in columns])
            if owned:
                connection.commit()
        except Exception:
            if owned:
                connection.rollback()
            raise
        finally:
            if owned:
                connection.close()

    def insert_incidents_batch(self, records: list[dict[str, Any]], connection: sqlite3.Connection | None = None) -> None:
        """Insert a batch in one transaction so partial uploads cannot persist."""
        if not records:
            return
        owned = connection is None
        connection = connection or sqlite_connection()
        columns = [column for column in INCIDENT_COLUMNS if column in {row[1] for row in connection.execute("PRAGMA table_info(incidents)").fetchall()}]
        values = []
        for record in records:
            row = {column: record.get(column) for column in columns}
            row["analysis"] = json.dumps(row["analysis"]) if isinstance(row.get("analysis"), dict) else row.get("analysis")
            values.append([row[column] for column in columns])
        try:
            connection.executemany(f"INSERT INTO incidents ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
            if owned:
                connection.commit()
        except Exception:
            if owned:
                connection.rollback()
            raise
        finally:
            if owned:
                connection.close()

    def update_analysis(self, incident_id: str, analysis: dict[str, Any], connection: sqlite3.Connection | None = None) -> None:
        owned = connection is None
        connection = connection or sqlite_connection()
        try:
            connection.execute("UPDATE incidents SET analysis=? WHERE id=?", (json.dumps(analysis), incident_id))
            if owned:
                connection.commit()
        finally:
            if owned:
                connection.close()

    def review_history(self, incident_id: str) -> list[dict[str, Any]]:
        connection = sqlite_connection()
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM review_history WHERE incident_id=? ORDER BY id ASC", (incident_id,)).fetchall()]
        finally:
            connection.close()

    def apply_review(self, incident_id: str, values: dict[str, Any]) -> dict[str, Any]:
        connection = sqlite_connection()
        try:
            connection.execute("UPDATE incidents SET review_status=?,reviewer=?,review_comment=?,sif_potential=?,sif_label_status=? WHERE id=?", (values["status"], values["reviewer"], values["comment"], values["sif_potential"], values["label_status"], incident_id))
            if connection.total_changes == 0:
                raise KeyError(incident_id)
            connection.execute("INSERT INTO review_history (incident_id,outcome,reviewer,reviewer_user_id,comment,timestamp,previous_outcome,new_outcome,screening_version) VALUES (?,?,?,?,?,?,?,?,?)", (incident_id, values["outcome"], values["reviewer"], values.get("reviewer_user_id"), values["comment"], values["timestamp"], values["previous_outcome"], values["outcome"], values["screening_version"]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_incident(incident_id) or {}

    def list_alerts(self) -> list[dict[str, Any]]:
        connection = sqlite_connection()
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()]
        finally:
            connection.close()

    def update_alert(self, alert_id: str, status: str) -> bool:
        connection = sqlite_connection()
        try:
            cursor = connection.execute("UPDATE alerts SET status=? WHERE id=?", (status, alert_id))
            connection.commit()
            return bool(cursor.rowcount)
        finally:
            connection.close()

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        return None

    def get_profile_by_username(self, username: str) -> dict[str, Any] | None:
        return None

    def create_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        raise DatabaseError("Profile storage is unavailable")

    def update_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        raise DatabaseError("Profile storage is unavailable")


class SupabaseDatabase:
    kind = "supabase-postgres"

    def __init__(self) -> None:
        self.base_url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SECRET_KEY"]

    def healthcheck(self) -> dict[str, str]:
        self._request("GET", "incidents", params={"select": "id", "limit": 1})
        return {"status": "READY"}

    def _request(self, method: str, table: str, *, params: dict[str, Any] | None = None, payload: Any = None, prefer: str | None = None) -> Any:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = httpx.request(method, f"{self.base_url}/rest/v1/{table}", params=params, json=payload, headers=headers, timeout=20)
        except httpx.HTTPError as error:
            raise DatabaseError("Supabase database is unavailable") from error
        if response.status_code >= 400:
            raise DatabaseError(f"Supabase database request failed ({response.status_code})")
        if not response.content:
            return None
        return response.json()

    def list_incidents(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page_size = 500
        offset = 0
        while True:
            page = self._request("GET", "incidents", params={"select": "*", "order": "report_date.desc,created_at.desc,id.desc", "limit": page_size, "offset": offset}) or []
            result.extend(page)
            if len(page) < page_size:
                return result
            offset += page_size

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "incidents", params={"id": f"eq.{incident_id}", "select": "*"}) or []
        return rows[0] if rows else None

    def list_incidents_page(self, *, search: str = "", site: str | None = None, activity: str | None = None, risk: str | None = None, review: str | None = None, source: str | None = None, page: int = 1, page_size: int = 25) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"select": "*", "order": "report_date.desc,created_at.desc,id.desc", "limit": page_size, "offset": (page - 1) * page_size}
        if search.strip():
            term = search.strip().replace(",", " ")
            params["or"] = f"(id.ilike.*{term}*,narrative.ilike.*{term}*,site.ilike.*{term}*,activity.ilike.*{term}*)"
        for column, value in (("site", site), ("activity", activity), ("risk", risk), ("review_status", review), ("source", source)):
            if value:
                params[column] = f"eq.{value}"
        headers = {"Prefer": "count=exact"}
        # A single page request gives the normal operations their stable shape.
        rows, content_range = self._request_with_headers("GET", "incidents", params=params, headers_extra=headers)
        rows = rows or []
        total = int((content_range or "*/0").split("/")[-1])
        return rows, total

    def _request_with_headers(self, method: str, table: str, *, params: dict[str, Any], headers_extra: dict[str, str]) -> tuple[Any, str | None]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", **headers_extra}
        try:
            response = httpx.request(method, f"{self.base_url}/rest/v1/{table}", params=params, headers=headers, timeout=20)
        except httpx.HTTPError as error:
            raise DatabaseError("Supabase database is unavailable") from error
        if response.status_code >= 400:
            raise DatabaseError(f"Supabase database request failed ({response.status_code})")
        return (response.json() if response.content else None), response.headers.get("content-range")

    def insert_incident(self, record: dict[str, Any], connection: Any = None) -> None:
        payload = {column: record.get(column) for column in INCIDENT_COLUMNS if column in record}
        self._request("POST", "incidents", payload=payload, prefer="return=minimal")

    def insert_incidents_batch(self, records: list[dict[str, Any]]) -> None:
        payload = [{column: record.get(column) for column in INCIDENT_COLUMNS if column in record} for record in records]
        self._request("POST", "incidents", payload=payload, prefer="return=minimal")

    def update_analysis(self, incident_id: str, analysis: dict[str, Any], connection: Any = None) -> None:
        self._request("PATCH", "incidents", params={"id": f"eq.{incident_id}"}, payload={"analysis": analysis}, prefer="return=minimal")

    def review_history(self, incident_id: str) -> list[dict[str, Any]]:
        return self._request("GET", "review_history", params={"incident_id": f"eq.{incident_id}", "select": "*", "order": "id.asc"}) or []

    def apply_review(self, incident_id: str, values: dict[str, Any]) -> dict[str, Any]:
        current = self.get_incident(incident_id)
        if not current:
            raise KeyError(incident_id)
        self._rpc("apply_incident_review", {"p_incident_id": incident_id, "p_status": values["status"], "p_reviewer": values["reviewer"], "p_reviewer_user_id": values.get("reviewer_user_id"), "p_comment": values["comment"], "p_sif_potential": values["sif_potential"], "p_label_status": values["label_status"], "p_outcome": values["outcome"], "p_timestamp": values["timestamp"], "p_previous_outcome": values["previous_outcome"], "p_screening_version": values["screening_version"]})
        return self.get_incident(incident_id) or {}

    def list_alerts(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page_size = 500
        offset = 0
        while True:
            page = self._request("GET", "alerts", params={"select": "*", "order": "created_at.desc", "limit": page_size, "offset": offset}) or []
            result.extend(page)
            if len(page) < page_size:
                return result
            offset += page_size

    def _rpc(self, function: str, payload: dict[str, Any]) -> Any:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        try:
            response = httpx.post(f"{self.base_url}/rest/v1/rpc/{function}", json=payload, headers=headers, timeout=20)
        except httpx.HTTPError as error:
            raise DatabaseError("Supabase database is unavailable") from error
        if response.status_code >= 400:
            raise DatabaseError(f"Supabase database RPC failed ({response.status_code})")
        return response.json() if response.content else None

    def update_alert(self, alert_id: str, status: str) -> bool:
        rows = self._request("PATCH", "alerts", params={"id": f"eq.{alert_id}", "select": "id"}, payload={"status": status}, prefer="return=representation") or []
        return bool(rows)

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "profiles", params={"id": f"eq.{user_id}", "select": "id,username,display_name,role"}) or []
        return rows[0] if rows else None

    def get_profile_by_username(self, username: str) -> dict[str, Any] | None:
        rows = self._request("GET", "profiles", params={"username": f"ilike.{username}", "select": "id,username,display_name,role"}) or []
        return rows[0] if rows else None

    def create_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        rows = self._request("POST", "profiles", payload=profile, prefer="return=representation") or []
        return rows[0] if rows else profile

    def update_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        rows = self._request("PATCH", "profiles", params={"id": f"eq.{user_id}"}, payload=profile, prefer="return=representation") or []
        return rows[0] if rows else {"id": user_id, **profile}


_database: SQLiteDatabase | SupabaseDatabase | None = None


def get_database() -> SQLiteDatabase | SupabaseDatabase:
    global _database
    if _database is None:
        if supabase_configured():
            _database = SupabaseDatabase()
        else:
            _database = SQLiteDatabase()
    return _database


def reset_database_for_tests() -> None:
    global _database
    _database = None
