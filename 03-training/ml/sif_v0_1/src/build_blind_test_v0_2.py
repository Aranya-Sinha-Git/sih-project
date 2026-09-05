"""Create the immutable v0.2 blind-human review release.

This builder is intentionally separate from the historical v0.1 builder.  It
uses no labels, model outputs, scores, or retrieval results to select records.
It may be run exactly once for a release directory; an existing release is a
hard error rather than an opportunity to silently repackage a blind set.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from build_blind_test_v0_1 import (
    DATA,
    DUPLICATE_FILES,
    HOLDOUT_POLICY,
    ML_ROOT,
    ROOT,
    TRAINING,
    UNRESOLVED,
    build_near_duplicate_index,
    build_reference_sets,
    clean_text,
    compact_id,
    duplicate_group_maps,
    high_similarity_match,
    identifiers,
    normalized_text,
    select_diverse,
)


RELEASE_VERSION = "v0.2"
DATASET = "blind_test_v0_2"
TARGET_COUNT = 75
FREEZE_CREATED_AT = "2026-09-05T00:00:00+00:00"
OUT = DATA / DATASET
CANDIDATES = DATA / "candidate_pool_v0_2.csv"
PACKET_NAME = "blind_test_v0_2_reviewer_packet.csv"
MANIFEST_NAME = "blind_test_v0_2_freeze_manifest.json"
EXCLUSION_AUDIT_NAME = "blind_test_v0_2_exclusion_audit.json"
VALIDATION_POLICY = ROOT / "01-app" / "backend" / "app" / "reference" / "validation_policy.json"
ARTIFACTS = ML_ROOT / "artifacts" / "supervised"
PREPROCESSING = ML_ROOT / "src" / "preprocess.py"

IDENTITY_FIELDS = [
    "test_id", "candidate_id", "source", "source_record_id", "source_year", "narrative",
    "activity_if_known", "location_if_known", "source_native_outcome",
]
REVIEW_METADATA_FIELDS = [
    "reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence", "reviewer_notes",
    "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence", "second_reviewer_notes",
    "adjudicated_label", "adjudicator_id", "adjudication_date", "disagreement_resolution", "adjudication_locked",
    "exclusion_reason", "excluded_by", "excluded_at",
]
REVIEWER_PACKET_FIELDS = IDENTITY_FIELDS + REVIEW_METADATA_FIELDS
FORBIDDEN_FIELD_TOKENS = (
    "prediction", "score", "probability", "model", "ai_", "consensus", "provenance", "pass_",
    "retrieval", "explanation", "rationale",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_narrative_hash(value: object) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "locked"}


def _load_policy() -> tuple[dict, set[str], set[str]]:
    try:
        policy = json.loads(VALIDATION_POLICY.read_text(encoding="utf-8"))
        version = str(policy["version"]).strip()
        sources = {str(value).strip().casefold() for value in policy["locked_sources"] if str(value).strip()}
        flags = {str(value).strip() for value in policy["locked_record_flags"] if str(value).strip()}
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("Validation policy is missing or invalid.") from error
    if not version or not sources:
        raise ValueError("Validation policy must declare a version and locked sources.")
    return policy, sources, flags


def validation_locked_mask(frame: pd.DataFrame, locked_sources: set[str], locked_record_flags: set[str]) -> pd.Series:
    missing = sorted(flag for flag in locked_record_flags if flag not in frame.columns)
    if missing:
        raise ValueError(f"Validation policy requires absent candidate lock field(s): {missing}")
    source_series = frame["source"].astype(str).str.strip().str.casefold()
    mask = source_series.isin(locked_sources)
    for flag in locked_record_flags:
        mask = mask | frame[flag].map(_truthy)
    return mask


def require_reviewer_safe_packet(frame: pd.DataFrame) -> None:
    if list(frame.columns) != REVIEWER_PACKET_FIELDS:
        raise ValueError("Reviewer packet schema does not exactly match the v0.2 release schema.")
    forbidden = [field for field in frame.columns if any(token in field.casefold() for token in FORBIDDEN_FIELD_TOKENS)]
    if forbidden:
        raise ValueError(f"Reviewer packet contains forbidden model/AI fields: {forbidden}")
    if frame[REVIEW_METADATA_FIELDS].fillna("").astype(str).apply(lambda column: column.str.strip().ne("")).any().any():
        raise ValueError("Reviewer metadata must be blank in the frozen release packet.")


def frozen_model_metadata() -> dict:
    config_path = ARTIFACTS / "threshold.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    identity = str(config["model"])
    if identity == "embedding_logreg":
        model_path = ARTIFACTS / "embedding_logreg.joblib"
    elif identity.startswith("tfidf_"):
        model_path = ARTIFACTS / "tfidf_logreg.joblib"
    else:
        raise ValueError(f"Unsupported frozen model identity: {identity}")
    band = [float(value) for value in config["human_review_band"]]
    if len(band) != 2 or not 0.0 <= band[0] <= band[1] <= 1.0:
        raise ValueError("Frozen review band is invalid.")
    return {
        "model_identity": identity,
        "model_sha256": sha256(model_path),
        "preprocessing_sha256": sha256(PREPROCESSING),
        "configuration_sha256": sha256(config_path),
        "binary_threshold": float(config["sif_threshold"]),
        "review_band": band,
    }


def build_release() -> dict:
    if OUT.exists():
        raise FileExistsError(f"Release directory already exists and is immutable: {OUT}")
    if "IOGP 2025" not in HOLDOUT_POLICY.read_text(encoding="utf-8"):
        raise ValueError("Expected holdout policy could not be verified.")
    policy, locked_sources, locked_record_flags = _load_policy()
    training = pd.read_csv(TRAINING, dtype=str).fillna("")
    unresolved = pd.read_csv(UNRESOLVED, dtype=str).fillna("")
    candidates = pd.read_csv(CANDIDATES, dtype=str).fillna("")
    locked = validation_locked_mask(candidates, locked_sources, locked_record_flags)
    protected_ids, protected_exact, protected_normalized, protected_texts = build_reference_sets(training, unresolved)
    protected_grams, protected_index = build_near_duplicate_index(protected_texts)
    id_to_groups, _ = duplicate_group_maps(candidates)
    protected_groups = set().union(*(id_to_groups.get(identifier, set()) for identifier in protected_ids))
    working = candidates[candidates["industry_relevance"].eq("verified_naics_oil_gas") & ~locked].copy()
    audit = Counter(input_candidate_records=int(len(candidates)), source_screened_records=int(len(working)))
    survivors = []
    for _, row in working.iterrows():
        candidate_id = clean_text(row["candidate_id"])
        row_ids = identifiers(row)
        narrative = clean_text(row["narrative"])
        normalized = normalized_text(narrative)
        groups = set().union(*(id_to_groups.get(identifier, set()) for identifier in row_ids))
        if row_ids & protected_ids:
            audit["matching_candidate_or_source_id"] += 1
        elif narrative in protected_exact:
            audit["exact_narrative_duplicate"] += 1
        elif normalized in protected_normalized:
            audit["normalized_text_duplicate"] += 1
        elif groups & protected_groups:
            audit["known_duplicate_group_overlap"] += 1
        elif high_similarity_match(normalized, protected_texts, protected_grams, protected_index) is not None:
            audit["high_similarity_near_duplicate"] += 1
        else:
            survivors.append(row)
    eligible = pd.DataFrame(survivors)
    if len(eligible) < TARGET_COUNT:
        raise RuntimeError(f"Only {len(eligible)} leakage-safe records remain; expected {TARGET_COUNT}.")
    selected = select_diverse(eligible, TARGET_COUNT).copy()
    selected.insert(0, "test_id", [f"BT-V0.2-{index:03d}" for index in range(1, TARGET_COUNT + 1)])
    for field in REVIEW_METADATA_FIELDS:
        selected[field] = ""
    packet = selected[REVIEWER_PACKET_FIELDS].fillna("")
    require_reviewer_safe_packet(packet)
    if packet["test_id"].duplicated().any() or packet["source_record_id"].duplicated().any():
        raise ValueError("Release selection contains duplicate test or source record IDs.")
    if packet["narrative"].map(normalized_text).duplicated().any():
        raise ValueError("Release selection contains duplicate normalized narratives.")
    selected_identifiers = set().union(*(identifiers(row) for _, row in packet.iterrows()))
    training_ids = set().union(*(identifiers(row) for _, row in training.iterrows()))
    unresolved_ids = set().union(*(identifiers(row) for _, row in unresolved.iterrows()))
    selected_groups = set().union(*(id_to_groups.get(compact_id(value), set()) for value in packet["source_record_id"]))
    integrity = {
        "record_count": int(len(packet)),
        "unique_test_ids": int(packet["test_id"].nunique()),
        "training_identifier_overlap": int(len(selected_identifiers & training_ids)),
        "unresolved_identifier_overlap": int(len(selected_identifiers & unresolved_ids)),
        "known_duplicate_group_overlap": int(len(selected_groups & protected_groups)),
        "locked_source_or_record_overlap": int(locked.loc[candidates.index.isin(selected.index)].sum()),
        "duplicate_normalized_narratives": int(packet["narrative"].map(normalized_text).duplicated().sum()),
    }
    if any(value for key, value in integrity.items() if key not in {"record_count", "unique_test_ids"}):
        raise ValueError(f"Blind release integrity failure: {integrity}")
    OUT.mkdir(parents=True, exist_ok=False)
    packet_path = OUT / PACKET_NAME
    packet.to_csv(packet_path, index=False, encoding="utf-8", lineterminator="\n")
    metadata = frozen_model_metadata()
    records = [
        {
            "test_id": row.test_id,
            "candidate_id": row.candidate_id,
            "source": row.source,
            "source_record_id": row.source_record_id,
            "normalized_narrative_sha256": normalized_narrative_hash(row.narrative),
        }
        for row in packet.itertuples(index=False)
    ]
    manifest = {
        "schema_version": "blind-human-freeze-v0.2",
        "release_version": RELEASE_VERSION,
        "dataset": DATASET,
        "release_status": "frozen_unscored",
        "created_at_utc": FREEZE_CREATED_AT,
        "selection": {"seed": 20260830, "record_count": TARGET_COUNT, "method": "deterministic diversity sampling using observable source fields only"},
        "canonical_packet": {"filename": PACKET_NAME, "sha256": sha256(packet_path)},
        "candidate_pool": {"filename": str(CANDIDATES.relative_to(ML_ROOT)).replace("\\", "/"), "sha256": sha256(CANDIDATES)},
        "validation_policy": {"filename": str(VALIDATION_POLICY.relative_to(ROOT)).replace("\\", "/"), "version": policy["version"], "sha256": sha256(VALIDATION_POLICY), "locked_sources": policy["locked_sources"], "locked_record_flags": policy["locked_record_flags"]},
        "frozen_model": metadata,
        "records": records,
        "integrity": integrity,
    }
    manifest_path = OUT / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / EXCLUSION_AUDIT_NAME).write_text(json.dumps({"dataset": DATASET, "policy_version": policy["version"], "counts": {key: int(value) for key, value in audit.items()}, "integrity": integrity}, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build_release(), indent=2))
