"""No-fit evaluator for locked blind human adjudications.

This module consumes reviewer-completed rows and the already-frozen predictor.
It never calls a training or threshold-selection routine and keeps binary
metrics separate from three-band routing workload.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from evaluate import binary_metrics
from predict import POLICY_REVIEW_BAND, predict


class EvaluationError(ValueError):
    """Raised when a locked reviewer packet cannot be scored safely."""


LABELS = {
    "0": 0, "1": 1, "non-sif": 0, "non_sif": 0, "non sif": 0,
    "sif": 1, "sif potential": 1, "non-sif potential": 0,
}


def _label(value: object, field: str, row_id: str) -> int | None:
    text = "" if value is None else str(value).strip().casefold()
    if not text:
        return None
    if text not in LABELS:
        raise EvaluationError(f"Unknown {field} '{value}' for {row_id}.")
    return LABELS[text]


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as error:
        raise EvaluationError(f"Unable to read reviewer packet: {path}") from error


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def frozen_metadata(artifact_dir: Path) -> dict[str, Any]:
    config_path = artifact_dir / "threshold.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        band = tuple(float(value) for value in config["human_review_band"])
        threshold = float(config["sif_threshold"])
        identity = str(config["model"])
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise EvaluationError("Frozen model configuration is missing or invalid.") from error
    if band != POLICY_REVIEW_BAND:
        raise EvaluationError(f"Frozen review band {band} does not match policy {POLICY_REVIEW_BAND}.")
    if identity == "embedding_logreg":
        model_name = "embedding_logreg.joblib"
    elif isinstance(identity, str) and identity.startswith("tfidf_"):
        model_name = "tfidf_logreg.joblib"
    else:
        raise EvaluationError(f"Unsupported frozen model identity: {identity}.")
    model_path = artifact_dir / model_name
    if not model_path.exists():
        raise EvaluationError(f"Frozen model artifact is missing: {model_path.name}.")
    return {"model_identity": identity, "model_hash": _sha256(model_path), "configuration_hash": _sha256(config_path), "binary_threshold": threshold, "review_band": list(POLICY_REVIEW_BAND), "calibration_status": "uncalibrated"}


def _manifest_ids(manifest: dict[str, Any]) -> tuple[set[str], set[str]]:
    source_ids = {str(value).strip() for value in manifest.get("selected_ids", []) if str(value).strip()}
    test_ids = {str(value).strip() for value in manifest.get("test_ids", []) if str(value).strip()}
    freeze = manifest.get("freeze_manifest") or manifest.get("frozen") or {}
    source_ids.update(str(value).strip() for value in freeze.get("source_ids", []) if str(value).strip())
    test_ids.update(str(value).strip() for value in freeze.get("test_ids", []) if str(value).strip())
    return source_ids, test_ids


def _freeze_value(manifest: dict[str, Any], key: str) -> Any:
    return manifest.get(key) or (manifest.get("freeze_manifest") or manifest.get("frozen") or {}).get(key)


def _validate_manifest(rows: list[dict[str, Any]], manifest: dict[str, Any] | None, *, require_frozen: bool) -> None:
    if not manifest:
        raise EvaluationError("A frozen reviewer manifest is required before scoring.")
    source_ids, test_ids = _manifest_ids(manifest)
    row_source_ids = {str(row.get("source_record_id") or "").strip() for row in rows if str(row.get("source_record_id") or "").strip()}
    row_test_ids = {str(row.get("test_id") or "").strip() for row in rows if str(row.get("test_id") or "").strip()}
    if source_ids and row_source_ids != source_ids:
        raise EvaluationError("Reviewer packet source IDs do not exactly match the frozen manifest.")
    if test_ids and row_test_ids != test_ids:
        raise EvaluationError("Reviewer packet test IDs do not exactly match the frozen manifest.")
    if not source_ids and not test_ids:
        raise EvaluationError("Frozen manifest must list test IDs.")
    if require_frozen:
        if not test_ids:
            raise EvaluationError("Frozen manifest must list exact test IDs.")
        freeze = manifest.get("freeze_manifest") or manifest.get("frozen") or manifest
        for key in ("model_hash", "configuration_hash"):
            if not freeze.get(key):
                raise EvaluationError(f"Frozen manifest is missing {key}.")
        if freeze.get("binary_threshold") is None or freeze.get("review_band") != list(POLICY_REVIEW_BAND):
            raise EvaluationError("Frozen manifest is missing the frozen threshold policy.")
        narrative_hashes = manifest.get("test_narrative_hashes") or freeze.get("test_narrative_hashes")
        if not narrative_hashes:
            raise EvaluationError("Frozen manifest is missing narrative hashes.")
        for row in rows:
            row_id = str(row.get("test_id") or row.get("source_record_id") or "").strip()
            source_id = str(row.get("source_record_id") or "").strip()
            expected = narrative_hashes.get(row_id) or narrative_hashes.get(source_id)
            actual = hashlib.sha256(str(row.get("narrative") or "").strip().encode()).hexdigest()
            if not expected or expected != actual:
                raise EvaluationError(f"Narrative hash does not match the frozen manifest for {row_id}.")


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "locked"}


def _locked_rows(rows: Iterable[dict[str, Any]], manifest: dict[str, Any] | None = None, *, require_frozen: bool = True) -> tuple[list[dict[str, Any]], int]:
    rows = list(rows)
    _validate_manifest(rows, manifest, require_frozen=require_frozen)
    excluded_ids = {str(value).strip() for value in (manifest or {}).get("excluded_ids", []) if str(value).strip()}
    seen: set[str] = set()
    valid: list[dict[str, Any]] = []
    unresolved = 0
    for row in rows:
        row_id = str(row.get("test_id") or row.get("source_record_id") or "").strip()
        if not row_id:
            raise EvaluationError("Every reviewer row needs a test_id or source_record_id.")
        if row_id in seen:
            raise EvaluationError(f"Duplicate reviewer row ID: {row_id}.")
        seen.add(row_id)
        narrative = str(row.get("narrative") or "").strip()
        if not narrative:
            raise EvaluationError(f"Missing narrative for {row_id}.")
        first = _label(row.get("reviewer_sif_label"), "reviewer_sif_label", row_id)
        second = _label(row.get("second_reviewer_label"), "second_reviewer_label", row_id)
        adjudicated = _label(row.get("adjudicated_label"), "adjudicated_label", row_id)
        if not _truthy(row.get("adjudication_locked")):
            if row_id in excluded_ids:
                unresolved += 1
                continue
            raise EvaluationError(f"Adjudication is not locked for {row_id}.")
        if not all(str(row.get(field) or "").strip() for field in ("reviewer_id", "review_date", "second_reviewer_id", "second_review_date", "reviewer_confidence", "second_reviewer_confidence")):
            raise EvaluationError(f"Reviewer identity, dates, and confidence are required for {row_id}.")
        if str(row.get("reviewer_id") or "").strip() == str(row.get("second_reviewer_id") or "").strip():
            raise EvaluationError(f"Independent reviewer identities are required for {row_id}.")
        if first is not None and second is not None and first != second and adjudicated is None:
            if row_id not in excluded_ids:
                raise EvaluationError(f"Disagreement is unresolved for {row_id}.")
            unresolved += 1
            continue
        if adjudicated is None:
            if row_id not in excluded_ids:
                raise EvaluationError(f"Adjudicated label is required for {row_id}.")
            unresolved += 1
            continue
        if first is None or second is None:
            raise EvaluationError(f"Independent reviewer labels are required for {row_id}.")
        if first != second and not str(row.get("disagreement_resolution") or "").strip():
            raise EvaluationError(f"Disagreement resolution is required for {row_id}.")
        valid.append({**row, "_row_id": row_id, "_label": adjudicated})
    return valid, unresolved


def _routing(score: float | None) -> str:
    if score is None:
        return "HUMAN_REVIEW"
    lower, upper = POLICY_REVIEW_BAND
    return "NON_SIF_POTENTIAL" if score < lower else "HUMAN_REVIEW" if score <= upper else "SIF_POTENTIAL"


def calibration_metrics(y_true: Iterable[int], scores: Iterable[float], bins: int = 10) -> dict[str, Any]:
    """Assess frozen raw scores without fitting a calibrator."""
    labels, values = list(y_true), [float(value) for value in scores]
    if len(labels) != len(values) or not values:
        raise EvaluationError("Calibration assessment needs paired, non-empty labels and scores.")
    if any(not 0.0 <= value <= 1.0 for value in values):
        raise EvaluationError("Calibration scores must be in [0, 1].")
    brier = sum((value - label) ** 2 for label, value in zip(labels, values)) / len(values)
    reliability = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = [(label, value) for label, value in zip(labels, values) if lower <= value < upper or index == bins - 1 and value == upper]
        if selected:
            reliability.append({"lower": lower, "upper": upper, "count": len(selected), "mean_score": round(sum(value for _, value in selected) / len(selected), 10), "observed_rate": round(sum(label for label, _ in selected) / len(selected), 10)})
    return {"status": "assessed_frozen_raw_scores", "sample_size": len(values), "brier_score": round(brier, 10), "reliability_bins": reliability, "calibrator_fitted": False}


def assess_calibration(rows: Iterable[dict[str, Any]], predictor: Callable[[str], dict[str, Any]], *, population: str, manifest: dict[str, Any], blind_manifest: dict[str, Any]) -> dict[str, Any]:
    row_list = list(rows)
    development_ids = {str(row.get(field) or "").strip() for row in row_list for field in ("test_id", "source_record_id") if str(row.get(field) or "").strip()}
    blind_source_ids, blind_test_ids = _manifest_ids(blind_manifest)
    if not blind_source_ids and not blind_test_ids:
        raise EvaluationError("The frozen blind-test manifest must list test IDs.")
    if development_ids & (blind_source_ids | blind_test_ids):
        raise EvaluationError("Calibration cannot overlap the frozen final human blind test.")
    locked, unresolved = _locked_rows(row_list, manifest, require_frozen=False)
    scored = []
    for row in locked:
        score = predictor(row["narrative"]).get("sif_score")
        if score is not None:
            scored.append((row["_label"], float(score)))
    result = calibration_metrics([label for label, _ in scored], [score for _, score in scored])
    result["population"] = population; result["unresolved_exclusions"] = unresolved
    return result


def evaluate_rows(rows: Iterable[dict[str, Any]], predictor: Callable[[str], dict[str, Any]], threshold: float, *, manifest: dict[str, Any] | None = None, frozen: dict[str, Any] | None = None) -> dict[str, Any]:
    if not frozen or not frozen.get("model_hash") or not frozen.get("configuration_hash"):
        raise EvaluationError("Frozen model metadata is required before scoring.")
    try:
        frozen_threshold_matches = float(threshold) == float(frozen.get("binary_threshold"))
    except (TypeError, ValueError):
        frozen_threshold_matches = False
    if not frozen_threshold_matches or frozen.get("review_band") != list(POLICY_REVIEW_BAND):
        raise EvaluationError("Scoring threshold does not match the frozen model metadata.")
    if manifest and any(_freeze_value(manifest, key) != frozen.get(key) for key in ("model_hash", "configuration_hash")):
        raise EvaluationError("Frozen model metadata does not match the reviewer manifest.")
    locked, unresolved = _locked_rows(rows, manifest, require_frozen=True)
    predictions: list[tuple[dict[str, Any], float | None, str]] = []
    inference_failures: list[str] = []
    for row in locked:
        output = predictor(row["narrative"])
        score = output.get("sif_score")
        score = float(score) if score is not None else None
        if score is None:
            inference_failures.append(row["_row_id"])
        predictions.append((row, score, _routing(score)))
    scored = [(row, score) for row, score, _ in predictions if score is not None]
    y_true = [row["_label"] for row, _ in scored]
    scores = [score for _, score in scored]
    metrics = binary_metrics(y_true, scores, threshold) if scored else {"threshold": float(threshold), "precision": 0.0, "recall": 0.0, "f1": 0.0, "f2": 0.0, "confusion_matrix": [[0, 0], [0, 0]], "false_negative_indices": []}
    false_negative_ids = [row["_row_id"] for row, score in scored if row["_label"] == 1 and score < threshold]
    routing_counts = {name: sum(route == name for _, _, route in predictions) for name in ("NON_SIF_POTENTIAL", "HUMAN_REVIEW", "SIF_POTENTIAL")}
    auto_non_sif_ids = [row["_row_id"] for row, _, route in predictions if row["_label"] == 1 and route == "NON_SIF_POTENTIAL"]
    return {
        "population": "human_blind_test",
        "sample_size": len(locked),
        "scored_sample_size": len(scored),
        "unresolved_exclusions": unresolved + len(inference_failures),
        "inference_failure_ids": inference_failures,
        "binary_threshold": float(threshold),
        "binary_metrics": {key: value for key, value in metrics.items() if key != "false_negative_indices"},
        "false_negative_ids": false_negative_ids,
        "three_band_routing": {"counts": routing_counts, "review_workload": routing_counts["HUMAN_REVIEW"], "human_positive_cases_routed_non_sif": len(auto_non_sif_ids), "human_positive_ids_routed_non_sif": auto_non_sif_ids, "review_is_not_a_correct_binary_classification": True},
        "frozen": frozen or {"binary_threshold": float(threshold), "review_band": list(POLICY_REVIEW_BAND), "calibration_status": "uncalibrated"},
        "calibration": {"status": "not_assessed_on_blind_test", "requirement": "independent human-labelled development data", "calibrator_fitted": False},
    }


def evaluate_file(packet_path: Path, artifact_dir: Path, manifest_path: Path | None = None, output_path: Path | None = None) -> dict[str, Any]:
    if manifest_path is None:
        raise EvaluationError("A frozen manifest is required before scoring.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frozen = frozen_metadata(artifact_dir)
    if manifest:
        for key in ("model_hash", "configuration_hash"):
            expected = _freeze_value(manifest, key)
            if expected and expected != frozen[key]:
                raise EvaluationError(f"{key} does not match the frozen artifact.")
        expected_threshold = _freeze_value(manifest, "binary_threshold")
        expected_band = _freeze_value(manifest, "review_band")
        if expected_threshold is None or float(expected_threshold) != frozen["binary_threshold"] or expected_band != frozen["review_band"]:
            raise EvaluationError("Frozen threshold policy does not match the selected artifact.")
    packet = _read_csv(packet_path)
    result = evaluate_rows(packet, lambda text: predict(text, artifact_dir=artifact_dir), frozen["binary_threshold"], manifest=manifest, frozen=frozen)
    result["freeze_manifest"] = {"model_identity": frozen["model_identity"], "model_hash": frozen["model_hash"], "configuration_hash": frozen["configuration_hash"], "binary_threshold": frozen["binary_threshold"], "review_band": list(POLICY_REVIEW_BAND), "test_ids": [row.get("test_id") or row.get("source_record_id") for row in packet], "test_narrative_hashes": {str(row.get("test_id") or row.get("source_record_id")): hashlib.sha256(str(row.get("narrative") or "").strip().encode()).hexdigest() for row in packet}}
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a locked blind reviewer packet with the frozen predictor.")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_file(args.packet, args.artifacts, args.manifest, args.output), indent=2))


if __name__ == "__main__":
    main()
