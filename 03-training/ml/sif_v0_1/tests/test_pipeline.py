import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import evaluate_human
from build_blind_test_v0_2 import (
    ARTIFACTS, CANDIDATES, FORBIDDEN_FIELD_TOKENS, PACKET_NAME,
    REVIEWER_PACKET_FIELDS, REVIEW_METADATA_FIELDS, VALIDATION_POLICY,
    validation_locked_mask,
)
from evaluate import binary_metrics
from evaluate_human import EvaluationError, assess_calibration, canonical_manifest, evaluate_file


def release_rows() -> list[dict[str, str]]:
    with evaluate_human.CANONICAL_PACKET.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def completed_rows() -> list[dict[str, str]]:
    rows = release_rows()
    for row in rows:
        row.update({
            "reviewer_id": "Reviewer A", "review_date": "2026-09-05", "reviewer_sif_label": "0",
            "reviewer_confidence": "high", "reviewer_notes": "independent review",
            "second_reviewer_id": "Reviewer B", "second_review_date": "2026-09-06", "second_reviewer_label": "0",
            "second_reviewer_confidence": "high", "second_reviewer_notes": "independent second review",
            "adjudicated_label": "0", "adjudicator_id": "Adjudicator C", "adjudication_date": "2026-09-07",
            "disagreement_resolution": "", "adjudication_locked": "true",
            "exclusion_reason": "", "excluded_by": "", "excluded_at": "",
        })
    return rows


def test_actual_v02_release_packet_and_manifest_are_canonical_and_reviewer_safe():
    manifest = canonical_manifest()
    rows = release_rows()
    assert len(rows) == 75
    assert list(rows[0]) == REVIEWER_PACKET_FIELDS
    assert len({row["test_id"] for row in rows}) == 75
    assert {row["test_id"] for row in rows} == {record["test_id"] for record in manifest["records"]}
    assert manifest["canonical_packet"]["filename"] == PACKET_NAME
    assert manifest["candidate_pool"]["sha256"] == hashlib.sha256(CANDIDATES.read_bytes()).hexdigest()
    assert manifest["validation_policy"]["sha256"] == hashlib.sha256(VALIDATION_POLICY.read_bytes()).hexdigest()
    assert all(not any(token in field.casefold() for token in FORBIDDEN_FIELD_TOKENS) for field in rows[0])
    assert all(not any(row[field].strip() for field in REVIEW_METADATA_FIELDS) for row in rows)
    evaluate_human._validate_release_anchor(manifest, ARTIFACTS)


def test_validation_policy_locks_and_missing_required_lock_field_fail_closed():
    policy = json.loads(VALIDATION_POLICY.read_text(encoding="utf-8"))
    frame = pd.DataFrame([
        {"source": "OSHA_SIR", "validation_locked": "false"},
        {"source": "OSHA_SIR", "validation_locked": "true"},
        {"source": "IOGP 2025", "validation_locked": "false"},
    ])
    mask = validation_locked_mask(frame, {value.casefold() for value in policy["locked_sources"]}, set(policy["locked_record_flags"]))
    assert frame.loc[~mask].index.tolist() == [0]
    with pytest.raises(ValueError, match="absent candidate lock"):
        validation_locked_mask(frame.drop(columns=["validation_locked"]), set(), set(policy["locked_record_flags"]))


def test_evaluator_refuses_unreviewed_actual_release_packet():
    with pytest.raises(EvaluationError, match="Complete reviewer and adjudication provenance"):
        evaluate_file(evaluate_human.CANONICAL_PACKET)


def test_locked_structure_requires_complete_adjudication_and_valid_exclusions():
    manifest = canonical_manifest()
    rows = completed_rows()
    locked, excluded = evaluate_human._locked_rows(rows, manifest)
    assert len(locked) == 75 and excluded == 0
    incomplete = completed_rows(); incomplete[0]["adjudicator_id"] = ""
    with pytest.raises(EvaluationError, match="Complete reviewer and adjudication provenance"):
        evaluate_human._locked_rows(incomplete, manifest)
    excluded_rows = completed_rows()
    excluded_rows[0].update({"adjudication_locked": "", "adjudicated_label": "", "exclusion_reason": "withdrawn_before_review", "excluded_by": "Release steward", "excluded_at": "2026-09-08"})
    locked, excluded = evaluate_human._locked_rows(excluded_rows, manifest)
    assert len(locked) == 74 and excluded == 1
    excluded_rows[1].update({"adjudication_locked": "", "adjudicated_label": "", "exclusion_reason": "post_hoc_removal", "excluded_by": "Release steward", "excluded_at": "2026-09-08"})
    with pytest.raises(EvaluationError, match="Disallowed exclusion"):
        evaluate_human._locked_rows(excluded_rows, manifest)


def test_tampered_identity_manifest_packet_model_config_threshold_and_policy_fail(tmp_path, monkeypatch):
    manifest = canonical_manifest()
    rows = release_rows()
    bad_id = [dict(row) for row in rows]; bad_id[0]["test_id"] = "BT-V0.2-999"
    with pytest.raises(EvaluationError, match="test IDs"):
        evaluate_human._validate_packet_identity(bad_id, manifest)
    bad_text = [dict(row) for row in rows]; bad_text[0]["narrative"] = "Repackaged narrative"
    with pytest.raises(EvaluationError, match="narrative hash"):
        evaluate_human._validate_packet_identity(bad_text, manifest)

    changed_manifest = tmp_path / "manifest.json"
    changed_manifest.write_text(evaluate_human.CANONICAL_MANIFEST.read_text(encoding="utf-8") + " ", encoding="utf-8")
    monkeypatch.setattr(evaluate_human, "CANONICAL_MANIFEST", changed_manifest)
    with pytest.raises(EvaluationError, match="manifest hash mismatch"):
        canonical_manifest()
    monkeypatch.undo()

    changed_packet = tmp_path / PACKET_NAME
    changed_packet.write_text(evaluate_human.CANONICAL_PACKET.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    monkeypatch.setattr(evaluate_human, "CANONICAL_PACKET", changed_packet)
    with pytest.raises(EvaluationError, match="packet hash mismatch"):
        evaluate_human._validate_release_anchor(manifest, ARTIFACTS)
    monkeypatch.undo()

    altered_artifacts = tmp_path / "artifacts"; altered_artifacts.mkdir()
    shutil.copy2(ARTIFACTS / "tfidf_logreg.joblib", altered_artifacts / "tfidf_logreg.joblib")
    config = json.loads((ARTIFACTS / "threshold.json").read_text(encoding="utf-8")); config["sif_threshold"] = 0.41
    (altered_artifacts / "threshold.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(EvaluationError, match="configuration_sha256|binary_threshold"):
        evaluate_human._validate_release_anchor(manifest, altered_artifacts)
    (altered_artifacts / "threshold.json").write_text((ARTIFACTS / "threshold.json").read_text(encoding="utf-8"), encoding="utf-8")
    with (altered_artifacts / "tfidf_logreg.joblib").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(EvaluationError, match="model_sha256"):
        evaluate_human._validate_release_anchor(manifest, altered_artifacts)

    changed_policy = tmp_path / "validation_policy.json"
    changed_policy.write_text(json.dumps({"version": "changed"}), encoding="utf-8")
    monkeypatch.setattr(evaluate_human, "VALIDATION_POLICY", changed_policy)
    with pytest.raises(EvaluationError, match="Validation policy"):
        evaluate_human._validate_release_anchor(manifest, ARTIFACTS)


def test_repackaged_blind_narrative_is_rejected_from_calibration():
    blind = release_rows()[0]
    alias = {"test_id": "DEV-RENAMED", "candidate_id": "DEV-CANDIDATE", "source_record_id": "DEV-SOURCE", "narrative": blind["narrative"], "adjudicated_label": "1"}
    with pytest.raises(EvaluationError, match="overlap or repackage"):
        assess_calibration([alias], lambda _: {"sif_score": 0.5}, population="independent_development")


def test_metrics_keep_binary_errors_and_review_band_workload_distinct():
    metrics = binary_metrics([1, 0, 1], [0.2, 0.4, 0.5], 0.4)
    assert metrics["confusion_matrix"] == [[0, 1], [1, 1]]
    assert metrics["false_negative_indices"] == [0]
