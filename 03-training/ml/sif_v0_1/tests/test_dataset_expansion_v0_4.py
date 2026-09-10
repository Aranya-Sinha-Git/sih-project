import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "domain_adaptation_v0_4"
OLD = ROOT / "data" / "domain_adaptation_v0_2"
ARTIFACTS = ROOT / "artifacts" / "domain_adapted_v0_4"
REPORTS = ROOT / "reports" / "domain_adaptation_v0_4"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_membership_and_partitions_were_frozen_before_annotation():
    source = pd.read_csv(DATA / "selected_source_v0_4.csv", dtype=str, keep_default_na=False)
    manifest = json.loads((DATA / "selection_freeze_manifest_v0_4.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FROZEN_BEFORE_ANNOTATION_OR_MODEL_PREDICTIONS"
    assert digest(DATA / "selected_source_v0_4.csv") == manifest["selected_source_sha256"]
    assert len(source) == 1000
    assert source.partition.value_counts().to_dict() == {
        "train_addition": 700,
        "development_addition": 150,
        "fresh_final_assessment": 150,
    }
    assert source.candidate_id.is_unique
    assert source.source_record_id.is_unique
    assert source.duplicate_group.is_unique
    assert source.normalized_narrative_sha256.is_unique
    forbidden = {"sif_label", "model_score", "prediction", "adjudication", "annotation_rationale"}
    assert not forbidden & set(source.columns)


def test_expansion_has_no_identity_overlap_with_existing_model_partitions():
    source = pd.read_csv(DATA / "selected_source_v0_4.csv", dtype=str, keep_default_na=False)
    for filename in ("train_v0_2.csv", "development_v0_2.csv", "protected_test_v0_2.csv"):
        frame = pd.read_csv(OLD / filename, dtype=str, keep_default_na=False)
        assert not set(source.candidate_id) & set(frame.incident_id)
        assert not set(source.source_record_id) & set(frame.source_record_id)
        assert not set(source.duplicate_group) & set(frame.duplicate_group)
        assert not set(source.normalized_narrative_sha256) & set(frame.normalized_narrative_sha256)


def test_final_annotations_are_frozen_and_unknown_targets_are_explicit():
    frame = pd.read_csv(DATA / "annotations_final_v0_4.csv", dtype=str, keep_default_na=False)
    manifest = json.loads((DATA / "annotation_freeze_manifest_v0_4.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FROZEN_REFERENCES_BEFORE_MODEL_TRAINING_OR_FINAL_SCORING"
    assert digest(DATA / "annotations_final_v0_4.csv") == manifest["final_annotations_sha256"]
    assert len(frame) == 750
    assert manifest["selected_rows"] == 1000
    assert manifest["unannotated_rows"] == 250
    assert manifest["split_files"]["train_addition"]["rows"] == 450
    assert manifest["split_files"]["development_addition"]["rows"] == 150
    assert manifest["split_files"]["fresh_final_assessment"]["rows"] == 150
    assert set(frame.sif_label) <= {"SIF_POTENTIAL", "NON_SIF_POTENTIAL", "UNCERTAIN"}
    assert (frame[frame.sif_label == "UNCERTAIN"].uncertainty_reason.str.len() > 0).all()
    for number in range(1, 10):
        rule = f"LSR{number:02d}"
        assert set(frame[f"{rule}_target"]) <= {"POSITIVE", "NEGATIVE", "UNKNOWN"}
        assert (frame[frame[f"{rule}_target"] == "POSITIVE"][f"{rule}_evidence"].str.len() > 0).all()
        assert (frame[frame[f"{rule}_target"] == "UNKNOWN"][f"{rule}_unknown_reason"].str.len() > 0).all()


def test_fitted_artifacts_and_thresholds_are_frozen_before_final_scoring():
    selection = json.loads((ARTIFACTS / "selection_manifest_v0_4.json").read_text(encoding="utf-8"))
    assert selection["status"] == "FROZEN_CANDIDATE_AND_THRESHOLDS_BEFORE_FINAL_ASSESSMENT"
    assert selection["selected_family"] in {None, "tfidf_v0.4", "setfit_v0.4"}
    assert digest(ARTIFACTS / "sif_tfidf_v0_4.joblib") == selection["artifacts"]["tfidf"]["sha256"]
    assert digest(ARTIFACTS / "lsr_model_v0_4.joblib") == selection["artifacts"]["lsr"]["sha256"]
    artifact = joblib.load(ARTIFACTS / "lsr_model_v0_4.joblib")
    assert artifact["unknown_targets_masked"] is True
    assert artifact["input_allowlist"] == ["narrative"]


def test_final_evaluation_keeps_binary_metrics_separate_and_runtime_llm_free():
    report = json.loads((REPORTS / "final_evaluation_v0_4.json").read_text(encoding="utf-8"))
    final = report["sif"]["datasets"]["fresh_final_assessment"]
    assert "binary_prediction_metrics" in final["active_baseline_v0.1"]
    assert "operational_routing" in final["active_baseline_v0.1"]
    assert report["runtime_generative_llm_calls"] is False
    assert report["old_regression_status"].startswith("DIAGNOSTIC_ONLY")
    assert report["lsr"]["evaluations"]["candidate_v0.4"]["aggregate"]["unavailable_rules_excluded"] is True
