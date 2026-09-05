"""Read-only evaluator for the canonical v0.2 blind-human release.

The historical v0.1 packet is deliberately unsupported. Evaluation always
anchors to the committed v0.2 manifest and blank release packet; callers cannot
provide a replacement manifest to redefine the blind set.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from build_blind_test_v0_2 import (
    ARTIFACTS, CANDIDATES, DATASET, MANIFEST_NAME, OUT as RELEASE_ROOT,
    PACKET_NAME, PREPROCESSING, REVIEWER_PACKET_FIELDS, REVIEW_METADATA_FIELDS,
    VALIDATION_POLICY, normalized_narrative_hash, sha256,
)
from evaluate import binary_metrics
from predict import POLICY_REVIEW_BAND, predict


class EvaluationError(ValueError):
    """Raised when a completed packet or frozen release identity is unsafe."""


CANONICAL_PACKET = RELEASE_ROOT / PACKET_NAME
CANONICAL_MANIFEST = RELEASE_ROOT / MANIFEST_NAME
# SHA-256 of the committed canonical manifest; populated after the v0.2 release
# is created, preventing a caller-created manifest from becoming authoritative.
CANONICAL_MANIFEST_SHA256 = "cdb27d32de1a9845ecd76db72bacb827058a57fb06bb76e93051711f0d7833b0"
ALLOWED_EXCLUSION_REASONS = frozenset({
    "withdrawn_before_review", "insufficient_source_material",
    "duplicate_discovered_after_freeze", "reviewer_unavailable",
})
LABELS = {
    "0": 0, "1": 1, "non-sif": 0, "non_sif": 0, "non sif": 0,
    "sif": 1, "sif potential": 1, "non-sif potential": 0,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as error:
        raise EvaluationError(f"Unable to read reviewer packet: {path}") from error


def _label(value: object, field: str, row_id: str) -> int | None:
    text = "" if value is None else str(value).strip().casefold()
    if not text:
        return None
    if text not in LABELS:
        raise EvaluationError(f"Unknown {field} '{value}' for {row_id}.")
    return LABELS[text]


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "locked"}


def frozen_metadata(artifact_dir: Path) -> dict[str, Any]:
    config_path = artifact_dir / "threshold.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        identity = str(config["model"])
        threshold = float(config["sif_threshold"])
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
    return {
        "model_identity": identity,
        "model_sha256": sha256(model_path),
        "preprocessing_sha256": sha256(PREPROCESSING),
        "configuration_sha256": sha256(config_path),
        "binary_threshold": threshold,
        "review_band": band,
        "calibration_status": "uncalibrated",
    }


def canonical_manifest() -> dict[str, Any]:
    if not CANONICAL_MANIFEST.is_file():
        raise EvaluationError("Canonical v0.2 freeze manifest is missing.")
    if CANONICAL_MANIFEST_SHA256.startswith("TO_BE_SET"):
        raise EvaluationError("Canonical v0.2 manifest hash has not been release-pinned.")
    if sha256(CANONICAL_MANIFEST) != CANONICAL_MANIFEST_SHA256:
        raise EvaluationError("Canonical freeze manifest hash mismatch.")
    try:
        manifest = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise EvaluationError("Canonical freeze manifest is unreadable.") from error
    if manifest.get("schema_version") != "blind-human-freeze-v0.2" or manifest.get("dataset") != DATASET:
        raise EvaluationError("Canonical freeze manifest has an unexpected schema or dataset.")
    return manifest


def _require_exact_schema(rows: list[dict[str, Any]], label: str) -> None:
    if not rows:
        raise EvaluationError(f"{label} is empty.")
    actual = list(rows[0].keys())
    if actual != REVIEWER_PACKET_FIELDS or any(list(row.keys()) != actual for row in rows):
        raise EvaluationError(f"{label} schema does not exactly match the v0.2 reviewer packet.")


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
        test_id = str(row["test_id"]).strip()
        expected_row = expected[test_id]
        for field in ("candidate_id", "source", "source_record_id"):
            if str(row.get(field) or "").strip() != str(expected_row.get(field) or "").strip():
                raise EvaluationError(f"Reviewer packet {field} mismatch for {test_id}.")
        if normalized_narrative_hash(row.get("narrative")) != expected_row.get("normalized_narrative_sha256"):
            raise EvaluationError(f"Reviewer packet narrative hash mismatch for {test_id}.")


def _validate_release_anchor(manifest: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    packet = _read_csv(CANONICAL_PACKET)
    _require_exact_schema(packet, "Canonical reviewer packet")
    canonical_packet = manifest.get("canonical_packet") or {}
    if canonical_packet.get("filename") != PACKET_NAME or sha256(CANONICAL_PACKET) != canonical_packet.get("sha256"):
        raise EvaluationError("Canonical blind packet hash mismatch.")
    if any(any(str(row.get(field) or "").strip() for field in REVIEW_METADATA_FIELDS) for row in packet):
        raise EvaluationError("Canonical reviewer packet is not blank before human scoring.")
    candidate = manifest.get("candidate_pool") or {}
    if candidate.get("sha256") != sha256(CANDIDATES):
        raise EvaluationError("Candidate-pool hash does not match the canonical freeze.")
    policy = manifest.get("validation_policy") or {}
    try:
        current_policy = json.loads(VALIDATION_POLICY.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise EvaluationError("Validation policy is unreadable.") from error
    if policy.get("sha256") != sha256(VALIDATION_POLICY) or policy.get("version") != current_policy.get("version"):
        raise EvaluationError("Validation policy does not match the canonical freeze.")
    frozen = frozen_metadata(artifact_dir)
    expected_frozen = manifest.get("frozen_model") or {}
    for key in ("model_identity", "model_sha256", "preprocessing_sha256", "configuration_sha256", "binary_threshold", "review_band"):
        if expected_frozen.get(key) != frozen.get(key):
            raise EvaluationError(f"Frozen {key} does not match the canonical freeze.")
    if not isinstance(manifest.get("records"), list) or len(manifest["records"]) != 75:
        raise EvaluationError("Canonical freeze manifest must contain exactly 75 records.")
    _validate_packet_identity(packet, manifest)
    return frozen


def _locked_rows(rows: Iterable[dict[str, Any]], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    row_list = list(rows)
    _validate_packet_identity(row_list, manifest)
    valid: list[dict[str, Any]] = []
    excluded = 0
    for row in row_list:
        row_id = str(row["test_id"]).strip()
        exclusion_reason = str(row.get("exclusion_reason") or "").strip()
        if exclusion_reason:
            if exclusion_reason not in ALLOWED_EXCLUSION_REASONS:
                raise EvaluationError(f"Disallowed exclusion reason for {row_id}.")
            if not all(str(row.get(field) or "").strip() for field in ("excluded_by", "excluded_at")):
                raise EvaluationError(f"Excluded row {row_id} requires excluded_by and excluded_at.")
            if _truthy(row.get("adjudication_locked")) or _label(row.get("adjudicated_label"), "adjudicated_label", row_id) is not None:
                raise EvaluationError(f"Excluded row {row_id} cannot be adjudicated or locked.")
            excluded += 1
            continue
        if any(str(row.get(field) or "").strip() for field in ("excluded_by", "excluded_at")):
            raise EvaluationError(f"Non-excluded row {row_id} has exclusion provenance.")
        required = (
            "reviewer_id", "review_date", "reviewer_sif_label", "reviewer_confidence",
            "second_reviewer_id", "second_review_date", "second_reviewer_label", "second_reviewer_confidence",
            "adjudicated_label", "adjudicator_id", "adjudication_date",
        )
        if not all(str(row.get(field) or "").strip() for field in required):
            raise EvaluationError(f"Complete reviewer and adjudication provenance is required for {row_id}.")
        if not _truthy(row.get("adjudication_locked")):
            raise EvaluationError(f"Adjudication is not locked for {row_id}.")
        if str(row["reviewer_id"]).strip().casefold() == str(row["second_reviewer_id"]).strip().casefold():
            raise EvaluationError(f"Independent reviewer identities are required for {row_id}.")
        first = _label(row.get("reviewer_sif_label"), "reviewer_sif_label", row_id)
        second = _label(row.get("second_reviewer_label"), "second_reviewer_label", row_id)
        adjudicated = _label(row.get("adjudicated_label"), "adjudicated_label", row_id)
        if first is None or second is None or adjudicated is None:
            raise EvaluationError(f"Complete reviewer labels are required for {row_id}.")
        if first != second and not str(row.get("disagreement_resolution") or "").strip():
            raise EvaluationError(f"Disagreement resolution is required for {row_id}.")
        valid.append({**row, "_row_id": row_id, "_label": adjudicated})
    return valid, excluded


def _routing(score: float | None) -> str:
    if score is None:
        return "HUMAN_REVIEW"
    lower, upper = POLICY_REVIEW_BAND
    return "NON_SIF_POTENTIAL" if score < lower else "HUMAN_REVIEW" if score <= upper else "SIF_POTENTIAL"


def calibration_metrics(y_true: Iterable[int], scores: Iterable[float], bins: int = 10) -> dict[str, Any]:
    labels, values = list(y_true), [float(value) for value in scores]
    if len(labels) != len(values) or not values:
        raise EvaluationError("Calibration assessment needs paired, non-empty labels and scores.")
    if any(label not in {0, 1} for label in labels) or any(not 0.0 <= value <= 1.0 for value in values):
        raise EvaluationError("Calibration labels must be binary and scores must be in [0, 1].")
    brier = sum((value - label) ** 2 for label, value in zip(labels, values)) / len(values)
    reliability = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = [(label, value) for label, value in zip(labels, values) if lower <= value < upper or index == bins - 1 and value == upper]
        if selected:
            reliability.append({"lower": lower, "upper": upper, "count": len(selected), "mean_score": round(sum(value for _, value in selected) / len(selected), 10), "observed_rate": round(sum(label for label, _ in selected) / len(selected), 10)})
    return {"status": "assessed_frozen_raw_scores", "sample_size": len(values), "brier_score": round(brier, 10), "reliability_bins": reliability, "calibrator_fitted": False}


def _calibration_overlap(rows: Iterable[dict[str, Any]], manifest: dict[str, Any]) -> bool:
    records = manifest["records"]
    blind_ids = {str(record.get(field) or "").strip() for record in records for field in ("test_id", "candidate_id", "source_record_id") if str(record.get(field) or "").strip()}
    blind_hashes = {str(record["normalized_narrative_sha256"]) for record in records}
    for row in rows:
        stable_ids = {str(row.get(field) or "").strip() for field in ("test_id", "candidate_id", "source_record_id") if str(row.get(field) or "").strip()}
        if stable_ids & blind_ids or normalized_narrative_hash(row.get("narrative")) in blind_hashes:
            return True
    return False


def assess_calibration(rows: Iterable[dict[str, Any]], predictor: Callable[[str], dict[str, Any]], *, population: str) -> dict[str, Any]:
    row_list = list(rows)
    manifest = canonical_manifest()
    _validate_release_anchor(manifest, ARTIFACTS)
    if _calibration_overlap(row_list, manifest):
        raise EvaluationError("Calibration cannot overlap or repackage the canonical blind test.")
    labels, scores = [], []
    for row in row_list:
        label = _label(row.get("adjudicated_label"), "adjudicated_label", str(row.get("test_id") or "development"))
        if label is None:
            raise EvaluationError("Calibration rows require adjudicated labels.")
        score = predictor(str(row.get("narrative") or "")).get("sif_score")
        if score is not None:
            labels.append(label); scores.append(float(score))
    result = calibration_metrics(labels, scores)
    result["population"] = population
    return result


def evaluate_rows(rows: Iterable[dict[str, Any]], predictor: Callable[[str], dict[str, Any]], threshold: float, *, manifest: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    if float(threshold) != float(frozen.get("binary_threshold")) or frozen.get("review_band") != list(POLICY_REVIEW_BAND):
        raise EvaluationError("Scoring threshold does not match the canonical frozen model metadata.")
    locked, excluded = _locked_rows(rows, manifest)
    predictions: list[tuple[dict[str, Any], float | None, str]] = []
    failures: list[str] = []
    for row in locked:
        score = predictor(row["narrative"]).get("sif_score")
        score = float(score) if score is not None else None
        if score is not None and not 0.0 <= score <= 1.0:
            raise EvaluationError(f"Predictor score is outside [0, 1] for {row['_row_id']}.")
        if score is None:
            failures.append(row["_row_id"])
        predictions.append((row, score, _routing(score)))
    scored = [(row, score) for row, score, _ in predictions if score is not None]
    metrics = binary_metrics([row["_label"] for row, _ in scored], [score for _, score in scored], threshold) if scored else {"threshold": float(threshold), "precision": 0.0, "recall": 0.0, "f1": 0.0, "f2": 0.0, "confusion_matrix": [[0, 0], [0, 0]], "false_negative_indices": []}
    false_negative_ids = [row["_row_id"] for row, score in scored if row["_label"] == 1 and score < threshold]
    routing_counts = {route: sum(actual_route == route for _, _, actual_route in predictions) for route in ("NON_SIF_POTENTIAL", "HUMAN_REVIEW", "SIF_POTENTIAL")}
    auto_non_sif = [row["_row_id"] for row, _, route in predictions if row["_label"] == 1 and route == "NON_SIF_POTENTIAL"]
    return {"population": "human_blind_test_v0_2", "sample_size": len(locked), "scored_sample_size": len(scored), "excluded_rows": excluded, "inference_failure_ids": failures, "binary_threshold": float(threshold), "binary_metrics": {key: value for key, value in metrics.items() if key != "false_negative_indices"}, "false_negative_ids": false_negative_ids, "three_band_routing": {"counts": routing_counts, "review_workload": routing_counts["HUMAN_REVIEW"], "human_positive_cases_routed_non_sif": len(auto_non_sif), "human_positive_ids_routed_non_sif": auto_non_sif, "review_is_not_a_correct_binary_classification": True}, "frozen": frozen, "calibration": {"status": "not_assessed_on_blind_test", "calibrator_fitted": False}}


def evaluate_file(packet_path: Path, artifact_dir: Path = ARTIFACTS, output_path: Path | None = None) -> dict[str, Any]:
    manifest = canonical_manifest()
    frozen = _validate_release_anchor(manifest, artifact_dir)
    packet = _read_csv(packet_path)
    result = evaluate_rows(packet, lambda text: predict(text, artifact_dir=artifact_dir), frozen["binary_threshold"], manifest=manifest, frozen=frozen)
    result["canonical_freeze"] = {"manifest_path": str(CANONICAL_MANIFEST), "manifest_sha256": CANONICAL_MANIFEST_SHA256, "release_status": manifest["release_status"]}
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a completed packet against the canonical v0.2 blind freeze.")
    parser.add_argument("--packet", type=Path, required=True, help="Completed v0.2 reviewer packet; never a mutable authority manifest.")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_file(args.packet, args.artifacts, args.output), indent=2))


if __name__ == "__main__":
    main()
