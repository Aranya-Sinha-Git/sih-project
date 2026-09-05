from __future__ import annotations

import csv
import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def capture(url: str, destination: Path) -> dict[str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return {"url": url, "status": "already_present", "file": str(destination.relative_to(ROOT))}
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read()
        if not data:
            raise ValueError("empty response")
        destination.write_bytes(data)
        return {
            "url": url,
            "status": "downloaded",
            "file": str(destination.relative_to(ROOT)),
            "bytes": str(len(data)),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {"url": url, "status": f"not_downloaded: {exc}", "file": ""}


def main() -> None:
    # These are the prescribed empty folders. Each receives an evidence/status artifact;
    # no synthetic incident rows are created.
    statuses: dict[str, str] = {
        "01_OIL_INDIA_PUBLIC/ENVIRONMENT_AND_RISK": (
            "# Oil India — environment and risk\n\n"
            "This folder contains the status of publicly discoverable environment/risk material. "
            "The authoritative Oil India BRSR PDFs and Baghjan/environment documents are stored in "
            "the sibling `BRSR` and `BAGHJAN` folders. No additional public structured incident table "
            "was found for this category during this collection.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "01_OIL_INDIA_PUBLIC/OTHER_PUBLIC_SAFETY": (
            "# Oil India — other public safety\n\n"
            "Official Oil India public safety source-page captures are stored here when available. "
            "The underlying BRSR, HSE schema, and Baghjan source files remain in their dedicated folders.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "02_IOGP/FATAL_INCIDENTS": (
            "# IOGP fatal incident reports\n\n"
            "IOGP annual fatality reports are listed on the official safety-data page but require the "
            "publisher's name/company/email form before download. The collection does not bypass that "
            "access gate. See `00_MANIFEST/MANUAL_DOWNLOAD_REQUIRED.csv`.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "02_IOGP/FPI_REFERENCES": (
            "# IOGP FPI references\n\n"
            "FPI (Fatal Potential Incident) references are retained as a discovery/status area. No "
            "public, downloadable IOGP FPI incident table was available without the publisher's gated "
            "form.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "02_IOGP/PROCESS_SAFETY": (
            "# IOGP process-safety material\n\n"
            "No open structured incident export was identified for this folder. IOGP public guidance and "
            "the Life-Saving Rules material are stored under `SAFETY_DATA_GUIDES` and "
            "`LIFE_SAVING_RULES`.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "03_NIOSH_FOG/PROCESSED": (
            "# NIOSH FOG — processed\n\n"
            "No processed incident rows are claimed here. NIOSH FOG official landing/index pages are "
            "documented under `DOCUMENTATION`; the direct CDC Stacks export endpoints returned HTTP 403 "
            "during collection, so no access control was bypassed.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "03_NIOSH_FOG/RAW": (
            "# NIOSH FOG — raw\n\n"
            "The official NIOSH FOG raw export is not present because the CDC Stacks download endpoint "
            "returned HTTP 403. This folder intentionally contains a status record instead of an "
            "unverified or synthetic replacement.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "04_OSHA/DOCUMENTATION": (
            "# OSHA documentation\n\n"
            "The official OSHA Severe Injury Reports landing page is captured here when accessible. "
            "The source archive and filtered oil/gas data are stored under `SEVERE_INJURY_RAW` and "
            "`OIL_GAS_SUBSET`.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "05_BSEE/DOCUMENTATION": (
            "# BSEE documentation\n\n"
            "Official BSEE incident-statistics and raw-data landing pages are captured here when "
            "accessible. Downloaded annual workbooks and the raw archive remain under `RAW`; the "
            "combined table is under `PROCESSED`.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "06_NIOSH_FACE/OIL_GAS_RELEVANT": (
            "# NIOSH FACE — oil and gas relevant\n\n"
            "The six oil/gas-relevant official FACE report records are indexed in the parent `INDEX` "
            "folder. Their CDC Stacks PDF endpoints returned HTTP 403 during collection, so this folder "
            "contains an access-status index rather than copied PDFs.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "07_OTHER_REAL_DATA_DISCOVERY/LOW_SEVERITY_CANDIDATES": (
            "# Low-severity candidate sources\n\n"
            "Candidate source status is recorded here. No low-severity incident rows are mixed into the "
            "SIF candidate master.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "07_OTHER_REAL_DATA_DISCOVERY/NEAR_MISS_CANDIDATES": (
            "# Near-miss candidate sources\n\n"
            "Candidate source status is recorded here. Oil India public near-miss reporting schema "
            "material is retained under `01_OIL_INDIA_PUBLIC/HSE_REPORTING_SCHEMA`; no synthetic near-miss "
            "records are created.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "07_OTHER_REAL_DATA_DISCOVERY/UNSAFE_ACT_CONDITION_CANDIDATES": (
            "# Unsafe-act/condition candidate sources\n\n"
            "Candidate source status is recorded here. No unsafe-act/condition rows are asserted unless "
            "they are present in an authoritative source.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
        "12_REFERENCE_ONLY": (
            "# Reference-only material\n\n"
            "This folder holds contextual source-page captures and a reference catalog. These files are "
            "not training or validation records.\n\n"
            f"Status recorded: {NOW}.\n"
        ),
    }
    for rel, text in statuses.items():
        write_text(ROOT / rel / "SOURCE_STATUS.md", text)

    # Every IOGP annual event subfolder gets an explicit, auditable access record.
    iogp_rows = []
    for year in range(2021, 2026):
        for kind, code in (("High Potential Events", "sh"), ("Fatal Incidents", "sf")):
            url = f"https://www.iogp.org/safety-data/{year}{code}/"
            rel = f"02_IOGP/{'HIGH_POTENTIAL_EVENTS' if code == 'sh' else 'FATAL_INCIDENTS'}/{year}"
            write_text(
                ROOT / rel / "ACCESS_STATUS.md",
                f"# IOGP {year} — {kind}\n\n"
                f"Official listing: {url}\n\n"
                "Download requires the publisher's form (name, company, and email). The gate was not "
                "bypassed. When the report is supplied manually, preserve it as raw source material and "
                "update the manifest/checksum.\n",
            )
            iogp_rows.append({"year": str(year), "category": kind, "official_listing": url, "status": "manual_download_required"})
    write_csv(ROOT / "02_IOGP" / "annual_access_status.csv", iogp_rows, ["year", "category", "official_listing", "status"])

    # Copy only existing parent indexes into category folders as auditable pointers.
    candidate_catalog = ROOT / "07_OTHER_REAL_DATA_DISCOVERY" / "candidate_sources.csv"
    if candidate_catalog.exists():
        rows = list(__import__("csv").DictReader(candidate_catalog.open(encoding="utf-8")))
        for folder, needle in (("LOW_SEVERITY_CANDIDATES", "low"), ("NEAR_MISS_CANDIDATES", "near"), ("UNSAFE_ACT_CONDITION_CANDIDATES", "unsafe")):
            selected = [r for r in rows if needle in " ".join(r.values()).lower()]
            if not selected:
                selected = [{"status": "no_direct_download_identified", "note": "See parent candidate_sources.csv"}]
            write_csv(ROOT / "07_OTHER_REAL_DATA_DISCOVERY" / folder / "candidate_status.csv", selected, list(selected[0].keys()))

    face_index = ROOT / "06_NIOSH_FACE" / "INDEX" / "face_oil_gas_index.csv"
    if face_index.exists():
        rows = list(csv.DictReader(face_index.open(encoding="utf-8")))
        write_csv(ROOT / "06_NIOSH_FACE" / "OIL_GAS_RELEVANT" / "access_status.csv", rows, list(rows[0].keys()))

    reference_rows = [
        {"source_family": "Oil India BRSR", "url": "https://www.oil-india.com/business-responsibility-sustainability-report", "role": "reference and safety statistics source"},
        {"source_family": "Oil India Baghjan update", "url": "https://www.oil-india.com/baghjan-update", "role": "reference-only incident context"},
        {"source_family": "IOGP safety data", "url": "https://www.iogp.org/workstreams/safety/safety/safety-data/", "role": "gated annual safety report index"},
        {"source_family": "NIOSH FOG", "url": "https://www.cdc.gov/niosh/oil-gas/about/fog/index.html", "role": "official data landing page"},
        {"source_family": "OSHA Severe Injury Reports", "url": "https://www.osha.gov/severe-injury-reports", "role": "raw source landing page"},
        {"source_family": "BSEE Offshore Incident Statistics", "url": "https://www.bsee.gov/stats-facts/offshore", "role": "raw source landing page"},
        {"source_family": "NIOSH FACE", "url": "https://www.cdc.gov/niosh/face/", "role": "official case-study index"},
    ]
    write_csv(ROOT / "12_REFERENCE_ONLY" / "reference_catalog.csv", reference_rows, ["source_family", "url", "role"])

    captures = [
        ("https://www.oil-india.com/baghjan-update", ROOT / "01_OIL_INDIA_PUBLIC" / "OTHER_PUBLIC_SAFETY" / "oil_india_baghjan_update.html"),
        ("https://www.oil-india.com/business-responsibility-sustainability-report", ROOT / "01_OIL_INDIA_PUBLIC" / "ENVIRONMENT_AND_RISK" / "oil_india_brsr_index.html"),
        ("https://www.cdc.gov/niosh/oil-gas/about/fog/index.html", ROOT / "03_NIOSH_FOG" / "DOCUMENTATION" / "niosh_fog_landing.html"),
        ("https://www.osha.gov/severe-injury-reports", ROOT / "04_OSHA" / "DOCUMENTATION" / "osha_severe_injury_reports_landing.html"),
        ("https://www.bsee.gov/stats-facts/offshore", ROOT / "05_BSEE" / "DOCUMENTATION" / "bsee_offshore_statistics_landing.html"),
        ("https://www.cdc.gov/niosh/face/", ROOT / "06_NIOSH_FACE" / "OIL_GAS_RELEVANT" / "niosh_face_landing.html"),
        ("https://www.iogp.org/workstreams/safety/safety/safety-data/", ROOT / "12_REFERENCE_ONLY" / "iogp_safety_data_landing.html"),
    ]
    results = [capture(url, dest) for url, dest in captures]
    write_csv(ROOT / "12_REFERENCE_ONLY" / "page_capture_log.csv", results, ["url", "status", "file", "bytes", "sha256"])

    # Keep a machine-readable completion record for the next agent.
    write_text(ROOT / "12_REFERENCE_ONLY" / "population_summary.json", json.dumps({"generated_at": NOW, "captured_pages": results, "policy": "status artifacts only; no synthetic records"}, indent=2) + "\n")
    print(json.dumps({"status_files": len(statuses), "page_captures": results}, indent=2))


if __name__ == "__main__":
    main()
