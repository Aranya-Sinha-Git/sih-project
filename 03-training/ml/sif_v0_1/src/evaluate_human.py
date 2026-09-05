"""Evaluate only finalized adjudications for the canonical v0.2 blind release."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from build_blind_test_v0_2 import (
    PREPROCESSING, REVIEWER_PACKET_FIELDS, REVIEW_METADATA_FIELDS,
    ROOT, VALIDATION_POLICY, normalized_narrative_hash,
)
from build_blind_test_v0_3 import (
    ARTIFACTS, CANDIDATES, DATASET, FINALIZATION_POLICY,
    MANIFEST_NAME, OFFICIAL_ATTESTATION_NAME, OFFICIAL_FINALIZATION_MANIFEST_NAME,
    OFFICIAL_FINALIZED_PACKET_NAME, OUT as RELEASE_ROOT, PACKET_NAME,
    sha256,
)
from evaluate import binary_metrics
from predict import POLICY_REVIEW_BAND, predict


class EvaluationError(ValueError):
    """Raised when a release, adjudication, or finalization is unsafe."""


CANONICAL_PACKET = RELEASE_ROOT / PACKET_NAME
CANONICAL_MANIFEST = RELEASE_ROOT / MANIFEST_NAME
CANONICAL_MANIFEST_SHA256 = "c4821727fbcbcdbb1bce7d3dcb6a4e02077931b52a7a2095cbd27f9c7a88ee53"
OFFICIAL_FINALIZED_PACKET = RELEASE_ROOT / OFFICIAL_FINALIZED_PACKET_NAME
OFFICIAL_FINALIZATION_MANIFEST = RELEASE_ROOT / OFFICIAL_FINALIZATION_MANIFEST_NAME
OFFICIAL_ATTESTATION = RELEASE_ROOT / OFFICIAL_ATTESTATION_NAME
FINALIZATION_SCHEMA_VERSION = "blind-human-adjudication-finalization-v0.3"
EVALUATOR_SCHEMA_VERSION = "evaluate-human-finalized-v0.3"
LABELS = {"0": 0, "1": 1, "non-sif": 0, "non_sif": 0, "non sif": 0, "sif": 1, "sif potential": 1, "non-sif potential": 0}
CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as error:
        raise EvaluationError(f"Unable to read reviewer packet: {path}") from error


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is unreadable.") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be a JSON object.")
    return value


def _label(value: object, field: str, row_id: str) -> int | None:
    text = "" if value is None else str(value).strip().casefold()
    if not text:
        return None
    if text not in LABELS:
        raise EvaluationError(f"Unknown {field} '{value}' for {row_id}.")
    return LABELS[text]


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "locked"}


def _require_date(value: object, field: str, row_id: str) -> None:
    text = str(value or "").strip()
    if not text:
        raise EvaluationError(f"{field} is required for {row_id}.")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError(f"{field} must be ISO-8601 for {row_id}.") from error


def _require_confidence(value: object, field: str, row_id: str) -> None:
    if str(value or "").strip().casefold() not in CONFIDENCE_VALUES:
        raise EvaluationError(f"{field} must be one of {sorted(CONFIDENCE_VALUES)} for {row_id}.")


def _require_exact_schema(rows: list[dict[str, Any]], label: str) -> None:
    if not rows:
        raise EvaluationError(f"{label} is empty.")
    actual = list(rows[0].keys())
    if actual != REVIEWER_PACKET_FIELDS or any(list(row.keys()) != actual for row in rows):
        raise EvaluationError(f"{label} schema does not exactly match the v0.2 reviewer packet.")


def canonical_packet_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    """Stable logical CSV bytes: fixed schema and test-ID ordering."""
    row_list = list(rows)
    _require_exact_schema(row_list, "Reviewer packet")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=REVIEWER_PACKET_FIELDS, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in sorted(row_list, key=lambda item: str(item.get("test_id") or "").strip()):
        writer.writerow({field: "" if row.get(field) is None else str(row.get(field)) for field in REVIEWER_PACKET_FIELDS})
    return stream.getvalue().encode("utf-8")


def finalized_packet_sha256(rows: Iterable[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_packet_bytes(rows)).hexdigest()


def frozen_metadata(artifact_dir: Path) -> dict[str, Any]:
    config_path = artifact_dir / "threshold.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        identity, threshold = str(config["model"]), float(config["sif_threshold"])
        band = [float(value) for value in config["human_review_band"]]
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise EvaluationError("Frozen model configuration is missing or invalid.") from error
    if tuple(band) != POLICY_REVIEW_BAND:
        raise EvaluationError(f"Frozen review band {band} does not match policy {POLICY_REVIEW_BAND}.")
    if identity == "embedding_logreg":
        model_path = artifact_dir / "embedding_logreg.joblib"
    elif identity.startswith("tfidf_"):
        model_path = artifact_dir / "tfidf_logreg.joblib"
    else:
        raise EvaluationError(f"Unsupported frozen model identity: {identity}.")
    if not model_path.is_file() or not PREPROCESSING.is_file():
        raise EvaluationError("Frozen model or preprocessing artifact is missing.")
    return {"model_identity": identity, "model_sha256": sha256(model_path), "preprocessing_sha256": sha256(PREPROCESSING), "configuration_sha256": sha256(config_path), "binary_threshold": threshold, "review_band": band, "calibration_status": "uncalibrated"}


def canonical_manifest() -> dict[str, Any]:
    if not CANONICAL_MANIFEST.is_file() or sha256(CANONICAL_MANIFEST) != CANONICAL_MANIFEST_SHA256:
        raise EvaluationError("Canonical freeze manifest hash mismatch.")
    manifest = _read_json(CANONICAL_MANIFEST, "Canonical freeze manifest")
    if manifest.get("schema_version") != "blind-human-freeze-v0.3" or manifest.get("dataset") != DATASET:
        raise EvaluationError("Canonical freeze manifest has an unexpected schema or dataset.")
    return manifest


def finalization_policy() -> dict[str, Any]:
    policy = _read_json(FINALIZATION_POLICY, "Human-review finalization policy")
    try:
        minimum = int(policy["minimum_retained_records"])
        reasons, required = policy["approved_exclusion_reasons"], policy["required_exclusion_approval_fields"]
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationError("Human-review finalization policy is incomplete.") from error
    if policy.get("schema_version") != "human-review-finalization-policy-v1" or not str(policy.get("version") or "").strip() or minimum < 1 or not isinstance(reasons, list) or not reasons or not isinstance(required, list):
        raise EvaluationError("Human-review finalization policy is invalid.")
    return policy


def _validate_packet_identity(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    _require_exact_schema(rows, "Reviewer packet")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise EvaluationError("Canonical freeze manifest records are invalid.")
    expected = {str(record["test_id"]): record for record in records}
    actual_ids = [str(row.get("test_id") or "").strip() for row in rows]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected):
        raise EvaluationError("Reviewer packet test IDs do not exactly match the canonical freeze.")
    for row in rows:
        record = expected[str(row["test_id"]).strip()]
        for field in ("candidate_id", "source", "source_record_id"):
            if str(row.get(field) or "").strip() != str(record.get(field) or "").strip():
                raise EvaluationError(f"Reviewer packet {field} mismatch for {row['test_id']}.")
        if normalized_narrative_hash(row.get("narrative")) != record.get("normalized_narrative_sha256"):
            raise EvaluationError(f"Reviewer packet narrative hash mismatch for {row['test_id']}.")


def _validate_release_anchor(manifest: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    packet = _read_csv(CANONICAL_PACKET)
    _require_exact_schema(packet, "Canonical reviewer packet")
    canonical_packet = manifest.get("canonical_packet") or {}
    if canonical_packet.get("filename") != PACKET_NAME or sha256(CANONICAL_PACKET) != canonical_packet.get("sha256"):
        raise EvaluationError("Canonical blind packet hash mismatch.")
    if any(any(str(row.get(field) or "").strip() for field in REVIEW_METADATA_FIELDS) for row in packet):
        raise EvaluationError("Canonical reviewer packet is not blank before human scoring.")
    if (manifest.get("candidate_pool") or {}).get("sha256") != sha256(CANDIDATES):
        raise EvaluationError("Candidate-pool hash does not match the canonical freeze.")
    policy, current = manifest.get("validation_policy") or {}, _read_json(VALIDATION_POLICY, "Validation policy")
    if policy.get("sha256") != sha256(VALIDATION_POLICY) or policy.get("version") != current.get("version"):
        raise EvaluationError("Validation policy does not match the canonical freeze.")
    final_policy = finalization_policy()
    frozen_policy = manifest.get("finalization_policy") or {}
    if (
        frozen_policy.get("sha256") != sha256(FINALIZATION_POLICY)
        or frozen_policy.get("version") != final_policy.get("version")
        or frozen_policy.get("minimum_retained_records") != final_policy.get("minimum_retained_records")
        or frozen_policy.get("approved_exclusion_reasons") != final_policy.get("approved_exclusion_reasons")
    ):
        raise EvaluationError("Finalization policy does not match the canonical v0.3 freeze.")
    official = manifest.get("official_artifacts") or {}
    if official != {
        "finalized_packet": OFFICIAL_FINALIZED_PACKET_NAME,
        "finalization_manifest": OFFICIAL_FINALIZATION_MANIFEST_NAME,
        "attestation": OFFICIAL_ATTESTATION_NAME,
    }:
        raise EvaluationError("Canonical v0.3 official artifact locations are invalid.")
    frozen, expected_frozen = frozen_metadata(artifact_dir), manifest.get("frozen_model") or {}
    for key in ("model_identity", "model_sha256", "preprocessing_sha256", "configuration_sha256", "binary_threshold", "review_band"):
        if expected_frozen.get(key) != frozen.get(key):
            raise EvaluationError(f"Frozen {key} does not match the canonical freeze.")
    if not isinstance(manifest.get("records"), list) or len(manifest["records"]) != 75:
        raise EvaluationError("Canonical freeze manifest must contain exactly 75 records.")
    _validate_packet_identity(packet, manifest)
    return frozen


def _exclusion_metadata(row: dict[str, Any]) -> dict[str, str]:
    return {"test_id": str(row["test_id"]), "reason": str(row["exclusion_reason"]), "excluded_by": str(row["excluded_by"]), "excluded_at": str(row["excluded_at"]), "approved_by": str(row["adjudicator_id"]), "approval_date": str(row["adjudication_date"])}


def review_provenance(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    fields = ("test_id", "reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence", "reviewer_notes", "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence", "second_reviewer_notes", "adjudicated_label", "adjudicator_id", "adjudication_date", "disagreement_resolution", "adjudication_locked", "exclusion_reason", "excluded_by", "excluded_at")
    return [{field: str(row.get(field) or "") for field in fields} for row in sorted(rows, key=lambda item: str(item["test_id"]))]


def _locked_rows(rows: Iterable[dict[str, Any]], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    row_list = list(rows)
    _validate_packet_identity(row_list, manifest)
    policy, valid, exclusions = finalization_policy(), [], []
    allowed = {str(reason) for reason in policy["approved_exclusion_reasons"]}
    for row in row_list:
        row_id, reason = str(row["test_id"]).strip(), str(row.get("exclusion_reason") or "").strip()
        if reason:
            if reason not in allowed:
                raise EvaluationError(f"Disallowed exclusion reason for {row_id}.")
            for field in policy["required_exclusion_approval_fields"]:
                if not str(row.get(field) or "").strip():
                    raise EvaluationError(f"Excluded row {row_id} requires {field}.")
            _require_date(row["excluded_at"], "excluded_at", row_id)
            _require_date(row["adjudication_date"], "adjudication_date", row_id)
            if not _truthy(row.get("adjudication_locked")) or _label(row.get("adjudicated_label"), "adjudicated_label", row_id) is not None:
                raise EvaluationError(f"Excluded row {row_id} must be approval-locked and unlabelled.")
            exclusions.append(_exclusion_metadata(row)); continue
        if any(str(row.get(field) or "").strip() for field in ("exclusion_reason", "excluded_by", "excluded_at")):
            raise EvaluationError(f"Non-excluded row {row_id} has exclusion provenance.")
        required = ("reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence", "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence", "adjudicated_label", "adjudicator_id", "adjudication_date")
        if not all(str(row.get(field) or "").strip() for field in required):
            raise EvaluationError(f"Complete reviewer and adjudication provenance is required for {row_id}.")
        for field in ("review_date", "second_review_date", "adjudication_date"):
            _require_date(row[field], field, row_id)
        _require_confidence(row["reviewer_confidence"], "reviewer_confidence", row_id)
        _require_confidence(row["second_reviewer_confidence"], "second_reviewer_confidence", row_id)
        if not _truthy(row.get("adjudication_locked")):
            raise EvaluationError(f"Adjudication is not locked for {row_id}.")
        if str(row["reviewer_id"]).strip().casefold() == str(row["second_reviewer_id"]).strip().casefold():
            raise EvaluationError(f"Independent reviewer identities are required for {row_id}.")
        first, second, adjudicated = _label(row.get("reviewer_sif_label"), "reviewer_sif_label", row_id), _label(row.get("second_reviewer_label"), "second_reviewer_label", row_id), _label(row.get("adjudicated_label"), "adjudicated_label", row_id)
        if first is None or second is None or adjudicated is None:
            raise EvaluationError(f"Complete reviewer labels are required for {row_id}.")
        if first != second and not str(row.get("disagreement_resolution") or "").strip():
            raise EvaluationError(f"Disagreement resolution is required for {row_id}.")
        valid.append({**row, "_row_id": row_id, "_label": adjudicated})
    if len(valid) < int(policy["minimum_retained_records"]):
        raise EvaluationError(f"Retained record count {len(valid)} is below policy minimum {policy['minimum_retained_records']}.")
    return valid, exclusions


def validate_completed_packet(rows: Iterable[dict[str, Any]], artifact_dir: Path = ARTIFACTS) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    manifest = canonical_manifest()
    frozen = _validate_release_anchor(manifest, artifact_dir)
    retained, exclusions = _locked_rows(list(rows), manifest)
    return manifest, frozen, retained, exclusions


def _require_finalization_manifest(path: Path, packet_path: Path, rows: list[dict[str, Any]], canonical: dict[str, Any]) -> dict[str, Any]:
    finalized = _read_json(path, "Finalization manifest")
    if finalized.get("schema_version") != FINALIZATION_SCHEMA_VERSION or finalized.get("status") != "adjudication_finalized":
        raise EvaluationError("Packet has not been finalized under the supported adjudication schema.")
    release = finalized.get("canonical_blind_release") or {}
    if release.get("manifest_sha256") != CANONICAL_MANIFEST_SHA256 or release.get("release_version") != canonical.get("release_version") or release.get("dataset") != DATASET:
        raise EvaluationError("Finalization manifest cannot redefine the canonical blind release.")
    policy, declared = finalization_policy(), finalized.get("finalization_policy") or {}
    if declared.get("sha256") != sha256(FINALIZATION_POLICY) or declared.get("version") != policy.get("version") or declared.get("minimum_retained_records") != policy.get("minimum_retained_records"):
        raise EvaluationError("Finalization policy does not match the finalized adjudication.")
    finalized_packet = finalized.get("finalized_reviewer_packet") or {}
    if finalized_packet.get("canonical_content_sha256") != finalized_packet_sha256(rows):
        raise EvaluationError("Finalized reviewer packet content hash mismatch.")
    if finalized_packet.get("packet_file_sha256") != sha256(packet_path):
        raise EvaluationError("Finalized reviewer packet file hash mismatch.")
    retained, exclusions = _locked_rows(rows, canonical)
    expected_counts = {"frozen_records": 75, "retained_records": len(retained), "excluded_records": len(exclusions), "evaluated_records": len(retained)}
    if finalized.get("counts") != expected_counts or finalized.get("exclusions") != exclusions:
        raise EvaluationError("Finalization manifest count or exclusion metadata does not match the completed packet.")
    if finalized.get("review_provenance") != review_provenance(rows):
        raise EvaluationError("Finalization manifest review provenance does not match the completed packet.")
    _require_date(finalized.get("finalized_at_utc"), "finalized_at_utc", "finalization")
    if not str(finalized.get("finalized_by") or "").strip() or finalized.get("evaluator_schema_version") != EVALUATOR_SCHEMA_VERSION:
        raise EvaluationError("Finalization manifest finalizer or evaluator schema is invalid.")
    attestation = finalized.get("external_attestation")
    if not isinstance(attestation, dict) or set(attestation) != {"git_commit_sha", "git_tag"}:
        raise EvaluationError("Finalization manifest external attestation metadata is invalid.")
    return finalized


def _git_resolved_commit(commit: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise EvaluationError("Official Git commit attestation cannot be verified locally.") from error
    return result.stdout.strip()


def _require_official_attestation(canonical: dict[str, Any], finalized: dict[str, Any]) -> dict[str, Any]:
    if not OFFICIAL_ATTESTATION.is_file():
        raise EvaluationError("Official v0.3 attestation is missing.")
    attestation = _read_json(OFFICIAL_ATTESTATION, "Official v0.3 attestation")
    if attestation.get("schema_version") != "blind-human-official-attestation-v0.3" or attestation.get("status") != "official_attested":
        raise EvaluationError("Official v0.3 attestation status or schema is invalid.")
    if (
        attestation.get("release_version") != canonical.get("release_version")
        or attestation.get("canonical_release_manifest_sha256") != CANONICAL_MANIFEST_SHA256
        or attestation.get("finalized_packet_sha256") != sha256(OFFICIAL_FINALIZED_PACKET)
        or attestation.get("finalization_manifest_sha256") != sha256(OFFICIAL_FINALIZATION_MANIFEST)
        or attestation.get("finalization_policy_sha256") != sha256(FINALIZATION_POLICY)
    ):
        raise EvaluationError("Official attestation hash binding does not match v0.3 artifacts.")
    expected_counts = finalized.get("counts")
    if attestation.get("counts") != expected_counts:
        raise EvaluationError("Official attestation counts do not match finalized adjudications.")
    _require_date(attestation.get("attested_at_utc"), "attested_at_utc", "official attestation")
    commit = str(attestation.get("git_commit_sha") or "").strip()
    tag = str(attestation.get("git_tag") or "").strip()
    if not commit or not tag:
        raise EvaluationError("Official attestation requires Git commit and tag metadata.")
    resolved = _git_resolved_commit(commit)
    try:
        tag_result = subprocess.run(["git", "rev-parse", "--verify", f"{tag}^{{commit}}"], cwd=ROOT, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise EvaluationError("Official Git tag attestation cannot be verified locally.") from error
    if tag_result.stdout.strip() != resolved:
        raise EvaluationError("Official Git tag does not resolve to the attested commit.")
    return attestation


def _routing(score: float | None) -> str:
    if score is None: return "HUMAN_REVIEW"
    lower, upper = POLICY_REVIEW_BAND
    return "NON_SIF_POTENTIAL" if score < lower else "HUMAN_REVIEW" if score <= upper else "SIF_POTENTIAL"


def calibration_metrics(y_true: Iterable[int], scores: Iterable[float], bins: int = 10) -> dict[str, Any]:
    labels, values = list(y_true), [float(value) for value in scores]
    if len(labels) != len(values) or not values or any(label not in {0, 1} for label in labels) or any(not 0.0 <= value <= 1.0 for value in values):
        raise EvaluationError("Calibration assessment needs paired binary labels and scores in [0, 1].")
    brier = sum((value - label) ** 2 for label, value in zip(labels, values)) / len(values)
    reliability = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = [(label, value) for label, value in zip(labels, values) if lower <= value < upper or index == bins - 1 and value == upper]
        if selected: reliability.append({"lower": lower, "upper": upper, "count": len(selected), "mean_score": round(sum(value for _, value in selected) / len(selected), 10), "observed_rate": round(sum(label for label, _ in selected) / len(selected), 10)})
    return {"status": "assessed_frozen_raw_scores", "sample_size": len(values), "brier_score": round(brier, 10), "reliability_bins": reliability, "calibrator_fitted": False}


def _calibration_overlap(rows: Iterable[dict[str, Any]], manifest: dict[str, Any]) -> bool:
    records = manifest["records"]
    blind_ids = {str(record.get(field) or "").strip() for record in records for field in ("test_id", "candidate_id", "source_record_id") if str(record.get(field) or "").strip()}
    blind_hashes = {str(record["normalized_narrative_sha256"]) for record in records}
    return any(({str(row.get(field) or "").strip() for field in ("test_id", "candidate_id", "source_record_id") if str(row.get(field) or "").strip()} & blind_ids) or normalized_narrative_hash(row.get("narrative")) in blind_hashes for row in rows)


def assess_calibration(rows: Iterable[dict[str, Any]], predictor: Callable[[str], dict[str, Any]], *, population: str) -> dict[str, Any]:
    row_list, manifest = list(rows), canonical_manifest()
    _validate_release_anchor(manifest, ARTIFACTS)
    if _calibration_overlap(row_list, manifest): raise EvaluationError("Calibration cannot overlap or repackage the canonical blind test.")
    labels, scores = [], []
    for row in row_list:
        label = _label(row.get("adjudicated_label"), "adjudicated_label", str(row.get("test_id") or "development"))
        if label is None: raise EvaluationError("Calibration rows require adjudicated labels.")
        score = predictor(str(row.get("narrative") or "")).get("sif_score")
        if score is not None: labels.append(label); scores.append(float(score))
    result = calibration_metrics(labels, scores); result["population"] = population
    return result


def evaluate_rows(rows: Iterable[dict[str, Any]], predictor: Callable[[str], dict[str, Any]], threshold: float, *, manifest: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    if float(threshold) != float(frozen.get("binary_threshold")) or frozen.get("review_band") != list(POLICY_REVIEW_BAND):
        raise EvaluationError("Scoring threshold does not match the canonical frozen model metadata.")
    locked, exclusions = _locked_rows(rows, manifest)
    predictions, failures = [], []
    for row in locked:
        score = predictor(row["narrative"]).get("sif_score"); score = float(score) if score is not None else None
        if score is not None and not 0.0 <= score <= 1.0: raise EvaluationError(f"Predictor score is outside [0, 1] for {row['_row_id']}.")
        if score is None: failures.append(row["_row_id"])
        predictions.append((row, score, _routing(score)))
    scored = [(row, score) for row, score, _ in predictions if score is not None]
    metrics = binary_metrics([row["_label"] for row, _ in scored], [score for _, score in scored], threshold) if scored else {"threshold": float(threshold), "precision": 0.0, "recall": 0.0, "f1": 0.0, "f2": 0.0, "confusion_matrix": [[0, 0], [0, 0]], "false_negative_indices": []}
    false_negatives = [row["_row_id"] for row, score in scored if row["_label"] == 1 and score < threshold]
    routes = {route: sum(actual == route for _, _, actual in predictions) for route in ("NON_SIF_POTENTIAL", "HUMAN_REVIEW", "SIF_POTENTIAL")}
    auto_non_sif = [row["_row_id"] for row, _, route in predictions if row["_label"] == 1 and route == "NON_SIF_POTENTIAL"]
    return {"population": "human_blind_test_v0_2", "sample_size": len(locked), "scored_sample_size": len(scored), "frozen_records": 75, "evaluated_records": len(locked), "excluded_records": len(exclusions), "exclusions": exclusions, "inference_failure_ids": failures, "binary_threshold": float(threshold), "binary_metrics": {key: value for key, value in metrics.items() if key != "false_negative_indices"}, "false_negative_ids": false_negatives, "three_band_routing": {"counts": routes, "review_workload": routes["HUMAN_REVIEW"], "human_positive_cases_routed_non_sif": len(auto_non_sif), "human_positive_ids_routed_non_sif": auto_non_sif, "review_is_not_a_correct_binary_classification": True}, "frozen": frozen, "calibration": {"status": "not_assessed_on_blind_test", "calibrator_fitted": False}}


def _evaluate_packet(packet_path: Path, finalization_manifest_path: Path, artifact_dir: Path = ARTIFACTS) -> dict[str, Any]:
    canonical, frozen, packet = canonical_manifest(), None, _read_csv(packet_path)
    frozen = _validate_release_anchor(canonical, artifact_dir)
    finalized = _require_finalization_manifest(finalization_manifest_path, packet_path, packet, canonical)
    result = evaluate_rows(packet, lambda text: predict(text, artifact_dir=artifact_dir), frozen["binary_threshold"], manifest=canonical, frozen=frozen)
    result["canonical_freeze"] = {"manifest_path": str(CANONICAL_MANIFEST), "manifest_sha256": CANONICAL_MANIFEST_SHA256, "release_status": canonical["release_status"]}
    result["finalization"] = {"manifest_path": str(finalization_manifest_path), "completed_packet_sha256": finalized["finalized_reviewer_packet"]["canonical_content_sha256"], "status": finalized["status"], "finalized_at_utc": finalized["finalized_at_utc"]}
    return result


def evaluate_file(packet_path: Path, finalization_manifest_path: Path, artifact_dir: Path = ARTIFACTS, output_path: Path | None = None) -> dict[str, Any]:
    """Development-only evaluator; output is explicitly NON_OFFICIAL."""
    result = _evaluate_packet(packet_path, finalization_manifest_path, artifact_dir)
    result["official_status"] = "NON_OFFICIAL"
    result["population"] = "non_official_development_evaluation"
    if output_path:
        if output_path.resolve() in {OFFICIAL_FINALIZED_PACKET.resolve(), OFFICIAL_FINALIZATION_MANIFEST.resolve(), OFFICIAL_ATTESTATION.resolve()}:
            raise EvaluationError("Generic evaluator cannot write an official v0.3 artifact.")
        output_path.parent.mkdir(parents=True, exist_ok=True); output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def evaluate_official(artifact_dir: Path = ARTIFACTS, output_path: Path | None = None) -> dict[str, Any]:
    """Official v0.3 evaluation; all artifact paths are fixed by the freeze."""
    canonical = canonical_manifest()
    finalized = _require_finalization_manifest(OFFICIAL_FINALIZATION_MANIFEST, OFFICIAL_FINALIZED_PACKET, _read_csv(OFFICIAL_FINALIZED_PACKET), canonical)
    attestation = _require_official_attestation(canonical, finalized)
    result = _evaluate_packet(OFFICIAL_FINALIZED_PACKET, OFFICIAL_FINALIZATION_MANIFEST, artifact_dir)
    result["official_status"] = "OFFICIAL"
    result["population"] = "human_blind_test_v0_3"
    result["official_attestation"] = {"path": str(OFFICIAL_ATTESTATION), "sha256": sha256(OFFICIAL_ATTESTATION), "status": attestation["status"]}
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True); output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the designated official v0.3 human-review result.")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_official(args.artifacts, args.output), indent=2))


if __name__ == "__main__": main()
