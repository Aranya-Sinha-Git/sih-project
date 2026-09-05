from __future__ import annotations

import csv
import html
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "16_DOWNLOAD_STATUS"
READY = STATUS / "READY_ACCESSIBLE"
FILES = READY / "FILES"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    ready_index = STATUS / "READY_ACCESSIBLE" / "verified_downloads.csv"
    ready_rows = read_csv(ready_index)
    FILES.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, str]] = []
    for row in ready_rows:
        relative = row["relative_path"]
        source = ROOT / Path(*relative.split("\\"))
        if not source.is_file():
            copied.append({"source_relative_path": relative, "openable_copy": "", "status": "source_missing"})
            continue
        target = FILES / Path(*relative.split("\\"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append({
            "source_relative_path": relative,
            "openable_copy": str(target.relative_to(STATUS)),
            "status": "copied_verified_source",
        })

    with (READY / "OPENABLE_FILES.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_relative_path", "openable_copy", "status"])
        writer.writeheader()
        writer.writerows(copied)

    (READY / "README.md").write_text(
        "# Ready accessible downloads\n\n"
        "Openable copies of the verified source files are in the `FILES` subfolder. They are copied "
        "from the immutable source-specific folders; the originals remain unchanged.\n\n"
        f"Materialized: {NOW}.\n",
        encoding="utf-8",
    )

    blocked_index = STATUS / "COULD_NOT_ACCESS" / "downloads_not_accessed.csv"
    blocked_rows = read_csv(blocked_index)
    items = []
    for row in blocked_rows:
        url = row.get("official_landing_page", "")
        label = row.get("report_title") or row.get("report_id") or row.get("source") or "Official source"
        reason = row.get("reason", "")
        link = f'<li><a href="{html.escape(url, quote=True)}">{html.escape(label)}</a><br><small>{html.escape(reason)}</small></li>' if url else f"<li>{html.escape(label)}<br><small>{html.escape(reason)}</small></li>"
        items.append(link)
    page = "<!doctype html><html><head><meta charset=\"utf-8\"><title>Downloads not accessed</title></head><body>"
    page += "<h1>Downloads that could not be accessed</h1><p>Open an official link below to try with authorized access. These items were not downloaded locally.</p><ul>"
    page += "".join(items)
    page += "</ul></body></html>"
    (STATUS / "COULD_NOT_ACCESS" / "OPEN_OFFICIAL_LINKS.html").write_text(page, encoding="utf-8")

    (STATUS / "README.md").write_text(
        "# Download access status\n\n"
        "Open actual files from `READY_ACCESSIBLE/FILES`. Use `COULD_NOT_ACCESS/OPEN_OFFICIAL_LINKS.html` "
        "for official pages requiring manual access or unavailable in this environment.\n",
        encoding="utf-8",
    )
    print(f"materialized={sum(r['status'] == 'copied_verified_source' for r in copied)} missing={sum(r['status'] != 'copied_verified_source' for r in copied)} blocked_links={len(blocked_rows)}")


if __name__ == "__main__":
    main()
