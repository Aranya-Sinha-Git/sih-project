"""Write checksums and structural metadata after the XLSX export."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = [
    "judge_demo_100.csv",
    "judge_demo_100_qa_matrix.csv",
    "judge_demo_100_runtime_profile.json",
    "DATASET_CARD.md",
    "outputs/judge_demo_100_20260912/judge_demo_100.xlsx",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    rows = list(csv.DictReader((ROOT / "judge_demo_100.csv").open(encoding="utf-8")))
    profile = json.loads((ROOT / "judge_demo_100_runtime_profile.json").read_text(encoding="utf-8"))
    manifest = {
        "dataset_id": "synthetic_judge_demo_100_v0_1",
        "status": "synthetic_non_validation",
        "synthetic": True,
        "row_count": len(rows),
        "schema": list(rows[0]),
        "date_range": {"min": min(row["report_date"] for row in rows), "max": max(row["report_date"] for row in rows)},
        "dimension_counts": {
            "site": dict(sorted(Counter(row["site"] for row in rows).items())),
            "activity": dict(sorted(Counter(row["activity"] for row in rows).items())),
            "report_type": dict(sorted(Counter(row["report_type"] for row in rows).items())),
        },
        "duplicate_checks": {
            "duplicate_report_ids": len(rows) - len({row["report_id"] for row in rows}),
            "duplicate_normalized_narrative_site_pairs": len(rows) - len({(" ".join(row["narrative"].casefold().split()), row["site"].casefold()) for row in rows}),
        },
        "runtime_profile_status": profile["status"],
        "active_artifacts": profile["active_artifacts"],
        "boundary": {
            "no_predictions_or_ai_labels_in_upload": True,
            "no_real_people_or_confidential_records": True,
            "blind_test_releases_untouched": True,
        },
        "files": {
            name: {"bytes": (ROOT / name).stat().st_size, "sha256": sha256(ROOT / name)}
            for name in FILES
        },
        "checksum_scope": "All listed files are checksummed; this manifest excludes its own checksum.",
    }
    (ROOT / "judge_demo_100_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "files": len(FILES), "profile": profile["status"]}, indent=2))


if __name__ == "__main__":
    main()
