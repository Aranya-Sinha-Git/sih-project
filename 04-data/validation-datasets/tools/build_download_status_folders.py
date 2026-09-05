from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "16_DOWNLOAD_STATUS"
READY = OUT / "READY_ACCESSIBLE"
BLOCKED = OUT / "COULD_NOT_ACCESS"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    READY.mkdir(parents=True, exist_ok=True)
    BLOCKED.mkdir(parents=True, exist_ok=True)

    manifest = read_csv(ROOT / "00_MANIFEST" / "files.csv")
    ready_rows = [
        {
            "relative_path": row.get("path", ""),
            "publisher": row.get("publisher", ""),
            "publication_date": row.get("publication_date", ""),
            "source_url": row.get("source_url", ""),
            "official_landing_page": row.get("official_landing_page", ""),
            "bytes": row.get("bytes", ""),
            "sha256": row.get("sha256", ""),
            "status": row.get("status", ""),
        }
        for row in manifest
        if row.get("status", "").startswith("verified")
        and row.get("source_url", "")
        and row.get("publisher", "") != "Project-generated"
    ]
    ready_fields = [
        "relative_path", "publisher", "publication_date", "source_url",
        "official_landing_page", "bytes", "sha256", "status",
    ]
    write_csv(READY / "verified_downloads.csv", ready_rows, ready_fields)

    manual = read_csv(ROOT / "00_MANIFEST" / "MANUAL_DOWNLOAD_REQUIRED.csv")
    blocked_rows = [
        {
            "category": "manual_or_gated_download",
            "source": row.get("source", ""),
            "report_id": row.get("report_id", ""),
            "report_title": row.get("report_title", ""),
            "year": row.get("year", ""),
            "official_landing_page": row.get("official_landing_page", ""),
            "reason": row.get("reason_manual_download_required", ""),
            "expected_destination": row.get("expected_destination", ""),
        }
        for row in manual
    ]
    for row in read_csv(ROOT / "12_REFERENCE_ONLY" / "page_capture_log.csv"):
        if not row.get("status", "").startswith(("downloaded", "already_present")):
            blocked_rows.append(
                {
                    "category": "landing_page_not_downloaded",
                    "source": "page capture",
                    "report_id": "",
                    "report_title": "",
                    "year": "",
                    "official_landing_page": row.get("url", ""),
                    "reason": row.get("status", ""),
                    "expected_destination": "",
                }
            )
    blocked_fields = [
        "category", "source", "report_id", "report_title", "year",
        "official_landing_page", "reason", "expected_destination",
    ]
    write_csv(BLOCKED / "downloads_not_accessed.csv", blocked_rows, blocked_fields)

    (READY / "README.md").write_text(
        "# Ready accessible downloads\n\n"
        "This folder indexes authoritative files successfully downloaded and verified in the current "
        "collection. The immutable files remain in their original source-specific folders; this folder "
        "contains the navigation manifest and does not duplicate large raw files.\n\n"
        f"Status generated: {NOW}.\n",
        encoding="utf-8",
    )
    (BLOCKED / "README.md").write_text(
        "# Downloads that could not be accessed\n\n"
        "This folder indexes official downloads that require authorized manual form submission or "
        "returned an access/availability error during collection. No access control was bypassed and no "
        "replacement or synthetic records were created.\n\n"
        "When a source becomes available, download it to the expected destination shown in the CSV, "
        "then rerun the processing and manifest tools.\n\n"
        f"Status generated: {NOW}.\n",
        encoding="utf-8",
    )
    (OUT / "README.md").write_text(
        "# Download access status\n\n"
        "Use `READY_ACCESSIBLE` for verified source files already available locally. Use "
        "`COULD_NOT_ACCESS` for gated or failed downloads. These are indexes/status artifacts; the raw "
        "source files remain in the prescribed source folders to preserve provenance.\n\n"
        f"Status generated: {NOW}.\n",
        encoding="utf-8",
    )
    (OUT / "STATUS_SUMMARY.txt").write_text(
        f"Generated: {NOW}\n"
        f"Verified downloadable source entries: {len(ready_rows)}\n"
        f"Unavailable/manual entries: {len(blocked_rows)}\n",
        encoding="utf-8",
    )
    print(f"ready={len(ready_rows)} blocked_or_manual={len(blocked_rows)}")


if __name__ == "__main__":
    main()
