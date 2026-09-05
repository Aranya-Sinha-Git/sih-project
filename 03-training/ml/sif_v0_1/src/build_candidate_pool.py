"""Build a traceable incident-only candidate pool and an unlabeled human review queue."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from audit_labels import audit
from preprocess import clean_narrative, normalize_text, project_root, text_hash

ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
SOURCE = project_root() / "04-data" / "validation-datasets" / "04_OSHA" / "OIL_GAS_SUBSET" / "osha_sir_oil_gas_subset.csv"
FIELDS = ["candidate_id", "source", "source_record_id", "source_year", "industry_relevance", "report_type_if_known", "activity_if_known", "location_if_known", "narrative", "source_native_outcome", "source_native_classification", "duplicate_group", "sif_potential", "sif_label_status", "notes"]
QUEUE_FIELDS = ["candidate_id", "source", "source_record_id", "narrative", "source_native_outcome", "activity_if_known", "reviewer_sif_label", "reviewer_confidence", "reviewer_notes", "second_reviewer_label", "adjudicated_label"]
TRUSTED_NAICS = ("211", "213111", "213112", "32411", "486", "237120")


def relevance(naics: str) -> tuple[str, str]:
    code = (naics or "").strip()
    if code.startswith(TRUSTED_NAICS):
        return "verified_naics_oil_gas", f"Primary NAICS {code} matched the narrow oil/gas inclusion list."
    return "ambiguous_existing_filter", "Retained from the prior broad OSHA candidate filter; requires industry review before model use."


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def select_queue(rows: list[dict], maximum: int = 500) -> list[dict]:
    """Round-robin across source-native event/outcome buckets; does not use proxy SIF labels."""
    eligible = [row for row in rows if row["industry_relevance"] == "verified_naics_oil_gas"]
    buckets: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for row in eligible:
        length_band = min(len(row["narrative"]) // 400, 4)
        bucket = (row["activity_if_known"], row["source_native_outcome"], length_band)
        buckets[bucket].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: row["candidate_id"])
    selected: list[dict] = []; selected_groups: set[str] = set()
    keys = sorted(buckets)
    while keys and len(selected) < maximum:
        next_keys = []
        for key in keys:
            while buckets[key] and buckets[key][0]["duplicate_group"] in selected_groups:
                buckets[key].pop(0)
            if buckets[key] and len(selected) < maximum:
                chosen = buckets[key].pop(0); selected.append(chosen); selected_groups.add(chosen["duplicate_group"])
            if buckets[key]: next_keys.append(key)
        keys = next_keys
    return [{field: row.get(field, "") for field in QUEUE_FIELDS} for row in selected]


def assign_tfidf_near_duplicate_groups(rows: list[dict]) -> int:
    """Conservatively connect only very similar verified-NAICS narratives.

    The broad OSHA remainder is explicitly ambiguous and is not queued.  Its exact
    duplicate groups are still preserved; future inclusion requires a fresh full
    duplicate review before any supervised split.
    """
    eligible = [row for row in rows if row["industry_relevance"] == "verified_naics_oil_gas"]
    if len(eligible) < 2: return 0
    matrix = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30000, strip_accents="unicode").fit_transform([row["narrative"] for row in eligible])
    distances, neighbors = NearestNeighbors(n_neighbors=min(4, len(eligible)), metric="cosine", algorithm="brute", n_jobs=-1).fit(matrix).kneighbors(matrix)
    parent = list(range(len(eligible)))
    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]; index = parent[index]
        return index
    def union(left, right):
        left, right = find(left), find(right)
        if left != right: parent[right] = left
    for left, (row_distances, row_neighbors) in enumerate(zip(distances, neighbors)):
        for distance, right in zip(row_distances[1:], row_neighbors[1:]):
            if 1 - float(distance) >= 0.92: union(left, int(right))
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(eligible)): components[find(index)].append(index)
    near_groups = 0
    for members in components.values():
        if len(members) > 1:
            near_groups += 1
            group = "osha-near-" + hashlib.sha256("|".join(sorted(eligible[i]["candidate_id"] for i in members)).encode()).hexdigest()[:12]
            for index in members:
                eligible[index]["duplicate_group"] = group
                eligible[index]["notes"] += " TF-IDF near-duplicate group assigned (cosine similarity >= 0.92)."
    return near_groups


def build() -> dict:
    DATA.mkdir(parents=True, exist_ok=True); REPORTS.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists(): raise FileNotFoundError(SOURCE)
    rows: list[dict] = []
    duplicate_ids: dict[str, str] = {}
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        for source_row in csv.DictReader(handle):
            narrative = clean_narrative(source_row.get("Final Narrative"))
            if not narrative: continue
            record_id = (source_row.get("ID") or "").strip()
            normalized_hash = text_hash(narrative)
            duplicate_group = duplicate_ids.setdefault(normalized_hash, f"osha-text-{normalized_hash[:12]}")
            industry_relevance, note = relevance(source_row.get("Primary NAICS", ""))
            outcome = "; ".join(f"{name}={source_row.get(name, '')}" for name in ("Hospitalized", "Amputation", "Loss of Eye"))
            rows.append({
                "candidate_id": f"OSHA-SIR-{record_id}", "source": "OSHA_SIR", "source_record_id": record_id,
                "source_year": (source_row.get("EventDate") or "")[-4:], "industry_relevance": industry_relevance,
                "report_type_if_known": "Incident", "activity_if_known": source_row.get("EventTitle", ""),
                "location_if_known": ", ".join(part for part in (source_row.get("City", ""), source_row.get("State", "")) if part),
                "narrative": narrative, "source_native_outcome": outcome, "source_native_classification": "OSHA severe injury report",
                "duplicate_group": duplicate_group, "sif_potential": "", "sif_label_status": "unresolved", "notes": note,
            })
    # Existing data audit documents no exact normalized duplicates in the prior master.  Assign deterministic exact
    # groups and perform a conservative TF-IDF near-duplicate pass on the review-eligible narrow-NAICS subset.
    near_groups = assign_tfidf_near_duplicate_groups(rows)
    write_csv(DATA / "candidate_pool.csv", rows, FIELDS)
    queue = select_queue(rows)
    write_csv(DATA / "labeling_queue.csv", queue, QUEUE_FIELDS)
    reviewed = DATA / "reviewed_labels.csv"
    if not reviewed.exists():
        write_csv(reviewed, [], ["candidate_id", "source", "narrative", "adjudicated_label", "label_provenance", "reviewer", "reviewed_at", "notes", "duplicate_group"])
    label_audit = audit()
    summary = {
        "candidate_pool_records": len(rows), "verified_naics_oil_gas": sum(r["industry_relevance"] == "verified_naics_oil_gas" for r in rows),
        "ambiguous_existing_filter": sum(r["industry_relevance"] == "ambiguous_existing_filter" for r in rows),
        "tfidf_near_duplicate_groups_verified_naics": near_groups, "labeling_queue_records": len(queue), "source": str(SOURCE), "label_audit": label_audit,
        "excluded_sources": ["BSEE: incident/aggregate grain not reconciled", "IOGP 2025: validation locked", "BRSR/tenders/LSR: reference-only", "NIOSH: records unavailable"],
    }
    (REPORTS / "candidate_pool_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
