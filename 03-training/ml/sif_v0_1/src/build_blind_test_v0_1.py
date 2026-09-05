"""Build a leakage-screened, unlabeled human-review test set for SIF NLP v0.1.

This script intentionally never reads or uses target labels, model outputs, or scores
when sampling.  It only uses training and unresolved files as protected-record
references for overlap removal.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
ML_ROOT = ROOT / "03-training" / "ml" / "sif_v0_1"
DATA = ML_ROOT / "data"
OUT = DATA / "blind_test"
TRAINING = DATA / "ai_labeling" / "training_labels_v0_1.csv"
UNRESOLVED = DATA / "ai_labeling" / "unresolved_after_pass_c.csv"
CANDIDATES = DATA / "candidate_pool.csv"
HOLDOUT_POLICY = ROOT / "04-data" / "validation-datasets" / "15_REPORTS" / "HOLDOUT_POLICY.md"
VALIDATION_POLICY = ROOT / "01-app" / "backend" / "app" / "reference" / "validation_policy.json"
DUPLICATE_FILES = [
    ROOT / "04-data" / "validation-datasets" / "13_DUPLICATE_ANALYSIS" / name
    for name in ("narrative_duplicates.csv", "exact_duplicates.csv", "semantic_duplicate_candidates.csv")
]

SEED = 20260830
TARGET_COUNT = 75
OUTPUT_FIELDS = [
    "test_id", "source", "source_record_id", "source_year", "narrative",
    "activity_if_known", "location_if_known", "source_native_outcome",
    "reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence", "reviewer_notes",
    "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence", "second_reviewer_notes",
    "disagreement_resolution", "adjudicated_label", "adjudication_locked",
]
LABEL_FIELDS = [
    "test_id", "source", "source_record_id", "source_year", "narrative",
    "activity_if_known", "location_if_known", "source_native_outcome",
    "reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence", "reviewer_notes",
    "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence", "second_reviewer_notes",
    "disagreement_resolution", "adjudication_locked",
]
BLIND_SAFE_FIELDS = frozenset(OUTPUT_FIELDS)
STOPWORDS = {
    "the", "and", "with", "from", "that", "while", "when", "were", "was",
    "into", "onto", "over", "under", "during", "employee", "injured", "worker",
    "work", "site", "oil", "gas", "incident", "report", "injury", "sustained",
}


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).split())


def normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def compact_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).casefold())


def identifiers(row: pd.Series) -> set[str]:
    source_id = clean_text(row.get("source_record_id", ""))
    candidate_id = clean_text(row.get("candidate_id", ""))
    values = {candidate_id, source_id}
    if source_id:
        values.add(f"OSHA-SIR-{source_id}")
    return {compact_id(value) for value in values if value}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def token_3grams(text: str) -> set[tuple[str, str, str]]:
    tokens = text.split()
    return set(zip(tokens, tokens[1:], tokens[2:]))


def build_near_duplicate_index(texts: list[str]) -> tuple[list[set[tuple[str, str, str]]], dict[tuple[str, str, str], list[int]]]:
    grams_by_text = [token_3grams(text) for text in texts]
    inverted: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, grams in enumerate(grams_by_text):
        for gram in grams:
            inverted[gram].append(index)
    return grams_by_text, inverted


def high_similarity_match(
    text: str,
    reference_texts: list[str],
    reference_grams: list[set[tuple[str, str, str]]],
    inverted_index: dict[tuple[str, str, str], list[int]],
) -> tuple[float, float] | None:
    """Find only plausible matches through a shingle index, then verify exactly.

    This is deterministic duplicate detection. It is intentionally not a TF-IDF,
    embedding, or SIF-model pass.
    """
    grams = token_3grams(text)
    if not grams:
        return None
    shared = Counter(index for gram in grams for index in inverted_index.get(gram, []))
    for index, intersection in shared.items():
        reference = reference_grams[index]
        jaccard = intersection / (len(grams) + len(reference) - intersection)
        if jaccard >= 0.82:
            return jaccard, SequenceMatcher(None, text, reference_texts[index], autojunk=False).ratio()
        # A very high character sequence match necessarily shares many token
        # shingles; only these plausible cases merit the exact character check.
        lengths_are_close = 0.85 <= len(text) / max(1, len(reference_texts[index])) <= 1.15
        if lengths_are_close and jaccard >= 0.40:
            sequence = SequenceMatcher(None, text, reference_texts[index], autojunk=False).ratio()
            if sequence >= 0.92:
                return jaccard, sequence
    return None


def build_reference_sets(training: pd.DataFrame, unresolved: pd.DataFrame) -> tuple[set[str], set[str], set[str], list[str]]:
    protected_ids, exact_texts, normalized_texts, texts = set(), set(), set(), []
    for frame in (training, unresolved):
        for _, row in frame.iterrows():
            protected_ids.update(identifiers(row))
            text = clean_text(row.get("narrative", ""))
            norm = normalized_text(text)
            if text:
                exact_texts.add(text)
                normalized_texts.add(norm)
                texts.append(norm)
    return protected_ids, exact_texts, normalized_texts, texts


def duplicate_group_maps(candidates: pd.DataFrame) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    id_to_groups: dict[str, set[str]] = defaultdict(set)
    group_to_ids: dict[str, set[str]] = defaultdict(set)
    for _, row in candidates.iterrows():
        group = clean_text(row.get("duplicate_group", ""))
        if not group:
            continue
        for identifier in identifiers(row):
            id_to_groups[identifier].add(group)
            group_to_ids[group].add(identifier)
    for path in DUPLICATE_FILES:
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path, dtype=str).fillna("")
        for _, row in frame.iterrows():
            group = clean_text(row.get("duplicate_group", ""))
            record = compact_id(row.get("record_id", ""))
            if group and record:
                id_to_groups[record].add(group)
                group_to_ids[group].add(record)
    return id_to_groups, group_to_ids


def activity_context(row: pd.Series) -> str:
    text = normalized_text(f"{row.get('activity_if_known', '')} {row.get('narrative', '')}")
    patterns = [
        ("drilling", r"\b(drill|drilling|rig floor|wellhead|casing|derrick)\b"),
        ("lifting_materials", r"\b(crane|hoist|lift|forklift|rigg|pipe)\b"),
        ("vehicle_transport", r"\b(truck|vehicle|drive|road|trailer|atv|utv)\b"),
        ("process_pressure", r"\b(pressure|valve|line|tank|pump|hydraulic|steam)\b"),
        ("electrical", r"\b(electric|arc flash|voltage|transformer|energ)\b"),
        ("maintenance", r"\b(maintenance|repair|service|install|remov|clean)\b"),
        ("fall_access", r"\b(fall|ladder|stair|scaffold|excavat|platform)\b"),
        ("chemical_fire", r"\b(chemical|burn|fire|flame|gas|fuel|acid)\b"),
        ("rotating_mechanical", r"\b(belt|pulley|winch|motor|machine|spool|tongs)\b"),
    ]
    matches = [name for name, pattern in patterns if re.search(pattern, text)]
    return "+".join(matches[:2]) if matches else "other_operations"


def activity_signature(row: pd.Series) -> str:
    tokens = [token for token in normalized_text(row.get("activity_if_known", "")).split() if token not in STOPWORDS]
    return " ".join(tokens[:3]) or activity_context(row)


def source_outcome_bucket(value: object) -> str:
    text = normalized_text(value)
    parts = []
    for label, token in (("hospitalized", "hospitalized 1"), ("amputation", "amputation 1"), ("eye_loss", "loss of eye 1")):
        if token in text:
            parts.append(label)
    return "+".join(parts) or "other_or_unspecified"


def length_band(length: int) -> str:
    if length < 180:
        return "short"
    if length < 360:
        return "medium"
    if length < 700:
        return "long"
    return "very_long"


def location_bucket(value: object) -> str:
    text = clean_text(value)
    return text.rsplit(",", 1)[-1].strip() if "," in text else (text or "unspecified")


def select_diverse(eligible: pd.DataFrame, count: int) -> pd.DataFrame:
    """Greedy deterministic selection using only observable source characteristics."""
    rng = random.Random(SEED)
    pool = eligible.copy()
    pool["_context"] = pool.apply(activity_context, axis=1)
    pool["_activity"] = pool.apply(activity_signature, axis=1)
    pool["_outcome"] = pool["source_native_outcome"].map(source_outcome_bucket)
    pool["_length"] = pool["narrative"].map(lambda value: length_band(len(clean_text(value))))
    pool["_location"] = pool["location_if_known"].map(location_bucket)
    pool["_tie"] = [rng.random() for _ in range(len(pool))]
    dimensions = ["source", "source_year", "_context", "_activity", "_outcome", "_length", "_location"]
    frequencies = {column: Counter(pool[column].astype(str)) for column in dimensions}
    chosen, selected_counts = [], {column: Counter() for column in dimensions}
    remaining = pool.sort_values(["_tie", "candidate_id"]).to_dict("records")
    while remaining and len(chosen) < count:
        def score(row: dict) -> tuple[float, float, str]:
            diversity = sum(1 / (1 + selected_counts[column][str(row[column])]) for column in dimensions)
            rarity = sum(1 / frequencies[column][str(row[column])] for column in dimensions)
            return diversity + 0.25 * rarity, row["_tie"], str(row["candidate_id"])
        best_index = max(range(len(remaining)), key=lambda index: score(remaining[index]))
        row = remaining.pop(best_index)
        chosen.append(row)
        for column in dimensions:
            selected_counts[column][str(row[column])] += 1
    return pd.DataFrame(chosen)


def require_blind(frame: pd.DataFrame) -> None:
    unexpected = [column for column in frame.columns if column not in BLIND_SAFE_FIELDS]
    if unexpected:
        raise ValueError(f"Blind output contains prohibited columns: {unexpected}")
    reviewer_columns = [column for column in frame.columns if "reviewer" in column or column == "adjudicated_label"]
    if frame[reviewer_columns].fillna("").astype(str).apply(lambda column: column.str.strip().ne("")).any().any():
        raise ValueError("A reviewer field is prefilled.")


def validation_locked_mask(frame: pd.DataFrame, locked_sources: set[str], locked_record_flags: set[str]) -> pd.Series:
    source_series = frame["source"].astype(str).str.strip().str.casefold()
    mask = source_series.isin(locked_sources)
    for flag in locked_record_flags:
        if flag in frame.columns:
            mask = mask | frame[flag].map(lambda value: str(value).strip().casefold() in {"1", "true", "yes", "locked"})
    return mask


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if "IOGP 2025" not in HOLDOUT_POLICY.read_text(encoding="utf-8"):
        raise ValueError("Expected holdout policy could not be verified.")
    policy = json.loads(VALIDATION_POLICY.read_text(encoding="utf-8"))
    locked_sources = {str(value).strip().casefold() for value in policy["locked_sources"] if str(value).strip()}
    locked_record_flags = {str(value).strip() for value in policy["locked_record_flags"] if str(value).strip()}
    training = pd.read_csv(TRAINING, dtype=str).fillna("")
    unresolved = pd.read_csv(UNRESOLVED, dtype=str).fillna("")
    candidates = pd.read_csv(CANDIDATES, dtype=str).fillna("")
    protected_ids, protected_exact, protected_normalized, protected_texts = build_reference_sets(training, unresolved)
    protected_grams, protected_index = build_near_duplicate_index(protected_texts)
    id_to_groups, _ = duplicate_group_maps(candidates)
    protected_groups = set().union(*(id_to_groups.get(identifier, set()) for identifier in protected_ids))

    # Strict source screen: candidate pool's narrow NAICS oil/gas screen only.
    validation_locked = validation_locked_mask(candidates, locked_sources, locked_record_flags)
    working = candidates[candidates["industry_relevance"].eq("verified_naics_oil_gas") & ~validation_locked].copy()
    audit = Counter(input_candidate_records=int(len(candidates)), source_screened_records=int(len(working)))
    survivors = []
    near_matches: list[dict] = []
    excluded_ids_by_reason: dict[str, set[str]] = defaultdict(set)
    for _, row in working.iterrows():
        candidate_id = clean_text(row["candidate_id"])
        ids = identifiers(row)
        narrative = clean_text(row["narrative"])
        norm = normalized_text(narrative)
        groups = set().union(*(id_to_groups.get(identifier, set()) for identifier in ids))
        reason = ""
        if ids & protected_ids:
            reason = "matching_candidate_or_source_id"
        elif narrative in protected_exact:
            reason = "exact_narrative_duplicate"
        elif norm in protected_normalized:
            reason = "normalized_text_duplicate"
        elif groups & protected_groups:
            reason = "known_duplicate_group_overlap"
        if reason:
            audit[reason] += 1
            excluded_ids_by_reason[reason].add(candidate_id)
            continue
        # Deterministic high-similarity duplicate review against every protected narrative.
        near_match = high_similarity_match(norm, protected_texts, protected_grams, protected_index)
        if near_match is not None:
            jaccard, sequence = near_match
            near_matches.append({"candidate_id": candidate_id, "token_3gram_jaccard": round(jaccard, 4), "sequence_ratio": round(sequence, 4)})
            audit["high_similarity_near_duplicate"] += 1
            excluded_ids_by_reason["high_similarity_near_duplicate"].add(candidate_id)
            continue
        survivors.append(row)

    eligible = pd.DataFrame(survivors)
    if len(eligible) == 0:
        raise RuntimeError("No leakage-safe candidate reports remain after exclusions.")
    selected = select_diverse(eligible, min(TARGET_COUNT, len(eligible))).copy()
    selected.insert(0, "test_id", [f"BT-V0.1-{index:03d}" for index in range(1, len(selected) + 1)])
    for column in ("reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence", "reviewer_notes", "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence", "second_reviewer_notes", "disagreement_resolution", "adjudicated_label", "adjudication_locked"):
        selected[column] = ""
    blind = selected[OUTPUT_FIELDS].fillna("")
    require_blind(blind)
    if blind["source_record_id"].duplicated().any() or blind["narrative"].map(normalized_text).duplicated().any():
        raise ValueError("Selection contains duplicate report IDs or normalized narratives.")

    blind_path = OUT / "blind_test_v0_1.csv"
    sheet_path = OUT / "blind_test_labeling_sheet.csv"
    blind.to_csv(blind_path, index=False, encoding="utf-8", lineterminator="\n")
    blind[LABEL_FIELDS].to_csv(sheet_path, index=False, encoding="utf-8", lineterminator="\n")

    selected_ids = set(blind["source_record_id"].map(compact_id)) | set(blind["test_id"].map(compact_id))
    training_ids = set().union(*(identifiers(row) for _, row in training.iterrows()))
    unresolved_ids = set().union(*(identifiers(row) for _, row in unresolved.iterrows()))
    selected_groups = set().union(*(id_to_groups.get(compact_id(value), set()) for value in blind["source_record_id"]))
    forbidden_columns = [column for column in blind.columns if any(term in column.casefold() for term in ("prediction", "score", "consensus", "provenance", "pass_"))]
    integrity = {
        "report_count": int(len(blind)),
        "unique_test_ids": int(blind["test_id"].nunique()),
        "unique_source_record_ids": int(blind["source_record_id"].nunique()),
        "duplicate_normalized_narratives": int(blind["narrative"].map(normalized_text).duplicated().sum()),
        "training_overlap": int(len(selected_ids & training_ids)),
        "unresolved_overlap": int(len(selected_ids & unresolved_ids)),
        "known_duplicate_group_overlap": int(len(selected_groups & protected_groups)),
        "validation_locked_overlap": int(blind["source"].astype(str).str.strip().str.casefold().isin(locked_sources).sum()),
        "prefilled_reviewer_fields": False,
        "model_prediction_columns": forbidden_columns,
        "validation_locked_sources_excluded": policy["locked_sources"],
        "status": "passed",
    }
    if len(blind) != TARGET_COUNT:
        integrity["status"] = "maximum_available_below_target"
    if any(value for key, value in integrity.items() if key in {"training_overlap", "unresolved_overlap", "known_duplicate_group_overlap", "duplicate_normalized_narratives"}):
        raise ValueError(f"Integrity failure: {integrity}")
    if forbidden_columns:
        raise ValueError(f"Prediction-like columns present: {forbidden_columns}")

    lengths = blind["narrative"].map(lambda value: len(clean_text(value)))
    manifest = {
        "dataset": "blind_test_v0_1",
        "creation_timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selection_seed": SEED,
        "selection_method": "deterministic greedy diversity sampling using source, year, activity/context, source-native outcome, narrative length, and location only",
        "selected_count": int(len(blind)),
        "selected_ids": blind["source_record_id"].tolist(),
        "source_distribution": dict(Counter(blind["source"])),
        "year_distribution": dict(sorted(Counter(blind["source_year"]).items())),
        "narrative_length_summary_characters": {"min": int(lengths.min()), "max": int(lengths.max()), "mean": round(float(lengths.mean()), 2), "median": float(lengths.median())},
        "dataset_hashes_sha256": {"blind_test_v0_1.csv": sha256(blind_path), "blind_test_labeling_sheet.csv": sha256(sheet_path)},
        "excluded_overlap_counts": {key: int(audit.get(key, 0)) for key in ("matching_candidate_or_source_id", "exact_narrative_duplicate", "normalized_text_duplicate", "known_duplicate_group_overlap", "high_similarity_near_duplicate")},
        "integrity": integrity,
    }
    audit_payload = {
        "dataset": "blind_test_v0_1",
        "selection_seed": SEED,
        "source_policy": "Only candidate_pool records marked verified_naics_oil_gas were eligible; IOGP 2025 is excluded as validation-locked.",
        "counts": {key: int(value) for key, value in audit.items()},
        "excluded_overlap_counts": manifest["excluded_overlap_counts"],
        "near_duplicate_method": {"type": "token_3gram_jaccard_or_character_sequence", "thresholds": {"token_3gram_jaccard": 0.82, "character_sequence_ratio": 0.92}, "matched_count": int(len(near_matches))},
        "integrity": integrity,
        "source_files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in [CANDIDATES, TRAINING, UNRESOLVED, HOLDOUT_POLICY, *DUPLICATE_FILES]],
    }
    (OUT / "blind_test_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "blind_test_exclusion_audit.json").write_text(json.dumps(audit_payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"integrity": integrity, "manifest": manifest}, indent=2))


if __name__ == "__main__":
    main()
