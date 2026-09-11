"""Download, verify, weak-label, and import public DOE safety reports.

Only original public DOE Operating Experience Summary (OES) text is imported.
The SIF labels are deliberately *weak labels*: documented fatalities/serious
injuries are candidates for the positive class; documented no-injury near
misses/property-only events are candidates for the negative class. They are
not a substitute for expert SIF classification.

Usage:
  python scripts/import_public_doe_reports.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import con, init_db  # noqa: E402
from app.services.engine import analyze_text  # noqa: E402

ARCHIVE = ROOT / "data" / "public_doe_oes"
TARGET_PER_CLASS = 50
USER_AGENT = "SIF-Sentinel-public-safety-research/1.0"

# The DOE archive uses a lower-case prefix through 2005 and OES_ thereafter.
ISSUES = [(year, issue) for year in range(2004, 2011) for issue in range(1, 25)]
POSITIVE = re.compile(
    r"\b(?:died|was killed|were killed|fatal injur(?:y|ies)|fatality|lost (?:his|her|a) (?:finger|hand|arm|leg|eye))\b"
    r"|\b(?:worker|employee|operator|technician|mechanic|contractor|driver|electrician|victim)\b[^.]{0,90}\b(?:suffered|sustained|received|required surgery for|was hospitali[sz]ed for)\b[^.]{0,90}\b(?:serious|severe|amputat|hospital|fracture)"
    r"|\b(?:suffered|sustained|received)\s+(?:a\s+)?(?:serious|severe)\s+(?:[a-z-]+\s+){0,3}injur(?:y|ies|ed)\b",
    re.I,
)
NEGATIVE = re.compile(r"\b(no (?:one was )?injured|no personnel (?:were )?injur|no injur(?:y|ies)|without injur|near miss|uninjured|property damage only)\b", re.I)
ORPS = re.compile(r"(?:ORPS|OR)\s+Report\s*:?\s*\(?([A-Z0-9][A-Z0-9-]{4,}-(?:19|20)\d{2}-\d{4})", re.I)
MONTH = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+(20\d{2})\b")


def url_for(year: int, issue: int) -> str:
    directory = f"oesummary{year}"
    name = f"oe{year}-{issue:02}.pdf" if year <= 2005 else f"OES_{year}-{issue:02}.pdf"
    return f"https://ehss.energy.gov/oesummary/{directory}/{name}"


def download(url: str, path: Path) -> bool:
    if path.exists() and path.stat().st_size > 5000:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
        if not data.startswith(b"%PDF"):
            return False
        path.write_bytes(data)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def sentences(text: str) -> list[str]:
    return [clean(x) for x in re.split(r"(?<=[.!?])\s+(?=[A-Z])", clean(text)) if len(clean(x)) >= 45]


def report_candidates(pdf: Path, url: str, issue_year: int) -> list[dict]:
    try:
        pages = [page.extract_text() or "" for page in PdfReader(str(pdf)).pages]
    except Exception:
        return []
    text = clean(" ".join(pages))
    # Around each explicit DOE ORPS identifier is a specific official event summary.
    # Keep the extraction deliberately local: longer article-wide windows can join
    # a no-injury case to a later injury comparison and corrupt its weak label.
    results = []
    for match in ORPS.finditer(text):
        # Capture one original event around its source identifier. Starting at
        # the nearest dated event avoids drawing labels from an article's
        # generic safety advice or from a comparison event on the next page.
        pre = text[max(0, match.start() - 1100):match.start()]
        starts = list(re.finditer(r"\bOn\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+(?:19|20)\d{2}\b", pre))
        begin = max(0, match.start() - 1100) + (starts[-1].start() if starts else max(0, len(pre) - 500))
        anchor = clean(text[begin:match.end()])
        event_sentences = sentences(clean(text[begin:min(len(text), match.end() + 750)]))
        evidence = " ".join(event_sentences)[:2200]
        # The documented outcome must appear before the explicit ORPS record
        # identifier. Context is retained for the operator, but cannot decide
        # the label for a neighbouring/related event.
        positive = bool(POSITIVE.search(anchor))
        negative = bool(NEGATIVE.search(anchor))
        # Do not include ambiguous records or records stating both outcomes.
        if positive == negative:
            continue
        reference = match.group(1).upper()
        title = clean(event_sentences[0] if event_sentences else anchor)[:180]
        event_date = None
        for sentence in [anchor]:
            found = MONTH.search(sentence)
            if found:
                event_date = date.fromisoformat(f"{found.group(2)}-{['January','February','March','April','May','June','July','August','September','October','November','December'].index(found.group(1))+1:02}-01")
                break
        results.append({
            "id": "DOE-" + hashlib.sha1(reference.encode()).hexdigest()[:12].upper(),
            "external_id": reference,
            "title": title,
            "narrative": evidence[:2200],
            "report_date": str(event_date or date(issue_year, 1, 1)),
            "label": 1 if positive else 0,
            "source_url": url,
        })
    # Some older OES articles identify individual events without a machine-readable
    # ORPS reference. They remain usable public reports when the original dated
    # event text explicitly states a no-injury/near-miss outcome. We retain the
    # PDF URL and derive only a stable local identifier, never a new narrative.
    for dated in re.finditer(r"\bOn\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+((?:19|20)\d{2})\b", text):
        following = text[dated.start(): min(len(text), dated.start() + 1400)]
        next_dated = re.search(r"\bOn\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+(?:19|20)\d{2}\b", following[20:])
        if next_dated:
            following = following[:next_dated.start() + 20]
        anchor = clean(following[:800])
        if POSITIVE.search(anchor) or not NEGATIVE.search(anchor):
            continue
        evidence = " ".join(sentences(clean(following[:1500])))[:2200]
        reference = "OES-" + hashlib.sha1((url + anchor[:450]).encode()).hexdigest()[:14].upper()
        if any(existing["external_id"] == reference for existing in results):
            continue
        month = ["January","February","March","April","May","June","July","August","September","October","November","December"].index(dated.group(1)) + 1
        results.append({
            "id": "DOE-" + hashlib.sha1(reference.encode()).hexdigest()[:12].upper(),
            "external_id": reference,
            "title": clean(sentences(anchor)[0] if sentences(anchor) else anchor)[:180],
            "narrative": evidence,
            "report_date": f"{dated.group(3)}-{month:02}-{int(dated.group(2)):02}",
            "label": 0,
            "source_url": url,
        })
    return results


def import_records(records: list[dict]) -> tuple[int, int]:
    init_db()
    database = con()
    added = skipped = 0
    for record in records:
        exists = database.execute("SELECT 1 FROM incidents WHERE id=?", (record["id"],)).fetchone()
        if exists:
            skipped += 1
            continue
        analysis = analyze_text(record["narrative"])
        analysis["provenance"] = {
            "source_type": "public_verified_doe_oes",
            "publisher": "U.S. Department of Energy",
            "source_url": record["source_url"],
            "source_report_id": record["external_id"],
            "source_title": record["title"],
            "label_basis": "Documented serious-injury/fatality outcome" if record["label"] else "Documented no-injury near-miss or property-only outcome",
            "label_note": "Weak label from a public source. It is not expert SIF adjudication.",
        }
        analysis["sif_weak_label"] = record["label"]
        database.execute(
            "INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record["id"], record["report_date"], "DOE public report", "Unspecified", record["narrative"],
                "public_verified", analysis["sif_probability"], analysis["risk"], None, record["label"], "weak_label",
                json.dumps(analysis), "Pending", None, None, date.today().isoformat(),
            ),
        )
        added += 1
    database.commit()
    database.close()
    return added, skipped


def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    positives: dict[str, dict] = {}
    negatives: dict[str, dict] = {}
    downloaded = 0
    local_only = "--local-only" in sys.argv
    local_issues = []
    if local_only:
        for pdf in sorted(ARCHIVE.glob("OES_????-??.pdf")):
            match = re.fullmatch(r"OES_(\d{4})-(\d{2})", pdf.stem)
            if match:
                local_issues.append((int(match.group(1)), int(match.group(2))))
    for year, issue in (local_issues if local_only else ISSUES):
        url = url_for(year, issue)
        local = ARCHIVE / f"OES_{year}-{issue:02}.pdf"
        if not local.exists() and not download(url, local):
            continue
        downloaded += 1
        for record in report_candidates(local, url, year):
            bucket = positives if record["label"] else negatives
            bucket.setdefault(record["external_id"], record)
        if len(positives) >= TARGET_PER_CLASS and len(negatives) >= TARGET_PER_CLASS:
            break
    negative_only = "--negative-only" in sys.argv
    selected = list(negatives.values())[:TARGET_PER_CLASS] if negative_only else list(positives.values())[:TARGET_PER_CLASS] + list(negatives.values())[:TARGET_PER_CLASS]
    if len(negatives) < TARGET_PER_CLASS or (not negative_only and len(positives) < TARGET_PER_CLASS):
        raise SystemExit(f"Only found {len(positives)} documented serious-injury/fatality and {len(negatives)} documented no-injury candidates after {downloaded} files; no partial import made.")
    manifest = ROOT / "data" / "public_verified_doe_weak_labels.json"
    manifest.write_text(json.dumps(selected, indent=2), encoding="utf-8")
    added, skipped = import_records(selected)
    print(f"Downloaded={downloaded} selected={len(selected)} positives={sum(x['label'] for x in selected)} negatives={sum(not x['label'] for x in selected)} imported={added} already_present={skipped}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()
