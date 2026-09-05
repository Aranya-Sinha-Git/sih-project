"""Audit only genuinely reviewed labels; never promote weak or rule-derived labels."""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from preprocess import project_root

ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
ACCEPTED = {"expert_reviewed", "manual_reviewed"}


def audit() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    accepted_rows: list[dict] = []
    rejected = Counter()
    db = project_root() / "01-app" / "backend" / "data" / "sif_sentinel.db"
    if db.exists():
        with sqlite3.connect(db) as connection:
            connection.row_factory = sqlite3.Row
            for row in connection.execute("SELECT id, narrative, source, sif_potential, sif_label_status FROM incidents"):
                status = row["sif_label_status"] or "missing_status"
                label = row["sif_potential"]
                if status in ACCEPTED and label in (0, 1) and (row["narrative"] or "").strip():
                    accepted_rows.append({"candidate_id": row["id"], "source": row["source"], "narrative": row["narrative"], "label": label, "label_provenance": status})
                else:
                    rejected[status] += 1
    reviewed_path = DATA / "reviewed_labels.csv"
    if reviewed_path.exists():
        with reviewed_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                status = (row.get("label_provenance") or "missing_status").strip()
                label = (row.get("adjudicated_label") or row.get("label") or "").strip()
                if status in ACCEPTED and label in {"0", "1"} and (row.get("narrative") or "").strip():
                    accepted_rows.append({"candidate_id": row.get("candidate_id", ""), "source": row.get("source", ""), "narrative": row["narrative"], "label": int(label), "label_provenance": status})
                elif row:
                    rejected[status] += 1
    # Deduplicate accepted IDs while preserving a later reviewed-label export over DB values.
    unique = {row["candidate_id"]: row for row in accepted_rows if row["candidate_id"]}
    accepted_rows = list(unique.values())
    counts = Counter(str(row["label"]) for row in accepted_rows)
    result = {
        "reviewed_labels_accepted": len(accepted_rows), "sif": counts["1"], "non_sif": counts["0"], "uncertain": 0,
        "rejected_labels_by_reason": dict(sorted(rejected.items())),
        "eligible_for_supervised_training": len(accepted_rows) >= 200 and min(counts["0"], counts["1"]) >= 50,
        "accepted_provenance": sorted(ACCEPTED),
    }
    (REPORTS / "label_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (REPORTS / "label_audit.md").write_text(
        "# Label audit\n\n"
        f"- Reviewed labels accepted: {result['reviewed_labels_accepted']}\n- SIF: {result['sif']}\n- Non-SIF: {result['non_sif']}\n"
        f"- Uncertain: 0\n- Eligible for supervised training: {result['eligible_for_supervised_training']}\n"
        f"- Rejected labels: {json.dumps(result['rejected_labels_by_reason'], sort_keys=True)}\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
