import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_V2 = ROOT / "data" / "domain_adaptation_v0_2"
DATA = ROOT / "data" / "domain_adaptation_v0_3"
ARTIFACTS = ROOT / "artifacts" / "domain_adapted_v0_3"
REPORTS = ROOT / "reports" / "domain_adaptation_v0_3"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fresh_assessment_was_frozen_and_is_duplicate_isolated():
    fresh = pd.read_csv(DATA / "fresh_assessment_v0_3.csv", dtype=str, keep_default_na=False)
    manifest = json.loads((DATA / "fresh_assessment_v0_3_manifest.json").read_text(encoding="utf-8"))
    train = pd.read_csv(DATA_V2 / "train_v0_2.csv", dtype=str, keep_default_na=False)
    dev = pd.read_csv(DATA_V2 / "development_v0_2.csv", dtype=str, keep_default_na=False)
    regression = pd.read_csv(DATA_V2 / "protected_test_v0_2.csv", dtype=str, keep_default_na=False)
    assert manifest["status"] == "FROZEN_BEFORE_MODEL_SCORING"
    assert digest(DATA / "fresh_assessment_v0_3.csv") == manifest["source_file_sha256"]
    assert len(fresh) == 100 and fresh.duplicate_group.is_unique
    assert fresh.sif_label.value_counts().to_dict() == {"SIF_POTENTIAL": 50, "NON_SIF_POTENTIAL": 50}
    for frame in (train, dev, regression):
        assert not set(fresh.incident_id) & set(frame.incident_id)
        assert not set(fresh.source_record_id) & set(frame.source_record_id)
        assert not set(fresh.duplicate_group) & set(frame.duplicate_group)
        assert not set(fresh.normalized_narrative_sha256) & set(frame.normalized_narrative_sha256)


def test_sif_operating_points_are_frozen_on_their_fitted_score_scales():
    selection = json.loads((ARTIFACTS / "selection_manifest_v0_3.json").read_text(encoding="utf-8"))
    assert selection["status"] == "FROZEN_BEFORE_FINAL_ASSESSMENT"
    assert selection["fit_scope"]["tfidf"] == "training_only_no_refit"
    assert selection["fit_scope"]["setfit"] == "saved_training_only_checkpoint_no_retraining"
    assert selection["tfidf"]["development_gate_passed"] is False
    assert selection["setfit"]["development_gate_passed"] is True
    assert selection["selected_family"] == "setfit_saved_train_only"
    assert digest(ARTIFACTS / "sif_tfidf_train_only.joblib") == selection["artifacts"]["tfidf"]["sha256"]


def test_lsr_review_masks_unknowns_and_never_uses_protected_rows():
    review = pd.read_csv(DATA / "lsr_candidate_review_v0_3.csv", dtype=str, keep_default_na=False)
    assert len(review[review.rule_id == "LSR01"]) == 29
    assert len(review[review.rule_id == "LSR02"]) == 56
    assert set(review.revised_target) <= {"POSITIVE", "NEGATIVE", "UNKNOWN"}
    assert (review[(review.rule_id == "LSR02") & (review.revised_target == "UNKNOWN")].annotation_status == "unresolved").all()
    protected = review[review.partition.str.contains("excluded")]
    assert len(protected) == 4
    assert not set(protected.partition) - {"frozen_human_validation_excluded", "regression_benchmark_excluded"}
    assert (review[review.revised_target == "POSITIVE"].mapping_evidence_excerpt.str.len() > 0).all()
    assert (review.violation_status == "NOT_ESTABLISHED").all()


def test_experimental_lsr_artifact_has_honest_partial_coverage():
    artifact = joblib.load(ARTIFACTS / "lsr_model_v0_3.joblib")
    assert artifact["version"] == "iogp-lsr-v0.3"
    assert artifact["rules"]["LSR01"]["available"] is True
    assert artifact["rules"]["LSR02"]["available"] is True
    assert artifact["rules"]["LSR08"]["available"] is False
    assert artifact["rules"]["LSR08"]["reason"] == "two_accepted_positives_below_minimum_three"


def test_final_assessment_retains_active_baseline():
    report = json.loads((REPORTS / "sif_evaluation_v0_3.json").read_text(encoding="utf-8"))
    assert report["promotion"]["decision"] == "RETAIN_ACTIVE_BASELINE"
    assert report["regression_status"] == "90_REPORT_SET_ALREADY_INFORMED_DIAGNOSIS_NOT_FRESH_VALIDATION"
    assert report["fresh_assessment_status"].startswith("ONE_TIME_FROZEN_AI_ASSISTED")


def test_v0_3_artifact_manifest_hashes_match_disk():
    manifest = json.loads((ARTIFACTS / "artifact_manifest_v0_3.json").read_text(encoding="utf-8"))
    assert manifest["candidate_promoted"] is False
    assert manifest["runtime_changed"] is False
    assert manifest["runtime_generative_llm_calls"] is False
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert digest(path) == item["sha256"]
    for item in manifest["reports"]:
        assert digest(ROOT / item["path"]) == item["sha256"]
