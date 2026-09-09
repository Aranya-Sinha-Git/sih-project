import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data" / "domain_adaptation_v0_2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_teammate_export_is_unchanged_and_review_is_traceable():
    source = PROJECT / "04-data" / "Human labeled data" / "labeling_decisions_rows (1).csv"
    reviewed = pd.read_csv(DATA / "teammate_labels_reviewed_v0_2.csv", keep_default_na=False)
    assert digest(source).upper() == "9FBAF83B093C722F02B99022937F5223FBC3ED776CDE4D8E94DE73F1966130E3"
    assert len(reviewed) == 369 and reviewed.incident_id.is_unique
    required = {"incident_id", "source", "original_label", "revised_label", "exact_evidence_excerpt", "correction_reason", "annotation_review_status", "label_provenance", "annotation_version"}
    assert required <= set(reviewed.columns)
    changed = reviewed[reviewed.original_label != reviewed.revised_label]
    assert len(changed) == 67
    assert all(row.exact_evidence_excerpt in row.narrative for row in changed.itertuples())
    assert all("expert" not in value.casefold() for value in reviewed.label_provenance)


def test_splits_are_group_safe_and_unresolved_labels_are_not_supervised():
    merged = pd.read_csv(DATA / "merged_incidents_v0_2.csv", keep_default_na=False)
    train = pd.read_csv(DATA / "train_v0_2.csv", keep_default_na=False)
    dev = pd.read_csv(DATA / "development_v0_2.csv", keep_default_na=False)
    test = pd.read_csv(DATA / "protected_test_v0_2.csv", keep_default_na=False)
    assert len(merged) == 500 and (merged.sif_label == "UNCERTAIN").sum() == 39
    assert not set(train.duplicate_group) & set(dev.duplicate_group)
    assert not (set(train.duplicate_group) | set(dev.duplicate_group)) & set(test.duplicate_group)
    assert "UNCERTAIN" not in set(train.sif_label) | set(dev.sif_label)
    assert set(test.sif_label.value_counts().to_dict().items()) == {("SIF_POTENTIAL", 50), ("NON_SIF_POTENTIAL", 40)}


def test_protected_test_excludes_existing_frozen_releases():
    protected = pd.read_csv(DATA / "protected_test_v0_2.csv", keep_default_na=False)
    protected_ids = set(protected.incident_id)
    protected_sources = set(protected.source_record_id)
    protected_hashes = set(protected.normalized_narrative_sha256)
    for version in ("blind_test_v0_2", "blind_test_v0_3"):
        manifest = json.loads((ROOT / "data" / version / f"{version}_freeze_manifest.json").read_text(encoding="utf-8"))
        assert not protected_ids & {row["candidate_id"] for row in manifest["records"]}
        assert not protected_sources & {row["source_record_id"] for row in manifest["records"]}
        assert not protected_hashes & {row["normalized_narrative_sha256"] for row in manifest["records"]}


def test_lsr_annotations_keep_unknown_separate_from_negative():
    annotations = pd.read_csv(DATA / "lsr_annotations_train_dev_v0_2.csv", keep_default_na=False)
    for number in range(1, 10):
        values = set(annotations[f"LSR{number:02d}_target"])
        assert values <= {"POSITIVE", "NEGATIVE", "UNKNOWN"}
        assert "UNKNOWN" in values
    assert set(annotations.zero_mapping_assessment) <= {"EXPLICITLY_ASSESSED_ZERO", "INSUFFICIENT_INFORMATION", "HAS_RELEVANT_RULES"}


def test_artifact_and_source_manifest_hashes_match_disk():
    artifact_root = ROOT / "artifacts" / "domain_adapted_v0_2"
    manifest = json.loads((artifact_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert manifest["deployment_sif_model"] == "baseline_sif_v0.1"
    assert manifest["candidate_promoted"] is False
    assert manifest["runtime_generative_llm_calls"] is False
    for item in manifest["artifacts"]:
        path = artifact_root / item["file"]
        assert path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]
    for item in manifest["source_files"]:
        assert digest(PROJECT / item["path"]) == item["sha256"]
