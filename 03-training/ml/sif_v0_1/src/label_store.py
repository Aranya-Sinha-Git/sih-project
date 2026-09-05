"""Durable local storage for human SIF annotation decisions."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pandas as pd


VALID_LABELS = {"SIF_POTENTIAL", "NON_SIF_POTENTIAL", "UNCERTAIN", "SKIP"}
CURRENT_COLUMNS = [
    "candidate_id",
    "source",
    "source_record_id",
    "narrative",
    "source_native_outcome",
    "activity_if_known",
    "reviewer_sif_label",
    "reviewer_confidence",
    "reviewer_notes",
    "reviewer",
    "saved_at",
]


def _atomic_csv(frame: pd.DataFrame, path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.reindex(columns=columns).to_csv(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LabelStore:
    """SQLite source of truth plus atomic CSV compatibility exports."""

    def __init__(self, data_root: Path, storage_dir: Path | None = None) -> None:
        self.data_root = data_root.resolve()
        self.storage_dir = (storage_dir or self.data_root / "local_label_store").resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.storage_dir / "annotations.sqlite3"
        self.backup = self.storage_dir / "annotations.backup.sqlite3"
        self.decisions_csv = self.data_root / "annotation_decisions.csv"
        self.reviewed_csv = self.data_root / "reviewed_labels.csv"
        self.pool_csv = self.data_root / "candidate_pool.csv"
        self.lock_path = self.storage_dir / ".label-store.lock"

    @contextmanager
    def _lock(self):
        """Bounded cross-process lock for DB commits and snapshot publication."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+b")
        deadline = time.monotonic() + 15
        try:
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        handle.seek(0)
                        handle.write(b"0")
                        handle.flush()
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring label-store lock: {self.lock_path}")
                    time.sleep(0.05)
            yield
        finally:
            try:
                if os.name == "nt":
                    # Closing the Windows handle releases the byte-range lock;
                    # an explicit LK_UNLCK can fail after another operation
                    # moved the file pointer.
                    pass
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def initialize(self) -> None:
        with self._lock():
            with self._connect() as connection:
                connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS annotation_history (
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    narrative TEXT NOT NULL,
                    source_native_outcome TEXT NOT NULL,
                    activity_if_known TEXT NOT NULL,
                    reviewer_sif_label TEXT NOT NULL,
                    reviewer_confidence TEXT NOT NULL,
                    reviewer_notes TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    saved_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_annotation_history_candidate
                    ON annotation_history(candidate_id);
                CREATE TABLE IF NOT EXISTS annotation_current (
                    candidate_id TEXT PRIMARY KEY,
                    decision_id INTEGER NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    narrative TEXT NOT NULL,
                    source_native_outcome TEXT NOT NULL,
                    activity_if_known TEXT NOT NULL,
                    reviewer_sif_label TEXT NOT NULL,
                    reviewer_confidence TEXT NOT NULL,
                    reviewer_notes TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES annotation_history(decision_id)
                );
                """
            )
                migrated = connection.execute("SELECT value FROM store_metadata WHERE key = 'legacy_csv_migrated'").fetchone()
                if migrated is None:
                    self._migrate_legacy_csv(connection)
                    connection.execute("INSERT INTO store_metadata(key, value) VALUES('legacy_csv_migrated', ?)", (datetime.now(timezone.utc).isoformat(),))
            self._create_backup_locked()
            self._export_csv_snapshots_locked()

    def _migrate_legacy_csv(self, connection: sqlite3.Connection) -> None:
        if not self.decisions_csv.exists() or self.decisions_csv.stat().st_size == 0:
            return
        legacy = pd.read_csv(self.decisions_csv, dtype=str).fillna("")
        for row in legacy.to_dict(orient="records"):
            label = row.get("reviewer_sif_label", "")
            candidate_id = row.get("candidate_id", "").strip()
            if candidate_id and label in VALID_LABELS:
                self._insert(connection, row, label, row.get("reviewer_confidence", ""), row.get("reviewer_notes", ""), row.get("reviewer", ""), row.get("saved_at", ""))

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        incident: Mapping[str, object],
        label: str,
        confidence: str,
        notes: str,
        reviewer: str,
        saved_at: str = "",
    ) -> int:
        timestamp = saved_at or datetime.now(timezone.utc).isoformat()
        values = {
            "candidate_id": str(incident.get("candidate_id", "")).strip(),
            "source": str(incident.get("source", "")).strip(),
            "source_record_id": str(incident.get("source_record_id", "")).strip(),
            "narrative": str(incident.get("narrative", "")).strip(),
            "source_native_outcome": str(incident.get("source_native_outcome", "")).strip(),
            "activity_if_known": str(incident.get("activity_if_known", "")).strip(),
            "reviewer_sif_label": label,
            "reviewer_confidence": confidence.strip(),
            "reviewer_notes": notes.strip(),
            "reviewer": reviewer.strip(),
            "saved_at": timestamp,
        }
        cursor = connection.execute(
            """
            INSERT INTO annotation_history(
                candidate_id, source, source_record_id, narrative,
                source_native_outcome, activity_if_known, reviewer_sif_label,
                reviewer_confidence, reviewer_notes, reviewer, saved_at
            ) VALUES(
                :candidate_id, :source, :source_record_id, :narrative,
                :source_native_outcome, :activity_if_known, :reviewer_sif_label,
                :reviewer_confidence, :reviewer_notes, :reviewer, :saved_at
            )
            """,
            values,
        )
        decision_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO annotation_current(
                candidate_id, decision_id, source, source_record_id, narrative,
                source_native_outcome, activity_if_known, reviewer_sif_label,
                reviewer_confidence, reviewer_notes, reviewer, saved_at
            ) VALUES(
                :candidate_id, :decision_id, :source, :source_record_id, :narrative,
                :source_native_outcome, :activity_if_known, :reviewer_sif_label,
                :reviewer_confidence, :reviewer_notes, :reviewer, :saved_at
            )
            ON CONFLICT(candidate_id) DO UPDATE SET
                decision_id=excluded.decision_id,
                source=excluded.source,
                source_record_id=excluded.source_record_id,
                narrative=excluded.narrative,
                source_native_outcome=excluded.source_native_outcome,
                activity_if_known=excluded.activity_if_known,
                reviewer_sif_label=excluded.reviewer_sif_label,
                reviewer_confidence=excluded.reviewer_confidence,
                reviewer_notes=excluded.reviewer_notes,
                reviewer=excluded.reviewer,
                saved_at=excluded.saved_at
            """,
            {**values, "decision_id": decision_id},
        )
        return decision_id

    def save(
        self,
        incident: Mapping[str, object],
        label: str,
        confidence: str,
        notes: str,
        reviewer: str,
    ) -> int:
        if label not in VALID_LABELS:
            raise ValueError(f"Invalid SIF label: {label}")
        if not str(incident.get("candidate_id", "")).strip():
            raise ValueError("candidate_id is required")
        if label in {"SIF_POTENTIAL", "NON_SIF_POTENTIAL"} and len(reviewer.strip()) < 2:
            raise ValueError("Reviewer name is required for binary labels")
        with self._lock():
            with self._connect() as connection:
                decision_id = self._insert(connection, incident, label, confidence, notes, reviewer)
            try:
                self._create_backup_locked()
                self._export_csv_snapshots_locked()
            except Exception as export_error:
                raise RuntimeError(f"Decision saved; export failed: {export_error}") from export_error
        return decision_id

    def current(self) -> pd.DataFrame:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT " + ", ".join(CURRENT_COLUMNS) + " FROM annotation_current ORDER BY decision_id"
            ).fetchall()
        return pd.DataFrame([dict(row) for row in rows], columns=CURRENT_COLUMNS)

    def history_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM annotation_history").fetchone()[0])

    def export_csv_snapshots(self) -> None:
        with self._lock():
            self._export_csv_snapshots_locked()

    def _export_csv_snapshots_locked(self) -> None:
        current = self.current()
        _atomic_csv(current, self.decisions_csv, CURRENT_COLUMNS)
        group_by_candidate: dict[str, str] = {}
        if self.pool_csv.exists() and self.pool_csv.stat().st_size:
            pool = pd.read_csv(self.pool_csv, dtype=str).fillna("")
            if {"candidate_id", "duplicate_group"}.issubset(pool.columns):
                group_by_candidate = dict(zip(pool.candidate_id, pool.duplicate_group))
        binary = current[current.reviewer_sif_label.isin({"SIF_POTENTIAL", "NON_SIF_POTENTIAL"})]
        reviewed_columns = [
            "candidate_id", "source", "narrative", "adjudicated_label",
            "label_provenance", "reviewer", "reviewed_at", "notes", "duplicate_group",
        ]
        reviewed_rows = []
        for row in binary.itertuples(index=False):
            reviewed_rows.append(
                {
                    "candidate_id": row.candidate_id,
                    "source": row.source,
                    "narrative": row.narrative,
                    "adjudicated_label": "1" if row.reviewer_sif_label == "SIF_POTENTIAL" else "0",
                    "label_provenance": "manual_reviewed",
                    "reviewer": row.reviewer,
                    "reviewed_at": row.saved_at,
                    "notes": row.reviewer_notes,
                    "duplicate_group": group_by_candidate.get(row.candidate_id, row.candidate_id),
                }
            )
        _atomic_csv(pd.DataFrame(reviewed_rows, columns=reviewed_columns), self.reviewed_csv, reviewed_columns)

    def _create_backup(self) -> None:
        with self._lock():
            self._create_backup_locked()

    def _create_backup_locked(self) -> None:
        with tempfile.NamedTemporaryFile(prefix=f".{self.backup.name}.", suffix=".tmp", dir=self.backup.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
            os.replace(temporary, self.backup)
        finally:
            temporary.unlink(missing_ok=True)


def default_store() -> LabelStore:
    root = Path(__file__).resolve().parents[1]
    data_root = root / "data"
    configured = os.getenv("SIF_LABEL_DATA_DIR", "").strip()
    storage_dir = Path(configured).expanduser() if configured else data_root / "local_label_store"
    if not storage_dir.is_absolute():
        storage_dir = root / storage_dir
    return LabelStore(data_root=data_root, storage_dir=storage_dir)
