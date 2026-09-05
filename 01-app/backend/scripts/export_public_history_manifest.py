"""Export source provenance for the currently imported public history."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import rows  # noqa: E402


def main() -> None:
    manifest = []
    for report in rows():
        provenance = report["analysis"].get("provenance", {})
        if not provenance.get("source_type", "").startswith("public_verified"):
            continue
        manifest.append({
            "id": report["id"], "sif_weak_label": report["sif_potential"], "sif_label_status": report["sif_label_status"],
            "report_date": report["report_date"], "source": report["source"], "source_type": provenance.get("source_type"),
            "publisher": provenance.get("publisher"), "source_report_id": provenance.get("source_report_id"),
            "source_title": provenance.get("source_title"), "source_url": provenance.get("source_url"),
            "label_basis": provenance.get("label_basis"), "label_note": provenance.get("label_note"),
        })
    target = ROOT / "data" / "public_verified_history_manifest.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exported {len(manifest)} records to {target}")


if __name__ == "__main__":
    main()
