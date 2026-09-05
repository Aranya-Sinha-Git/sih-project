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
    ARTIFACTS, CANDIDATES, FORBIDDEN_FIELD_TOKENS, PACKET_NAME as V2_PACKET_NAME,
    REVIEWER_PACKET_FIELDS, REVIEW_METADATA_FIELDS, VALIDATION_POLICY,
    validation_locked_mask,
)
from build_blind_test_v0_3 import (
    MANIFEST_NAME as V3_MANIFEST_NAME, PACKET_NAME,
    OFFICIAL_ATTESTATION_NAME,
    OFFICIAL_FINALIZATION_MANIFEST_NAME, OFFICIAL_FINALIZED_PACKET_NAME,
    OUT as V3_OUT, V2_MANIFEST, V2_PACKET,
)
from evaluate import binary_metrics
from evaluate_human import EvaluationError, assess_calibration, canonical_manifest, evaluate_file, evaluate_official, finalized_packet_sha256
from finalize_human_reviews import finalize


def release_rows() -> list[dict[str, str]]:
    with evaluate_human.CANONICAL_PACKET.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEWER_PACKET_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def completed_rows() -> list[dict[str, str]]:
    rows = release_rows()
    for row in rows:
        row.update({
            "reviewer_id": "Synthetic Reviewer A", "review_date": "2026-09-05", "reviewer_sif_label": "0",
            "reviewer_confidence": "high", "reviewer_notes": "synthetic test fixture",
            "second_reviewer_id": "Synthetic Reviewer B", "second_review_date": "2026-09-06", "second_reviewer_label": "0",
            "second_reviewer_confidence": "high", "second_reviewer_notes": "synthetic test fixture",
            "adjudicated_label": "0", "adjudicator_id": "Synthetic Adjudicator", "adjudication_date": "2026-09-07",
            "disagreement_resolution": "", "adjudication_locked": "true",
            "exclusion_reason": "", "excluded_by": "", "excluded_at": "",
        })
    return rows


def exclude(row: dict[str, str]) -> None:
    row.update({
        "adjudicated_label": "", "adjudication_locked": "true",
        "exclusion_reason": "withdrawn_before_review", "excluded_by": "Synthetic Release Steward",
        "excluded_at": "2026-09-08", "adjudicator_id": "Synthetic Approval Steward",
        "adjudication_date": "2026-09-08",
    })


def finalized_fixture(tmp_path: Path, rows: list[dict[str, str]] | None = None) -> tuple[Path, Path]:
    source, packet, manifest = tmp_path / "completed.csv", tmp_path / "finalized.csv", tmp_path / "finalization.json"
    write_rows(source, rows or completed_rows())
    finalize(source, packet, manifest, finalized_by="Synthetic Finalizer", finalized_at_utc="2026-09-09T00:00:00+00:00", git_commit_sha="deadbeef", git_tag="blind-v0.2-pre-review")
    return packet, manifest


def test_actual_v03_release_packet_and_manifest_are_canonical_and_reviewer_safe():
    manifest, rows = canonical_manifest(), release_rows()
    assert len(rows) == len(manifest["records"]) == 75
    assert list(rows[0]) == REVIEWER_PACKET_FIELDS
    assert len({row["test_id"] for row in rows}) == 75
    assert {row["test_id"] for row in rows} == {record["test_id"] for record in manifest["records"]}
    assert manifest["canonical_packet"]["filename"] == PACKET_NAME
    assert manifest["candidate_pool"]["sha256"] == hashlib.sha256(CANDIDATES.read_bytes()).hexdigest()
    assert manifest["validation_policy"]["sha256"] == hashlib.sha256(VALIDATION_POLICY.read_bytes()).hexdigest()
    assert all(not any(token in field.casefold() for token in FORBIDDEN_FIELD_TOKENS) for field in rows[0])
    assert all(not any(row[field].strip() for field in REVIEW_METADATA_FIELDS) for row in rows)
    evaluate_human._validate_release_anchor(manifest, ARTIFACTS)


def test_v02_remains_historical_and_v03_keeps_exact_membership_and_packet_bytes():
    assert hashlib.sha256(V2_MANIFEST.read_bytes()).hexdigest() == "cdb27d32de1a9845ecd76db72bacb827058a57fb06bb76e93051711f0d7833b0"
    assert hashlib.sha256(V2_PACKET.read_bytes()).hexdigest() == "f911b0a78b8c366c95a18d6c60f47dda596adae3ef9edfc0719a357c0b6d83b3"
    v3 = canonical_manifest()
    assert v3["schema_version"] == "blind-human-freeze-v0.3"
    assert v3["canonical_packet"]["sha256"] == hashlib.sha256(V2_PACKET.read_bytes()).hexdigest()
    assert len(v3["records"]) == 75
    assert v3["finalization_policy"]["minimum_retained_records"] == 70
    assert v3["official_artifacts"] == {"finalized_packet": OFFICIAL_FINALIZED_PACKET_NAME, "finalization_manifest": OFFICIAL_FINALIZATION_MANIFEST_NAME, "attestation": OFFICIAL_ATTESTATION_NAME}


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


def test_non_finalized_packet_is_rejected_before_metrics(tmp_path, monkeypatch):
    source = tmp_path / "completed.csv"
    write_rows(source, completed_rows())
    monkeypatch.setattr(evaluate_human, "predict", lambda *_args, **_kwargs: {"sif_score": 0.5})
    with pytest.raises(EvaluationError, match="Finalization manifest is unreadable"):
        evaluate_file(source, tmp_path / "missing-finalization.json")


def test_official_evaluator_uses_only_fixed_v03_artifacts_and_fails_closed_before_review():
    assert not (V3_OUT / OFFICIAL_FINALIZED_PACKET_NAME).exists()
    assert not (V3_OUT / OFFICIAL_FINALIZATION_MANIFEST_NAME).exists()
    assert not (V3_OUT / OFFICIAL_ATTESTATION_NAME).exists()
    with pytest.raises(EvaluationError):
        evaluate_official()


def test_valid_finalized_packet_evaluates_and_publishes_exclusions(tmp_path, monkeypatch):
    rows = completed_rows()
    exclude(rows[0])
    packet, manifest = finalized_fixture(tmp_path, rows)
    monkeypatch.setattr(evaluate_human, "predict", lambda *_args, **_kwargs: {"sif_score": 0.5})
    result = evaluate_file(packet, manifest)
    assert result["frozen_records"] == 75
    assert result["excluded_records"] == 1
    assert result["evaluated_records"] == 74
    assert result["official_status"] == "NON_OFFICIAL"
    assert result["population"] == "non_official_development_evaluation"
    assert result["exclusions"] == [{"test_id": rows[0]["test_id"], "reason": "withdrawn_before_review", "excluded_by": "Synthetic Release Steward", "excluded_at": "2026-09-08", "approved_by": "Synthetic Approval Steward", "approval_date": "2026-09-08"}]


@pytest.mark.parametrize("field,value", [
    ("adjudicated_label", "1"),
    ("reviewer_id", "Modified Reviewer"),
    ("adjudicator_id", "Modified Adjudicator"),
    ("test_id", "BT-V0.2-999"),
    ("narrative", "Modified finalized narrative"),
])
def test_post_finalization_human_metadata_changes_fail(tmp_path, monkeypatch, field, value):
    packet, manifest = finalized_fixture(tmp_path)
    rows = evaluate_human._read_csv(packet)
    rows[0][field] = value
    write_rows(packet, rows)
    monkeypatch.setattr(evaluate_human, "predict", lambda *_args, **_kwargs: {"sif_score": 0.5})
    with pytest.raises(EvaluationError, match="content hash mismatch"):
        evaluate_file(packet, manifest)


def test_post_finalization_exclusion_change_fails(tmp_path, monkeypatch):
    rows = completed_rows(); exclude(rows[0])
    packet, manifest = finalized_fixture(tmp_path, rows)
    changed = evaluate_human._read_csv(packet)
    changed[0]["exclusion_reason"] = "reviewer_unavailable"
    write_rows(packet, changed)
    monkeypatch.setattr(evaluate_human, "predict", lambda *_args, **_kwargs: {"sif_score": 0.5})
    with pytest.raises(EvaluationError, match="content hash mismatch"):
        evaluate_file(packet, manifest)


def test_finalized_hash_is_deterministic_across_row_order_and_serialization(tmp_path, monkeypatch):
    packet, manifest = finalized_fixture(tmp_path)
    rows = evaluate_human._read_csv(packet)
    assert finalized_packet_sha256(rows) == finalized_packet_sha256(list(reversed(rows)))
    write_rows(packet, list(reversed(rows)))
    monkeypatch.setattr(evaluate_human, "predict", lambda *_args, **_kwargs: {"sif_score": 0.5})
    with pytest.raises(EvaluationError, match="file hash mismatch"):
        evaluate_file(packet, manifest)


def test_finalization_manifest_cannot_redefine_canonical_release(tmp_path, monkeypatch):
    packet, manifest = finalized_fixture(tmp_path)
    altered = json.loads(manifest.read_text(encoding="utf-8"))
    altered["canonical_blind_release"]["manifest_sha256"] = "0" * 64
    manifest.write_text(json.dumps(altered), encoding="utf-8")
    monkeypatch.setattr(evaluate_human, "predict", lambda *_args, **_kwargs: {"sif_score": 0.5})
    with pytest.raises(EvaluationError, match="cannot redefine"):
        evaluate_file(packet, manifest)


def test_generic_evaluator_cannot_write_official_artifacts(tmp_path):
    packet, manifest = finalized_fixture(tmp_path)
    with pytest.raises(EvaluationError, match="cannot write an official"):
        evaluate_file(packet, manifest, output_path=V3_OUT / OFFICIAL_ATTESTATION_NAME)


def test_minimum_retained_sample_is_enforced(tmp_path):
    rows = completed_rows()
    for row in rows[:6]:
        exclude(row)
    source = tmp_path / "below-floor.csv"
    write_rows(source, rows)
    with pytest.raises(EvaluationError, match="below policy minimum 70"):
        finalize(source, tmp_path / "final.csv", tmp_path / "final.json", finalized_by="Synthetic Finalizer", finalized_at_utc="2026-09-09T00:00:00+00:00")


def test_v03_policy_changes_fail_against_hard_anchored_freeze(tmp_path, monkeypatch):
    changed = tmp_path / "finalization-policy.json"
    policy = json.loads(evaluate_human.FINALIZATION_POLICY.read_text(encoding="utf-8"))
    policy["minimum_retained_records"] = 1
    policy["approved_exclusion_reasons"].append("operator_choice")
    changed.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(evaluate_human, "FINALIZATION_POLICY", changed)
    with pytest.raises(EvaluationError, match="Finalization policy"):
        evaluate_human._validate_release_anchor(canonical_manifest(), ARTIFACTS)


def test_missing_or_wrong_official_attestation_and_git_binding_fail(tmp_path, monkeypatch):
    packet = tmp_path / "packet.csv"; finalization = tmp_path / "finalization.json"; attestation = tmp_path / "attestation.json"
    packet.write_bytes(b"packet")
    finalization.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evaluate_human, "OFFICIAL_FINALIZED_PACKET", packet)
    monkeypatch.setattr(evaluate_human, "OFFICIAL_FINALIZATION_MANIFEST", finalization)
    monkeypatch.setattr(evaluate_human, "OFFICIAL_ATTESTATION", attestation)
    with pytest.raises(EvaluationError, match="missing"):
        evaluate_human._require_official_attestation({"release_version": "v0.3"}, {"counts": {}})
    attestation.write_text(json.dumps({"schema_version": "blind-human-official-attestation-v0.3", "status": "official_attested"}), encoding="utf-8")
    with pytest.raises(EvaluationError, match="hash binding"):
        evaluate_human._require_official_attestation({"release_version": "v0.3"}, {"counts": {}})
    with pytest.raises(EvaluationError, match="commit attestation"):
        evaluate_human._git_resolved_commit("not-a-real-commit")


def test_tampered_anchor_model_config_threshold_and_policy_fail(tmp_path, monkeypatch):
    manifest = canonical_manifest()
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


def test_repackaged_blind_narrative_is_rejected_from_calibration():
    blind = release_rows()[0]
    alias = {"test_id": "DEV-RENAMED", "candidate_id": "DEV-CANDIDATE", "source_record_id": "DEV-SOURCE", "narrative": blind["narrative"], "adjudicated_label": "1"}
    with pytest.raises(EvaluationError, match="overlap or repackage"):
        assess_calibration([alias], lambda _: {"sif_score": 0.5}, population="independent_development")


def test_metrics_keep_binary_errors_and_review_band_workload_distinct():
    metrics = binary_metrics([1, 0, 1], [0.2, 0.4, 0.5], 0.4)
    assert metrics["confusion_matrix"] == [[0, 1], [1, 1]]
    assert metrics["false_negative_indices"] == [0]
