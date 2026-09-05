from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from label_store import LabelStore


def incident(candidate_id: str = "candidate-1") -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "source": "TEST",
        "source_record_id": f"source-{candidate_id}",
        "narrative": "Worker stood near stored energy during an isolation failure.",
        "source_native_outcome": "No injury",
        "activity_if_known": "Maintenance",
    }


def test_store_keeps_history_current_snapshot_backup_and_exports(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame([{"candidate_id": "candidate-1", "duplicate_group": "group-1"}]).to_csv(
        data / "candidate_pool.csv", index=False
    )
    store = LabelStore(data)
    store.initialize()
    store.save(incident(), "UNCERTAIN", "medium", "Needs more context", "Reviewer")
    store.save(incident(), "SIF_POTENTIAL", "high", "Isolation barrier failed", "Reviewer")

    current = store.current()
    assert len(current) == 1
    assert store.history_count() == 2
    assert current.iloc[0].reviewer_sif_label == "SIF_POTENTIAL"
    assert store.database.exists() and store.backup.exists()

    decisions = pd.read_csv(data / "annotation_decisions.csv")
    reviewed = pd.read_csv(data / "reviewed_labels.csv")
    assert len(decisions) == 1
    assert len(reviewed) == 1
    assert reviewed.iloc[0].label_provenance == "manual_reviewed"
    assert reviewed.iloc[0].duplicate_group == "group-1"


def test_store_migrates_existing_csv_once(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    legacy = {
        **incident("legacy-1"),
        "reviewer_sif_label": "UNCERTAIN",
        "reviewer_confidence": "low",
        "reviewer_notes": "Legacy note",
        "saved_at": "2026-09-03T00:00:00+00:00",
    }
    pd.DataFrame([legacy]).to_csv(data / "annotation_decisions.csv", index=False)
    store = LabelStore(data)
    store.initialize()
    store.initialize()
    assert len(store.current()) == 1
    assert store.history_count() == 1
