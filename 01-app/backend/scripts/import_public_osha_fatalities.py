"""Download and import 50 original public OSHA fatality investigation summaries.

These are positive weak labels because OSHA's public detail record explicitly
marks each as a fatality. They are not expert SIF adjudications.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import con, init_db  # noqa: E402
from app.services.engine import analyze_text  # noqa: E402

BASE = "https://www.osha.gov/ords/imis/accidentsearch"
ARCHIVE = ROOT / "data" / "public_osha_fatality_reports"
HEADERS = {"User-Agent": "SIF-Sentinel-public-safety-research/1.0 (educational prototype)"}
TARGET = 50
SEED_IDS = [
    "180500.015", "174959.015", "174984.015", "174925.015", "178170.015", "174967.015", "174966.015", "174972.015", "174960.015", "174774.015",
    "174740.015", "174728.015", "177774.015", "175101.015", "174793.015", "174739.015", "174660.015", "178015.015", "174620.015", "174555.015",
    "174574.015", "174558.015", "174514.015", "174541.015", "174560.015", "174557.015", "175818.015", "174483.015", "177814.015", "174500.015",
    "174548.015", "174522.015", "174519.015", "174505.015", "174473.015", "174445.015", "174491.015", "174482.015", "174468.015", "174385.015",
    "174513.015", "174451.015", "174360.015", "178660.015", "174379.015", "174419.015", "174403.015", "174354.015", "174329.015", "174590.015",
]


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def plain(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def result_url(start: int, finish: int) -> str:
    params = {
        "acc_abstract": "", "acc_description": "", "acc_keyword": "", "endday": "", "endmonth": "", "endyear": "",
        "fatal": "", "inspnr": "", "keyword_list": "", "naics": "", "office": "", "officetype": "",
        "p_desc": "DESC", "p_direction": "Next", "p_finish": str(finish), "p_show": "20", "p_sort": "", "p_start": str(start),
        "sic": "", "sicgroup": "", "startday": "", "startmonth": "", "startyear": "",
    }
    return f"{BASE}.search?{urllib.parse.urlencode(params)}"


def detail_ids() -> list[str]:
    return SEED_IDS.copy()


def parse_detail(record_id: str) -> dict | None:
    url = f"{BASE}.accident_detail?id={urllib.parse.quote(record_id)}"
    target = ARCHIVE / f"OSHA_{record_id.replace('.', '_')}.html"
    source = target.read_text(encoding="utf-8") if target.exists() else fetch(url)
    if not target.exists():
        target.write_text(source, encoding="utf-8")
    title_match = re.search(r"Accident Summary Nr:\s*[^-]+-\s*(.*?)</", source, re.I | re.S)
    abstract_match = re.search(r"Abstract:\s*</?[^>]*>?(.*?)(?:Keywords:|Accident Details)", source, re.I | re.S)
    date_match = re.search(r"Event Date:\s*(\d{2}/\d{2}/\d{4})", source, re.I)
    title = plain(title_match.group(1)) if title_match else f"OSHA accident summary {record_id}"
    narrative = plain(abstract_match.group(1)) if abstract_match else title
    # Seed IDs are taken only from OSHA results whose Fatality column is X;
    # the detail abstract may use a different wording (for example, "died").
    if len(narrative) < 20:
        return None
    event_date = datetime.strptime(date_match.group(1), "%m/%d/%Y").date().isoformat() if date_match else "2000-01-01"
    return {"id": f"OSHA-{record_id.replace('.', '-')}", "external_id": record_id, "title": title[:180], "narrative": narrative[:2200], "report_date": event_date, "source_url": url}


def import_records(records: list[dict]) -> tuple[int, int]:
    init_db(); database = con(); added = skipped = 0
    for record in records:
        if database.execute("SELECT 1 FROM incidents WHERE id=?", (record["id"],)).fetchone():
            skipped += 1; continue
        analysis = analyze_text(record["narrative"])
        analysis["provenance"] = {
            "source_type": "public_verified_osha_imis", "publisher": "U.S. Occupational Safety and Health Administration",
            "source_url": record["source_url"], "source_report_id": record["external_id"], "source_title": record["title"],
            "label_basis": "OSHA accident-detail record marks a fatality", "label_note": "Weak label from a public source. It is not expert SIF adjudication.",
        }
        analysis["sif_weak_label"] = 1
        database.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            record["id"], record["report_date"], "OSHA public report", "Unspecified", record["narrative"], "public_verified",
            analysis["sif_probability"], analysis["risk"], None, 1, "weak_label", json.dumps(analysis), "Pending", None, None, datetime.now().isoformat(),
        ))
        added += 1
    database.commit(); database.close(); return added, skipped


def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    offset = int(next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--offset=")), "0"))
    count = int(next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--count=")), str(TARGET)))
    ids = detail_ids()[offset:offset + count]
    if len(ids) != count:
        raise SystemExit(f"Requested {count} OSHA result IDs, found {len(ids)}; nothing imported.")
    with ThreadPoolExecutor(max_workers=25) as pool:
        records = [record for record in pool.map(parse_detail, ids) if record]
    if len(records) != count:
        raise SystemExit(f"Only verified {len(records)} of {count} OSHA fatality details; nothing imported.")
    manifest = ROOT / "data" / f"public_verified_osha_fatality_weak_labels_{offset}_{offset + count}.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    added, skipped = import_records(records)
    print(f"Selected={len(records)} positives={len(records)} imported={added} already_present={skipped}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()
