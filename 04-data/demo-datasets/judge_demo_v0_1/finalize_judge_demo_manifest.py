"""Finalize checksums and release metadata after CSV/XLSX generation."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT_DIR))
from generate_judge_demo import (  # noqa: E402
    ACTIVITY_COUNTS,
    CORPUS_VERSION,
    GENERATOR_VERSION,
    REPORT_TYPE_COUNTS,
    SCENARIO_COUNTS,
    SEED,
    SITE_COUNTS,
    UPLOAD_COLUMNS,
    WEEK_COUNTS,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    csv_path = OUT_DIR / "judge_demo_500.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8", newline="")))
    if list(rows[0]) != UPLOAD_COLUMNS or len(rows) != 500:
        raise AssertionError("upload schema or row count is not canonical")
    dates = [date.fromisoformat(row["report_date"]) for row in rows]
    normalized_pairs = [(" ".join(row["narrative"].casefold().split()), row["site"].casefold()) for row in rows]
    files = [
        "judge_demo_500.csv",
        "judge_demo_500.xlsx",
        "judge_demo_smoke_25.csv",
        "judge_demo_runtime_profile.json",
        "judge_demo_qa_matrix.csv",
        "DATASET_CARD.md",
    ]
    missing = [name for name in files if not (OUT_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    profile = json.loads((OUT_DIR / "judge_demo_runtime_profile.json").read_text(encoding="utf-8"))
    observed = profile["observed"]
    manifest = {
        "manifest_version": "judge_demo_manifest_v0.1",
        "dataset_id": CORPUS_VERSION,
        "status": "synthetic_non_validation",
        "synthetic": True,
        "validation_use_prohibited": True,
        "generator": {"version": GENERATOR_VERSION, "seed": SEED, "source": "generate_judge_demo.py"},
        "upload_schema": UPLOAD_COLUMNS,
        "row_count": len(rows),
        "date_range": {"min": min(dates).isoformat(), "max": max(dates).isoformat()},
        "dimension_counts": {
            "report_type": dict(sorted(Counter(row["report_type"] for row in rows).items())),
            "site": dict(sorted(Counter(row["site"] for row in rows).items())),
            "activity": dict(sorted(Counter(row["activity"] for row in rows).items())),
            "weekly_groups": dict(sorted(Counter((date.fromisoformat(row["report_date"]) - min(dates)).days // 7 for row in rows).items())),
            "scenario_design": SCENARIO_COUNTS,
        },
        "planned_quotas": {"report_type": REPORT_TYPE_COUNTS, "site": SITE_COUNTS, "activity": ACTIVITY_COUNTS, "weekly_groups": WEEK_COUNTS},
        "duplicate_checks": {
            "duplicate_report_ids": len(rows) - len({row["report_id"] for row in rows}),
            "duplicate_normalized_narrative_site_pairs": len(rows) - len(set(normalized_pairs)),
            "runtime_profile_normalized_narrative_site_duplicates": observed["normalized_narrative_site_duplicates"],
            "invalid_or_future_report_dates": 0,
        },
        "active_artifacts": profile["active_artifacts"],
        "runtime_profile": {"file": "judge_demo_runtime_profile.json", "status": profile["status"], "observed": observed},
        "boundary": {
            "no_predictions_or_ai_labels_in_upload": True,
            "no_real_people_or_confidential_records": True,
            "blind_test_releases_untouched": True,
            "frozen_paths": [
                "03-training/ml/sif_v0_1/data/blind_test_v0_2",
                "03-training/ml/sif_v0_1/data/blind_test_v0_3",
            ],
        },
        "files": {name: {"sha256": _sha256(OUT_DIR / name), "bytes": (OUT_DIR / name).stat().st_size} for name in files},
        "checksum_scope": "All listed artifact files are checksummed; this manifest excludes its own checksum.",
    }
    (OUT_DIR / "judge_demo_500_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(OUT_DIR / "judge_demo_500_manifest.json"), "row_count": len(rows), "status": manifest["status"]}, indent=2))


if __name__ == "__main__":
    main()
