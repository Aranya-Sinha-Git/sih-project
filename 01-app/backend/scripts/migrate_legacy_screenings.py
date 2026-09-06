"""Replace screenings with current frozen-classifier and grounded mappings.

The original screening is retained inside each analysis JSON object under
``legacy_screening``. Human review fields and review history are never changed.
Run with ``--dry-run`` first; the default is read-only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import DB, init_db
from app.services.classifier import analyze_with_classifier
from app.services.engine import analyze_text


def is_legacy(analysis: dict) -> bool:
    mode = str(analysis.get("model_mode") or "").casefold()
    version = str(analysis.get("model_version") or "").casefold()
    return "transparent rules engine" in mode or version == "rules-v1.0"


def migrate(*, apply: bool, all_incidents: bool = False) -> tuple[int, int, list[dict]]:
    init_db()
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM incidents ORDER BY id").fetchall()
    corpus = [dict(item) for item in rows]
    migrated: list[dict] = []
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    try:
        for row in rows:
            raw = row["analysis"]
            try:
                old = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                old = {"legacy_raw_analysis": raw}
            if not all_incidents and (not isinstance(old, dict) or not is_legacy(old)):
                skipped += 1
                continue
            supplemental = analyze_text(row["narrative"])
            fresh = analyze_with_classifier(row["narrative"], supplemental)
            if all_incidents:
                from app.main import intelligence_snapshot
                # Reuse the snapshot corpus loaded above. Opening rows() from a
                # second connection while this transaction is writing causes
                # SQLite to report ``database is locked`` and gets serialized as
                # retrieval_unavailable by the API.
                fresh["intelligence"] = intelligence_snapshot(row["narrative"], item_id=row["id"], corpus=corpus)
                mappings = [{"rule": item["rule"], "evidence_id": item["evidence_id"], "provenance": "grounded_iogp_reference"}
                            for item in fresh["intelligence"].get("reference_evidence", [])
                            if item.get("reference_type") == "iogp_reference" and item.get("rule")]
                fresh["rules"] = {"primary": mappings[0] if mappings else None, "secondary": mappings[1:]}
                fresh["rerun_history"] = old.get("rerun_history", []) + [{"rerun_at": now, "previous_analysis": old}]
            else:
                fresh["intelligence"] = old.get("intelligence")
            fresh["legacy_screening"] = {
                "migrated_at": now,
                "model_mode": old.get("model_mode"),
                "model_version": old.get("model_version"),
                "classification": old.get("classification"),
                "classification_basis": old.get("classification_basis"),
                "sif_probability": old.get("sif_probability"),
                "risk": old.get("risk"),
                "sif_potential": old.get("sif_potential"),
                "sif_label_status": old.get("sif_label_status"),
                "review_required": old.get("review_required"),
                "analysis": old,
            }
            if apply:
                connection.execute(
                    "UPDATE incidents SET sif_probability=?,risk=?,high_potential=?,sif_potential=?,sif_label_status=?,analysis=? WHERE id=?",
                    (fresh["sif_probability"], fresh["risk"], fresh["high_potential"], fresh["sif_potential"], fresh["sif_label_status"], json.dumps(fresh), row["id"]),
                )
            migrated.append({
                "id": row["id"],
                "legacy_model": old.get("model_version"),
                "new_model": fresh.get("model_version"),
                "old_classification": old.get("classification"),
                "new_classification": fresh.get("classification"),
                "old_score": old.get("sif_probability"),
                "new_score": fresh.get("sif_probability"),
            })
        if apply:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(migrated), skipped, migrated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the migration")
    parser.add_argument("--all", action="store_true", dest="all_incidents", help="rerun every incident with current classifier and mapping")
    parser.add_argument("--manifest", type=Path, help="write a JSON before/after manifest")
    args = parser.parse_args()
    migrated, skipped, manifest = migrate(apply=args.apply, all_incidents=args.all_incidents)
    if args.manifest:
        args.manifest.write_text(json.dumps({"applied": args.apply, "migrated": migrated, "skipped": skipped, "records": manifest}, indent=2), encoding="utf-8")
    print(json.dumps({"applied": args.apply, "migrated": migrated, "skipped": skipped, "manifest": str(args.manifest) if args.manifest else None}))


if __name__ == "__main__":
    main()
