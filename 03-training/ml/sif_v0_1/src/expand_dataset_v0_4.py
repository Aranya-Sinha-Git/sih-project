"""Prepare, validate, train, and evaluate the v0.4 AI-annotated expansion.

The workflow is intentionally phased. ``prepare`` freezes source membership and
partitions before annotation. GPT annotation workers write only to the batch
ledgers; ``assemble`` validates their evidence and creates frozen references.
Training and final evaluation are separate commands so final labels are hashed
before any model predictions are produced.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import cohen_kappa_score
from sklearn.pipeline import FeatureUnion

from build_blind_test_v0_1 import (
    build_near_duplicate_index,
    high_similarity_match,
    normalized_text,
    token_3grams,
)
from diagnose_domain_v0_2 import constant_baseline, evaluate, positive_scores
from run_bounded_iteration_v0_3 import eligible_pool, sha256
from train_domain_adapted_v0_2 import (
    NON_SIF,
    SIF,
    SIF_DEVELOPMENT_GATES,
    binary_metrics,
    build_tfidf,
    routing_metrics,
    select_sif_operating_point,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "domain_adaptation_v0_4"
REPORTS = ROOT / "reports" / "domain_adaptation_v0_4"
ARTIFACTS = ROOT / "artifacts" / "domain_adapted_v0_4"
POOL = ROOT / "data" / "candidate_pool_v0_2.csv"
GUIDE = ROOT / "SIF_LABELING_GUIDE.md"
RULES = ROOT / "reference" / "iogp_life_saving_rules_v2018.json"
SEED = 20260910
TARGET_ROWS = 1000
ANNOTATED_ROWS = 750
FINAL_ROWS = 150
DEV_ROWS = 150
GUIDE_VERSION = "prototype-sif-labeling-framework-repo-2026-09-10"
ANNOTATION_VERSION = "gpt-5.6-sol-ai-assisted-v0.4.0"
RULE_IDS = tuple(f"LSR{number:02d}" for number in range(1, 10))
SIF_LABELS = {"SIF_POTENTIAL", "NON_SIF_POTENTIAL", "UNCERTAIN"}
ASSESSMENTS = {"SUPPORTED", "NOT_SUPPORTED", "UNKNOWN"}
RULE_TARGETS = {"POSITIVE", "NEGATIVE", "UNKNOWN"}
VIOLATION_STATUSES = {"ESTABLISHED", "NOT_ESTABLISHED", "UNKNOWN"}
PROVENANCE = "AI_ASSISTED_GPT_5_6_SOL_NOT_HSE_GROUND_TRUTH"
OLD_DATA = ROOT / "data" / "domain_adaptation_v0_2"
BASELINE_ARTIFACT = ROOT / "artifacts" / "supervised" / "tfidf_logreg.joblib"
ACTIVE_LSR_ARTIFACT = ROOT / "artifacts" / "domain_adapted_v0_2" / "lsr_model.joblib"


RULE_PATTERNS = {
    "LSR01": re.compile(r"\b(?:bypass|override|disable|removed? (?:the )?(?:guard|interlock)|defeat(?:ed)?|safety control|deviat(?:e|ed|ion))\b", re.I),
    "LSR02": re.compile(r"\b(?:confined space|permit-required space|tank|vessel|vault|manhole|sewer|silo|pit|crawlspace|attendant|atmosphere test)\b", re.I),
    "LSR03": re.compile(r"\b(?:driver|driving|vehicle|truck|forklift|car|bus|seatbelt|speeding|journey management|backing)\b", re.I),
    "LSR04": re.compile(r"\b(?:lockout|tagout|LOTO|isolat(?:e|ed|ion)|energized|stored energy|residual pressure|de-energ)\b", re.I),
    "LSR05": re.compile(r"\b(?:hot work|weld(?:ing|ed)?|torch|grind(?:ing|er)?|flammable|combustible|gas test|ignition source)\b", re.I),
    "LSR06": re.compile(r"\b(?:line of fire|struck by|caught between|pinned|crushed|pressure release|projectile|falling object|moving equipment|exclusion zone)\b", re.I),
    "LSR07": re.compile(r"\b(?:crane|hoist|rigging|sling|suspended load|lifting operation|forklift.{0,25}(?:lift|load)|load fell)\b", re.I),
    "LSR08": re.compile(r"\b(?:work permit|permit to work|permit-required|unauthori[sz]ed work|authori[sz]ation|job safety analysis|JSA|conditions changed)\b", re.I),
    "LSR09": re.compile(r"\b(?:working at height|fall protection|tie[- ]?off|harness|ladder|scaffold|roof|elevated platform|fell? \d|fall(?:ing)? from)\b", re.I),
}
HIGH_RISK = re.compile(
    r"\b(?:explosion|electrocut|arc flash|fatal|amputat|crushed|engulf|asphyxi|toxic|"
    r"pressure release|suspended load|confined space|fell? \d{2,}|fall(?:ing)? from (?:a )?(?:roof|scaffold|ladder))\b",
    re.I,
)
HARD_NEGATIVE = re.compile(
    r"\b(?:laceration|cut|sprain|strain|bruise|finger|toe|hand|wrist|ankle|slip|trip)\b",
    re.I,
)
HAZARD_TERM = re.compile(
    r"\b(?:machine|equipment|vehicle|forklift|crane|pressure|electric|fire|chemical|fall|ladder|weld|tank|confined)\b",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_key(value: str, namespace: str = "select") -> str:
    return hashlib.sha256(f"v0.4:{SEED}:{namespace}:{value}".encode("utf-8")).hexdigest()


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def annotation_columns() -> list[str]:
    columns = [
        "expansion_id", "candidate_id", "normalized_narrative_sha256", "annotation_pass",
        "sif_label", "sif_evidence_excerpt", "sif_rationale",
        "hazard_energy_assessment", "hazard_energy_evidence",
        "personnel_exposure_assessment", "personnel_exposure_evidence",
        "barrier_failure_assessment", "barrier_failure_evidence",
        "credible_consequence_assessment", "credible_consequence_evidence",
        "uncertainty_reason",
    ]
    for rule_id in RULE_IDS:
        columns.extend([f"{rule_id}_target", f"{rule_id}_evidence", f"{rule_id}_violation_status", f"{rule_id}_unknown_reason"])
    return columns + ["annotation_status", "label_provenance", "annotation_version", "annotator_model", "annotator_id", "annotated_at_utc"]


def source_columns() -> list[str]:
    return [
        "expansion_id", "candidate_id", "source", "source_record_id", "source_year",
        "report_type_if_known", "activity_if_known", "location_if_known", "narrative",
        "source_native_outcome", "source_native_classification", "duplicate_group",
        "normalized_narrative_sha256", "retrieval_strata", "primary_stratum", "length_band",
        "partition", "selection_basis",
    ]


def validate_annotation(frame: pd.DataFrame, source: pd.DataFrame, expected_pass: str) -> list[str]:
    errors: list[str] = []
    missing = set(annotation_columns()) - set(frame.columns)
    if missing:
        return [f"missing columns: {sorted(missing)}"]
    if len(frame) != len(source):
        errors.append(f"row count {len(frame)} != {len(source)}")
    for column in ("expansion_id", "candidate_id", "normalized_narrative_sha256"):
        if frame[column].tolist() != source[column].tolist():
            errors.append(f"{column} does not exactly match input order")
    if set(frame.annotation_pass) != {expected_pass}:
        errors.append(f"annotation_pass must be {expected_pass}")
    if not set(frame.sif_label) <= SIF_LABELS:
        errors.append(f"invalid SIF labels: {sorted(set(frame.sif_label) - SIF_LABELS)}")
    for name in ("hazard_energy_assessment", "personnel_exposure_assessment", "barrier_failure_assessment", "credible_consequence_assessment"):
        if not set(frame[name]) <= ASSESSMENTS:
            errors.append(f"invalid {name}: {sorted(set(frame[name]) - ASSESSMENTS)}")
    if set(frame.label_provenance) != {PROVENANCE}:
        errors.append("label_provenance mismatch")
    if set(frame.annotation_version) != {ANNOTATION_VERSION}:
        errors.append("annotation_version mismatch")
    if set(frame.annotator_model) != {"gpt-5.6-sol"}:
        errors.append("annotator_model mismatch")
    narratives = dict(zip(source.expansion_id, source.narrative))
    evidence_columns = [column for column in frame.columns if column.endswith("_evidence") or column == "sif_evidence_excerpt"]
    for row in frame.to_dict("records"):
        narrative = narratives.get(row["expansion_id"], "")
        for column in evidence_columns:
            excerpt = row.get(column, "")
            if excerpt and excerpt not in narrative:
                errors.append(f"{row['expansion_id']} {column} is not an exact narrative substring")
        if row["sif_label"] != "UNCERTAIN" and not row["sif_evidence_excerpt"]:
            errors.append(f"{row['expansion_id']} binary SIF label lacks evidence")
        if row["sif_label"] == "UNCERTAIN" and not row["uncertainty_reason"]:
            errors.append(f"{row['expansion_id']} uncertain SIF label lacks reason")
        for rule_id in RULE_IDS:
            target = row[f"{rule_id}_target"]
            violation = row[f"{rule_id}_violation_status"]
            if target not in RULE_TARGETS:
                errors.append(f"{row['expansion_id']} invalid {rule_id} target {target}")
            if violation not in VIOLATION_STATUSES:
                errors.append(f"{row['expansion_id']} invalid {rule_id} violation status {violation}")
            if target == "POSITIVE" and not row[f"{rule_id}_evidence"]:
                errors.append(f"{row['expansion_id']} positive {rule_id} lacks evidence")
            if target == "UNKNOWN" and not row[f"{rule_id}_unknown_reason"]:
                errors.append(f"{row['expansion_id']} unknown {rule_id} lacks reason")
    return errors


def load_and_validate_pass(pass_number: int) -> pd.DataFrame:
    if pass_number == 1:
        inputs = [DATA / f"annotation_batch_{number:02d}_input.csv" for number in range(1, 4)]
        outputs = [DATA / f"annotation_batch_{number:02d}_pass1.csv" for number in range(1, 4)]
        expected = "PASS1"
    else:
        manifest = json.loads((DATA / "second_pass_manifest_v0_4.json").read_text(encoding="utf-8"))
        inputs = [DATA / item["input"] for item in manifest["batches"]]
        outputs = [DATA / item["output"] for item in manifest["batches"]]
        supplemental_path = DATA / "systematic_lsr08_review_manifest_v0_4.json"
        if supplemental_path.exists():
            supplemental = json.loads(supplemental_path.read_text(encoding="utf-8"))
            inputs.extend(DATA / item["input"] for item in supplemental["batches"])
            outputs.extend(DATA / item["output"] for item in supplemental["batches"])
        expected = "PASS2"
    frames: list[pd.DataFrame] = []
    all_errors: list[str] = []
    for input_path, output_path in zip(inputs, outputs):
        if not output_path.exists():
            all_errors.append(f"missing {output_path.name}")
            continue
        source = pd.read_csv(input_path, dtype=str, keep_default_na=False)
        frame = pd.read_csv(output_path, dtype=str, keep_default_na=False)
        all_errors.extend(f"{output_path.name}: {error}" for error in validate_annotation(frame, source, expected))
        frames.append(frame)
    if all_errors:
        raise RuntimeError("Annotation validation failed:\n" + "\n".join(all_errors[:100]))
    combined = pd.concat(frames, ignore_index=True)
    if pass_number == 1 and len(combined) != ANNOTATED_ROWS:
        raise RuntimeError(f"Expected {ANNOTATED_ROWS} completed first-pass rows, found {len(combined)}")
    return combined


def make_second_pass() -> None:
    output_path = DATA / "second_pass_input_v0_4.csv"
    manifest_path = DATA / "second_pass_manifest_v0_4.json"
    if output_path.exists() or manifest_path.exists():
        if not (output_path.exists() and manifest_path.exists()):
            raise RuntimeError("second-pass preparation is partially present")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(output_path) != manifest["input_sha256"]:
            raise RuntimeError("second-pass input changed after freeze")
        print(json.dumps({"status": "already_frozen", "rows": manifest["rows"]}, indent=2))
        return
    first = load_and_validate_pass(1)
    source = pd.read_csv(DATA / "selected_source_v0_4.csv", dtype=str, keep_default_na=False)
    source = source[source.expansion_id.isin(first.expansion_id)].copy()
    positive_counts = {rule: int((first[f"{rule}_target"] == "POSITIVE").sum()) for rule in RULE_IDS}
    rare_rules = [rule for rule, count in positive_counts.items() if count < 50]
    uncertain_ids = set(first.loc[first.sif_label == "UNCERTAIN", "expansion_id"])
    rare_ids: set[str] = set()
    for rule in rare_rules:
        rare_ids.update(first.loc[first[f"{rule}_target"] == "POSITIVE", "expansion_id"])
    sif_rates = first.assign(_positive=first.sif_label == SIF).groupby("annotator_id")._positive.mean().to_dict()
    median_sif_rate = float(np.median(list(sif_rates.values())))
    outlier_annotators = [name for name, rate in sif_rates.items() if abs(rate - median_sif_rate) > 0.12]
    systematic_ids = set(first.loc[first.annotator_id.isin(outlier_annotators), "expansion_id"])
    mandatory = uncertain_ids | rare_ids | systematic_ids
    remaining = source[~source.expansion_id.isin(mandatory)].copy()
    remaining["sample_key"] = remaining.expansion_id.map(lambda value: stable_key(value, "pass2-random"))
    random_count = max(1, round(0.15 * len(remaining)))
    random_ids = set(remaining.sort_values("sample_key").head(random_count).expansion_id)
    selected_ids = mandatory | random_ids
    second = source[source.expansion_id.isin(selected_ids)].copy()
    second["pass2_selection_reason"] = second.expansion_id.map(
        lambda value: ";".join(
            reason for condition, reason in (
                (value in uncertain_ids, "SIF_UNCERTAIN"),
                (value in rare_ids, "RARE_RULE_POSITIVE"),
                (value in systematic_ids, "SYSTEMATIC_FIRST_PASS_SIF_RATE_OUTLIER_BATCH"),
                (value in random_ids, "REPRODUCIBLE_15_PERCENT_RANDOM_REMAINDER"),
            ) if condition
        )
    )
    second = second.sort_values("expansion_id").reset_index(drop=True)
    second[source_columns() + ["pass2_selection_reason"]].to_csv(output_path, index=False, lineterminator="\n")
    batches = []
    for number, start in enumerate(range(0, len(second), 125), 1):
        input_path = DATA / f"annotation_pass2_batch_{number:02d}_input.csv"
        output = DATA / f"annotation_pass2_batch_{number:02d}.csv"
        second.iloc[start : start + 125][source_columns()].to_csv(input_path, index=False, lineterminator="\n")
        batches.append({"input": input_path.name, "input_sha256": sha256(input_path), "output": output.name, "rows": min(125, len(second) - start)})
    manifest = {
        "status": "FROZEN_BLINDED_SECOND_PASS_INPUT",
        "frozen_at_utc": utc_now(),
        "rows": len(second),
        "selection_counts": {"first_pass_sif_uncertain": len(uncertain_ids), "rare_rule_positive_union": len(rare_ids), "systematic_batch_union": len(systematic_ids), "random_remaining": len(random_ids)},
        "first_pass_positive_counts": positive_counts,
        "rare_rules_below_50_positive_first_pass": rare_rules,
        "first_pass_sif_rates_by_annotator": sif_rates,
        "systematic_sif_rate_outlier_annotators_over_0.12_from_median": outlier_annotators,
        "input_contains_first_pass_labels_or_rationales": False,
        "input_contains_model_predictions_or_scores": False,
        "input_sha256": sha256(output_path),
        "batches": batches,
    }
    json_write(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "rows": len(second), "batches": len(batches)}, indent=2))


def make_systematic_lsr08_review() -> None:
    path = DATA / "systematic_lsr08_review_input_v0_4.csv"
    manifest_path = DATA / "systematic_lsr08_review_manifest_v0_4.json"
    if path.exists() or manifest_path.exists():
        if not (path.exists() and manifest_path.exists()):
            raise RuntimeError("systematic LSR08 review is partially present")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(path) != manifest["input_sha256"]:
            raise RuntimeError("systematic LSR08 review input changed after freeze")
        print(json.dumps({"status": "already_frozen", "rows": manifest["rows"]}, indent=2))
        return
    first = load_and_validate_pass(1)
    base = pd.read_csv(DATA / "second_pass_input_v0_4.csv", dtype=str, keep_default_na=False)
    source = pd.read_csv(DATA / "selected_source_v0_4.csv", dtype=str, keep_default_na=False)
    ids = set(first.loc[first.LSR08_target == "POSITIVE", "expansion_id"]) - set(base.expansion_id)
    review = source[source.expansion_id.isin(ids)].copy().sort_values("expansion_id")
    review[source_columns()].to_csv(path, index=False, lineterminator="\n")
    batches = []
    for number, start in enumerate(range(0, len(review), 125), 1):
        input_path = DATA / f"annotation_systematic_lsr08_batch_{number:02d}_input.csv"
        output = DATA / f"annotation_systematic_lsr08_batch_{number:02d}.csv"
        review.iloc[start : start + 125][source_columns()].to_csv(input_path, index=False, lineterminator="\n")
        batches.append({"input": input_path.name, "input_sha256": sha256(input_path), "output": output.name, "rows": min(125, len(review) - start)})
    manifest = {
        "status": "FROZEN_BLINDED_SYSTEMATIC_LSR08_REVIEW",
        "frozen_at_utc": utc_now(), "rows": len(review),
        "reason": "Main-agent inspection found generic-work over-mapping among first-pass LSR08 positives; every remaining positive outside the base second pass is re-reviewed.",
        "input_contains_first_pass_labels_or_rationales": False,
        "input_sha256": sha256(path), "batches": batches,
    }
    json_write(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "rows": len(review), "batches": len(batches)}, indent=2))


def make_adjudication() -> None:
    input_path = DATA / "adjudication_input_v0_4.csv"
    manifest_path = DATA / "adjudication_manifest_v0_4.json"
    if input_path.exists() or manifest_path.exists():
        if not (input_path.exists() and manifest_path.exists()):
            raise RuntimeError("adjudication preparation is partially present")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(input_path) != manifest["input_sha256"]:
            raise RuntimeError("adjudication input changed after freeze")
        print(json.dumps({"status": "already_frozen", "rows": manifest["rows"]}, indent=2))
        return
    first = load_and_validate_pass(1).set_index("expansion_id")
    second = load_and_validate_pass(2).set_index("expansion_id")
    source = pd.read_csv(DATA / "selected_source_v0_4.csv", dtype=str, keep_default_na=False)
    source = source[source.expansion_id.isin(first.index)].set_index("expansion_id")
    target_columns = ["sif_label"] + [f"{rule}_target" for rule in RULE_IDS]
    rows: list[dict[str, Any]] = []
    conflict_counts: Counter[str] = Counter()
    for expansion_id in second.index:
        conflicts = [column for column in target_columns if first.loc[expansion_id, column] != second.loc[expansion_id, column]]
        if not conflicts:
            continue
        conflict_counts.update(conflicts)
        row = source.loc[expansion_id].to_dict()
        row["expansion_id"] = expansion_id
        row["conflict_fields"] = ";".join(conflicts)
        rows.append(row)
    adjudication = pd.DataFrame(rows)
    if len(adjudication):
        adjudication = adjudication[source_columns() + ["conflict_fields"]].sort_values("expansion_id")
    else:
        adjudication = pd.DataFrame(columns=source_columns() + ["conflict_fields"])
    adjudication.to_csv(input_path, index=False, lineterminator="\n")
    batches = []
    for number, start in enumerate(range(0, len(adjudication), 125), 1):
        batch_input = DATA / f"annotation_adjudication_batch_{number:02d}_input.csv"
        output = DATA / f"annotation_adjudication_batch_{number:02d}.csv"
        adjudication.iloc[start : start + 125][source_columns()].to_csv(batch_input, index=False, lineterminator="\n")
        batches.append({"input": batch_input.name, "input_sha256": sha256(batch_input), "output": output.name, "rows": min(125, len(adjudication) - start)})
    manifest = {
        "status": "FROZEN_ADJUDICATION_INPUT",
        "frozen_at_utc": utc_now(),
        "rows": len(adjudication),
        "conflict_counts": dict(conflict_counts),
        "input_exposes_first_or_second_labels": False,
        "input_sha256": sha256(input_path),
        "batches": batches,
    }
    json_write(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "rows": len(adjudication), "batches": len(batches)}, indent=2))


def recover_stalled_second_pass_batch_02() -> None:
    """Preserve a stalled reviewer batch without falsely calling it a second review.

    The source packet was intentionally blinded.  Once the assigned GPT worker
    stalled, recreating its labels from a local heuristic or silently fabricating
    a second independent opinion would be worse than retaining the already
    validated first-pass record.  This recovery makes a schema-valid PASS2 file
    solely so the frozen workflow is mechanically complete, and marks every row
    as non-independent.  ``assemble`` excludes it from agreement statistics.
    """
    input_path = DATA / "annotation_pass2_batch_02_input.csv"
    output_path = DATA / "annotation_pass2_batch_02.csv"
    report_path = REPORTS / "stalled_second_pass_recovery_v0_4.json"
    if output_path.exists():
        print(json.dumps({"status": "already_present", "path": output_path.name}, indent=2))
        return
    source = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    first = load_and_validate_pass(1).set_index("expansion_id")
    if not set(source.expansion_id).issubset(first.index):
        raise RuntimeError("Stalled second-pass input includes records without a validated first pass")
    recovered = first.loc[source.expansion_id].reset_index()[annotation_columns()].copy()
    # Keep identity/order from the blind input authoritative.
    for column in ("expansion_id", "candidate_id", "normalized_narrative_sha256"):
        recovered[column] = source[column].to_numpy()
    recovered["annotation_pass"] = "PASS2"
    recovered["annotation_status"] = "RECOVERED_FIRST_PASS_NOT_INDEPENDENT"
    recovered["annotator_id"] = "main-agent-recovery-not-independent-batch-02"
    recovered["annotated_at_utc"] = utc_now()
    errors = validate_annotation(recovered, source, "PASS2")
    if errors:
        raise RuntimeError("Recovered second pass failed validation:\n" + "\n".join(errors[:25]))
    recovered.to_csv(output_path, index=False, lineterminator="\n")
    json_write(report_path, {
        "status": "RECOVERED_NOT_INDEPENDENT",
        "rows": len(recovered),
        "reason": "The already-started GPT-5.6 Sol batch-02 reviewer stalled without producing an output. The validated first-pass values were retained, not re-labelled or represented as an independent second review.",
        "output": output_path.name,
        "output_sha256": sha256(output_path),
        "agreement_statistics_exclude_rows": True,
        "limitations": ["These rows received no independent second-pass check.", "No local classifier or generative runtime model was used to manufacture replacement labels."],
    })
    print(json.dumps({"status": "recovered_not_independent", "rows": len(recovered)}, indent=2))


def load_adjudication() -> pd.DataFrame:
    if not (DATA / "adjudication_manifest_v0_4.json").exists():
        return pd.DataFrame(columns=annotation_columns())
    manifest = json.loads((DATA / "adjudication_manifest_v0_4.json").read_text(encoding="utf-8"))
    if not manifest["batches"]:
        return pd.DataFrame(columns=annotation_columns())
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for item in manifest["batches"]:
        source = pd.read_csv(DATA / item["input"], dtype=str, keep_default_na=False)
        output_path = DATA / item["output"]
        if not output_path.exists():
            errors.append(f"missing {output_path.name}")
            continue
        frame = pd.read_csv(output_path, dtype=str, keep_default_na=False)
        errors.extend(f"{output_path.name}: {error}" for error in validate_annotation(frame, source, "ADJUDICATION"))
        frames.append(frame)
    if errors:
        raise RuntimeError("Adjudication validation failed:\n" + "\n".join(errors[:100]))
    return pd.concat(frames, ignore_index=True)


def assemble() -> None:
    final_path = DATA / "annotations_final_v0_4.csv"
    manifest_path = DATA / "annotation_freeze_manifest_v0_4.json"
    if final_path.exists() or manifest_path.exists():
        if not (final_path.exists() and manifest_path.exists()):
            raise RuntimeError("final annotation assembly is partially present")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(final_path) != manifest["final_annotations_sha256"]:
            raise RuntimeError("final annotations changed after freeze")
        print(json.dumps({"status": "already_frozen", "rows": manifest["rows"]}, indent=2))
        return
    first = load_and_validate_pass(1).set_index("expansion_id")
    source = pd.read_csv(DATA / "selected_source_v0_4.csv", dtype=str, keep_default_na=False)
    source = source[source.expansion_id.isin(first.index)].copy()
    source.insert(2, "incident_id", source.candidate_id)
    second_frame = load_and_validate_pass(2)
    second = second_frame.set_index("expansion_id")
    adjudication_frame = load_adjudication()
    adjudication = adjudication_frame.set_index("expansion_id") if len(adjudication_frame) else adjudication_frame
    target_columns = ["sif_label"] + [f"{rule}_target" for rule in RULE_IDS]
    annotation_fields = [column for column in annotation_columns() if column not in {"expansion_id", "candidate_id", "normalized_narrative_sha256"}]
    final_rows: list[dict[str, Any]] = []
    resolution_counts: Counter[str] = Counter()
    for source_row in source.to_dict("records"):
        expansion_id = source_row["expansion_id"]
        chosen = first.loc[expansion_id].to_dict()
        resolution = "FIRST_PASS_NOT_SELECTED_FOR_SECOND_PASS"
        second_is_independent = expansion_id in second.index and second.loc[expansion_id, "annotation_status"] != "RECOVERED_FIRST_PASS_NOT_INDEPENDENT"
        if expansion_id in second.index and not second_is_independent:
            resolution = "SECOND_PASS_RECOVERY_NOT_INDEPENDENT_RETAIN_FIRST_PASS"
        elif expansion_id in second.index:
            conflicts = [column for column in target_columns if first.loc[expansion_id, column] != second.loc[expansion_id, column]]
            if not conflicts:
                resolution = "FIRST_SECOND_PASS_AGREEMENT"
            elif expansion_id in adjudication.index:
                chosen = adjudication.loc[expansion_id].to_dict()
                resolution = "THIRD_PASS_BLIND_ADJUDICATION"
                for column in conflicts:
                    three = {first.loc[expansion_id, column], second.loc[expansion_id, column], adjudication.loc[expansion_id, column]}
                    if len(three) == 3:
                        chosen[column] = "UNCERTAIN" if column == "sif_label" else "UNKNOWN"
                        resolution = "THREE_WAY_DISAGREEMENT_RETAINED_UNRESOLVED"
                        if column == "sif_label":
                            chosen["uncertainty_reason"] = "Three independent GPT-5.6 Sol passes assigned different SIF targets."
                        else:
                            rule_id = column.removesuffix("_target")
                            chosen[f"{rule_id}_unknown_reason"] = "Three independent GPT-5.6 Sol passes assigned different relevance targets."
            else:
                # The user asked not to create further workers.  Retain a
                # conservative unresolved target rather than choose between
                # two independent AI opinions without a blinded adjudicator.
                resolution = "TWO_PASS_DISAGREEMENT_RETAINED_UNRESOLVED"
                for column in conflicts:
                    if column == "sif_label":
                        chosen[column] = "UNCERTAIN"
                        chosen["uncertainty_reason"] = "Independent GPT-5.6 Sol passes disagreed; no additional adjudicator was initiated."
                    else:
                        rule_id = column.removesuffix("_target")
                        chosen[column] = "UNKNOWN"
                        chosen[f"{rule_id}_unknown_reason"] = "Independent GPT-5.6 Sol passes disagreed; no additional adjudicator was initiated."
        final = dict(source_row)
        for column in annotation_fields:
            final[column] = chosen.get(column, "")
        final["first_pass_annotator_id"] = first.loc[expansion_id, "annotator_id"]
        final["second_pass_annotator_id"] = second.loc[expansion_id, "annotator_id"] if expansion_id in second.index else ""
        final["adjudicator_id"] = adjudication.loc[expansion_id, "annotator_id"] if len(adjudication) and expansion_id in adjudication.index else ""
        final["final_review_status"] = resolution
        final["final_label_provenance"] = "AI_ASSISTED_GPT_5_6_SOL_CONSENSUS_OR_ADJUDICATION_NOT_HSE_GROUND_TRUTH"
        final_rows.append(final)
        resolution_counts[resolution] += 1
    final_frame = pd.DataFrame(final_rows)
    final_frame.to_csv(final_path, index=False, lineterminator="\n")
    split_files: dict[str, Any] = {}
    for partition, filename in (
        ("train_addition", "train_addition_v0_4.csv"),
        ("development_addition", "development_addition_v0_4.csv"),
        ("fresh_final_assessment", "fresh_final_assessment_v0_4.csv"),
    ):
        path = DATA / filename
        subset = final_frame[final_frame.partition == partition].copy()
        subset.to_csv(path, index=False, lineterminator="\n")
        split_files[partition] = {"path": filename, "rows": len(subset), "sha256": sha256(path), "sif_counts": subset.sif_label.value_counts().to_dict()}

    independent_ids = [
        expansion_id for expansion_id in second.index
        if second.loc[expansion_id, "annotation_status"] != "RECOVERED_FIRST_PASS_NOT_INDEPENDENT"
    ]
    joined = first.loc[independent_ids].join(second.loc[independent_ids, target_columns], how="inner", rsuffix="_pass2")
    agreement = {
        "reviewed_rows": len(joined),
        "non_independent_recovery_rows_excluded_from_agreement": int(len(second) - len(joined)),
        "sif": {
            "agreement_rate": float((joined.sif_label == joined.sif_label_pass2).mean()),
            "cohen_kappa": float(cohen_kappa_score(joined.sif_label, joined.sif_label_pass2)),
            "confusion": pd.crosstab(joined.sif_label, joined.sif_label_pass2).to_dict(),
        },
        "rules": {},
        "resolution_counts": dict(resolution_counts),
    }
    for rule_id in RULE_IDS:
        left, right = f"{rule_id}_target", f"{rule_id}_target_pass2"
        agreement["rules"][rule_id] = {
            "agreement_rate": float((joined[left] == joined[right]).mean()),
            "cohen_kappa": float(cohen_kappa_score(joined[left], joined[right])),
            "pass1_positive": int((joined[left] == "POSITIVE").sum()),
            "pass2_positive": int((joined[right] == "POSITIVE").sum()),
        }
    json_write(REPORTS / "annotation_agreement_v0_4.json", agreement)
    manifest = {
        "status": "FROZEN_REFERENCES_BEFORE_MODEL_TRAINING_OR_FINAL_SCORING",
        "frozen_at_utc": utc_now(),
        "rows": len(final_frame),
        "selected_rows": TARGET_ROWS,
        "unannotated_rows": TARGET_ROWS - len(final_frame),
        "unannotated_scope": "annotation_batch_04_input.csv excluded at user direction; not used for labels, training, development, final assessment, or retrieval",
        "annotation_version": ANNOTATION_VERSION,
        "provenance": "AI-assisted GPT-5.6 Sol prototype references; not HSE expert ground truth",
        "final_annotations_sha256": sha256(final_path),
        "sif_counts": final_frame.sif_label.value_counts().to_dict(),
        "rule_target_counts": {rule: final_frame[f"{rule}_target"].value_counts().to_dict() for rule in RULE_IDS},
        "split_files": split_files,
        "source_file_sha256": sha256(DATA / "selected_source_v0_4.csv"),
        "first_pass_files": {path.name: sha256(path) for path in sorted(DATA.glob("annotation_batch_*_pass1.csv"))},
        "second_pass_files": {path.name: sha256(path) for path in sorted(DATA.glob("annotation_pass2_batch_[0-9][0-9].csv"))},
        "adjudication_files": {path.name: sha256(path) for path in sorted(DATA.glob("annotation_adjudication_batch_[0-9][0-9].csv"))},
        "unresolved_sif_excluded_from_binary_training": True,
        "unknown_lsr_targets_masked_per_rule": True,
    }
    json_write(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "rows": len(final_frame), "sif_counts": manifest["sif_counts"], "resolutions": dict(resolution_counts)}, indent=2))


def verify_annotation_freeze() -> dict[str, Any]:
    manifest = json.loads((DATA / "annotation_freeze_manifest_v0_4.json").read_text(encoding="utf-8"))
    if manifest["status"] != "FROZEN_REFERENCES_BEFORE_MODEL_TRAINING_OR_FINAL_SCORING":
        raise RuntimeError("v0.4 references are not frozen")
    if sha256(DATA / "annotations_final_v0_4.csv") != manifest["final_annotations_sha256"]:
        raise RuntimeError("v0.4 annotations differ from the freeze manifest")
    for item in manifest["split_files"].values():
        if sha256(DATA / item["path"]) != item["sha256"]:
            raise RuntimeError(f"v0.4 split changed after freeze: {item['path']}")
    return manifest


def binary_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    return frame[frame.sif_label.isin([SIF, NON_SIF])].copy()


def search_tfidf(train: pd.DataFrame, dev: pd.DataFrame, checkpoint: str) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    y_train = (train.sif_label == SIF).astype(int).to_numpy()
    y_dev = (dev.sif_label == SIF).astype(int).to_numpy()
    weights = {"none": None, "balanced": "balanced", "non_sif_1_5": {0: 1.5, 1: 1.0}}
    models: dict[tuple[float, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for c in (0.5, 1.0, 2.0):
        for weight_name, class_weight in weights.items():
            model = build_tfidf(c, class_weight).fit(train.narrative, y_train)
            models[(c, weight_name)] = model
            scores, classes, positive_index = positive_scores(model, dev.narrative.tolist())
            for threshold in np.arange(0.20, 0.81, 0.05):
                for width in (0.05, 0.10):
                    rows.append({
                        "checkpoint": checkpoint, "model_family": "tfidf", "c": c,
                        "class_weight": weight_name, "classes": classes,
                        "positive_probability_column": positive_index,
                        **binary_metrics(y_dev, scores, float(threshold)),
                        **routing_metrics(y_dev, scores, max(0.05, float(threshold - width)), min(0.95, float(threshold + width))),
                    })
    selected = select_sif_operating_point(rows, float(y_dev.mean()))
    selected.update({
        "checkpoint": checkpoint,
        "training_rows": len(train),
        "training_class_counts": train.sif_label.value_counts().to_dict(),
        "development_rows": len(dev),
        "development_class_counts": dev.sif_label.value_counts().to_dict(),
        "declared_objective": "Pass recall, specificity, balanced-accuracy, precision-over-all-SIF, and review-workload gates; then maximize balanced accuracy, F2, recall, specificity, precision, and lower review rate.",
        "fit_scope": "training_only_no_refit_after_threshold_selection",
    })
    return models[(float(selected["c"]), selected["class_weight"])], selected, rows


def setfit_texts(model: Any, values: list[str]) -> tuple[list[str], dict[str, int]]:
    tokenizer = model.model_body.tokenizer
    output: list[str] = []
    over_limit = 0
    max_tokens = 0
    for value in values:
        tokens = tokenizer.encode(value, add_special_tokens=False, truncation=False)
        max_tokens = max(max_tokens, len(tokens))
        if len(tokens) > 250:
            over_limit += 1
            tokens = tokens[:125] + tokens[-125:]
            value = tokenizer.decode(tokens, skip_special_tokens=True)
        output.append(value)
    return output, {"reports_over_250_tokens": over_limit, "max_observed_tokens": max_tokens, "strategy": "head_125_plus_tail_125_tokens_before_special_tokens"}


def train_setfit_once(train: pd.DataFrame, dev: pd.DataFrame) -> tuple[Any | None, dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    try:
        from datasets import Dataset
        from setfit import SetFitModel, Trainer, TrainingArguments

        model_id = "sentence-transformers/all-MiniLM-L6-v2"
        model = SetFitModel.from_pretrained(model_id, labels=[0, 1], local_files_only=True)
        model.model_body.max_seq_length = 256
        train_texts, train_limits = setfit_texts(model, train.narrative.tolist())
        dev_texts, dev_limits = setfit_texts(model, dev.narrative.tolist())
        args = TrainingArguments(batch_size=16, num_epochs=1, num_iterations=5, seed=SEED, sampling_strategy="oversampling")
        trainer = Trainer(model=model, args=args, train_dataset=Dataset.from_dict({"text": train_texts, "label": (train.sif_label == SIF).astype(int).tolist()}))
        trainer.train()
        scores, classes, positive_index = positive_scores(model, dev_texts)
        y_dev = (dev.sif_label == SIF).astype(int).to_numpy()
        rows: list[dict[str, Any]] = []
        for threshold in np.arange(0.20, 0.81, 0.05):
            for width in (0.05, 0.10):
                rows.append({
                    "checkpoint": "all_700_additions", "model_family": "setfit_finetuned_v0.4",
                    "classes": classes, "positive_probability_column": positive_index,
                    **binary_metrics(y_dev, scores, float(threshold)),
                    **routing_metrics(y_dev, scores, max(0.05, float(threshold - width)), min(0.95, float(threshold + width))),
                })
        selected = select_sif_operating_point(rows, float(y_dev.mean()))
        selected.update({
            "status": "trained", "model_id": model_id, "training_rows": len(train),
            "task_specific_encoder_fine_tuning": True, "fit_scope": "training_only_no_refit",
            "input_limit_handling": {"train": train_limits, "development": dev_limits},
            "training_seconds": time.perf_counter() - started,
            "training_arguments": {"batch_size": 16, "num_epochs": 1, "num_iterations": 5, "sampling_strategy": "oversampling"},
        })
        path = ARTIFACTS / "setfit_candidate_v0_4"
        if path.exists():
            raise RuntimeError("SetFit output already exists; refusing to overwrite the frozen candidate")
        model.save_pretrained(path)
        return model, selected, rows
    except Exception as error:
        return None, {"status": "blocked", "blocker": f"{type(error).__name__}: {error}", "training_seconds": time.perf_counter() - started}, []


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def attach_old_rule_targets(frame: pd.DataFrame) -> pd.DataFrame:
    annotations = pd.read_csv(OLD_DATA / "lsr_annotations_train_dev_v0_2.csv", dtype=str, keep_default_na=False)
    columns = ["incident_id"] + [f"{rule}_target" for rule in RULE_IDS]
    return frame.merge(annotations[columns], on="incident_id", how="left", validate="one_to_one")


def tune_rule(classifier: Any, vectorizer: Any, dev: pd.DataFrame, rule_id: str) -> tuple[float, list[dict[str, Any]], str]:
    valid = dev[dev[f"{rule_id}_target"].isin(["POSITIVE", "NEGATIVE"])]
    labels = (valid[f"{rule_id}_target"] == "POSITIVE").astype(int).to_numpy()
    if labels.sum() < 2 or (labels == 0).sum() < 2:
        return 0.5, [], "fixed_default_insufficient_development_support"
    scores = classifier.predict_proba(vectorizer.transform(valid.narrative))[:, 1]
    rows = [evaluate(labels, scores, float(threshold), max(0.05, float(threshold - 0.10)), float(threshold))["binary_prediction_metrics"] for threshold in np.arange(0.20, 0.81, 0.05)]
    selected = max(rows, key=lambda row: (row["f1"], row["recall"], row["precision"], row["specificity"]))
    return float(selected["threshold"]), rows, "selected_on_development"


def train_lsr_v0_4(old_train: pd.DataFrame, old_dev: pd.DataFrame, new_train: pd.DataFrame, new_dev: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    train = pd.concat([attach_old_rule_targets(old_train), new_train], ignore_index=True, sort=False)
    dev = pd.concat([attach_old_rule_targets(old_dev), new_dev], ignore_index=True, sort=False)
    vectorizer = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.99, sublinear_tf=True, strip_accents="unicode")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
    ])
    vectorizer.fit(train.narrative)
    reference = json.loads(RULES.read_text(encoding="utf-8"))
    names = {item["id"]: item["name"] for item in reference["rules"]}
    artifact: dict[str, Any] = {
        "version": "iogp-lsr-v0.4-experimental", "reference_id": reference["reference_id"],
        "reference": reference, "annotation_version": ANNOTATION_VERSION, "vectorizer": vectorizer, "rules": {},
        "input_allowlist": ["narrative"], "unknown_targets_masked": True,
    }
    report: dict[str, Any] = {"reference_id": reference["reference_id"], "annotation_version": ANNOTATION_VERSION, "rules": {}}
    for rule_id in RULE_IDS:
        train_valid = train[train[f"{rule_id}_target"].isin(["POSITIVE", "NEGATIVE"])]
        dev_valid = dev[dev[f"{rule_id}_target"].isin(["POSITIVE", "NEGATIVE"])]
        train_counts = train_valid[f"{rule_id}_target"].value_counts().to_dict()
        dev_counts = dev[f"{rule_id}_target"].value_counts().to_dict()
        if train_counts.get("POSITIVE", 0) < 3 or train_counts.get("NEGATIVE", 0) < 3:
            artifact["rules"][rule_id] = {"available": False, "name": names[rule_id], "reason": "insufficient_positive_or_negative_training_support"}
            report["rules"][rule_id] = {"status": "unavailable", "training_counts": train_counts, "development_counts": dev_counts}
            continue
        classifier = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000, random_state=SEED).fit(
            vectorizer.transform(train_valid.narrative),
            (train_valid[f"{rule_id}_target"] == "POSITIVE").astype(int),
        )
        threshold, threshold_rows, threshold_status = tune_rule(classifier, vectorizer, dev, rule_id)
        spec = {"available": True, "name": names[rule_id], "classifier": classifier, "threshold": threshold, "borderline_threshold": max(0.05, threshold - 0.10)}
        artifact["rules"][rule_id] = spec
        metrics: dict[str, Any] = {"status": "insufficient_two_class_development_support"}
        labels = (dev_valid[f"{rule_id}_target"] == "POSITIVE").astype(int).to_numpy()
        if len(set(labels)) == 2:
            scores = classifier.predict_proba(vectorizer.transform(dev_valid.narrative))[:, 1]
            metrics = evaluate(labels, scores, threshold, spec["borderline_threshold"], threshold)["binary_prediction_metrics"]
        report["rules"][rule_id] = {
            "status": "trained", "training_counts": train_counts, "development_counts": dev_counts,
            "threshold": threshold, "threshold_status": threshold_status,
            "development_metrics": metrics, "threshold_search": threshold_rows,
        }
    report["coverage"] = {
        "available_rules": [rule for rule, spec in artifact["rules"].items() if spec["available"]],
        "unavailable_rules": [rule for rule, spec in artifact["rules"].items() if not spec["available"]],
        "unavailable_rules_excluded_from_aggregate_metrics": True,
    }
    return artifact, report


def train_models() -> None:
    verify_annotation_freeze()
    selection_path = ARTIFACTS / "selection_manifest_v0_4.json"
    if selection_path.exists():
        raise RuntimeError("v0.4 selection manifest already exists; refusing to retrain or replace frozen artifacts")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    old_train = binary_frame(OLD_DATA / "train_v0_2.csv")
    old_dev = binary_frame(OLD_DATA / "development_v0_2.csv")
    new_train_all = pd.read_csv(DATA / "train_addition_v0_4.csv", dtype=str, keep_default_na=False)
    new_dev_all = pd.read_csv(DATA / "development_addition_v0_4.csv", dtype=str, keep_default_na=False)
    new_train = new_train_all[new_train_all.sif_label.isin([SIF, NON_SIF])].copy()
    new_dev = new_dev_all[new_dev_all.sif_label.isin([SIF, NON_SIF])].copy()
    fixed_dev = pd.concat([old_dev, new_dev], ignore_index=True, sort=False)
    new_train["source_batch"] = new_train.expansion_id.str.extract(r"(\d+)$").astype(int).iloc[:, 0].map(lambda value: (value - 1) // 250 + 1)
    checkpoints = [("existing_only", old_train)]
    for batch in sorted(new_train.source_batch.unique()):
        cumulative = new_train[new_train.source_batch <= batch]
        checkpoints.append((f"through_annotation_batch_{batch:02d}", pd.concat([old_train, cumulative], ignore_index=True, sort=False)))
    learning_rows: list[dict[str, Any]] = []
    final_tfidf = None
    final_tfidf_selected: dict[str, Any] | None = None
    all_search_rows: list[dict[str, Any]] = []
    for checkpoint, train in checkpoints:
        model, selected, rows = search_tfidf(train, fixed_dev, checkpoint)
        learning_rows.append(selected)
        all_search_rows.extend(rows)
        final_tfidf, final_tfidf_selected = model, selected
    assert final_tfidf is not None and final_tfidf_selected is not None
    joblib.dump(final_tfidf, ARTIFACTS / "sif_tfidf_v0_4.joblib")
    pd.DataFrame(all_search_rows).to_csv(REPORTS / "sif_tfidf_development_search_v0_4.csv", index=False, lineterminator="\n")
    json_write(REPORTS / "sif_learning_curve_v0_4.json", {
        "fixed_development_rows": len(fixed_dev), "fixed_development_class_counts": fixed_dev.sif_label.value_counts().to_dict(),
        "all_sif_reference": constant_baseline((fixed_dev.sif_label == SIF).astype(int).to_numpy(), 1),
        "checkpoints": learning_rows,
    })
    full_train = pd.concat([old_train, new_train], ignore_index=True, sort=False)
    setfit_model, setfit_selected, setfit_rows = train_setfit_once(full_train, fixed_dev)
    pd.DataFrame(setfit_rows).to_csv(REPORTS / "sif_setfit_development_search_v0_4.csv", index=False, lineterminator="\n")
    lsr_artifact, lsr_report = train_lsr_v0_4(old_train, old_dev, new_train_all, new_dev_all)
    joblib.dump(lsr_artifact, ARTIFACTS / "lsr_model_v0_4.joblib")
    json_write(REPORTS / "lsr_development_evaluation_v0_4.json", lsr_report)

    candidates = [("tfidf_v0.4", final_tfidf_selected, True)]
    if setfit_model is not None and setfit_selected.get("development_gate_passed"):
        candidates.append(("setfit_v0.4", setfit_selected, False))
    passing = [item for item in candidates if item[1].get("development_gate_passed")]
    selected_name = None
    selected = None
    if passing:
        tfidf_item = next((item for item in passing if item[0] == "tfidf_v0.4"), None)
        best = max(passing, key=lambda item: (item[1]["balanced_accuracy"], item[1]["f2"], item[1]["recall"], item[1]["specificity"], item[1]["precision"], -item[1]["review_rate"]))
        if tfidf_item and tfidf_item[1]["balanced_accuracy"] >= best[1]["balanced_accuracy"] - 0.02:
            best = tfidf_item
        selected_name, selected, _ = best
    artifacts = {
        "tfidf": {"path": "sif_tfidf_v0_4.joblib", "sha256": sha256(ARTIFACTS / "sif_tfidf_v0_4.joblib")},
        "lsr": {"path": "lsr_model_v0_4.joblib", "sha256": sha256(ARTIFACTS / "lsr_model_v0_4.joblib")},
    }
    if setfit_model is not None:
        artifacts["setfit"] = {"path": "setfit_candidate_v0_4", "directory_sha256": directory_sha256(ARTIFACTS / "setfit_candidate_v0_4")}
    json_write(selection_path, {
        "status": "FROZEN_CANDIDATE_AND_THRESHOLDS_BEFORE_FINAL_ASSESSMENT",
        "frozen_at_utc": utc_now(), "random_seed": SEED,
        "development_gates": SIF_DEVELOPMENT_GATES,
        "selection_objective": "Pass all gates; maximize balanced accuracy then F2/recall/specificity/precision; prefer TF-IDF when balanced accuracy is within 0.02.",
        "selected_family": selected_name, "selected_operating_point": selected,
        "tfidf": final_tfidf_selected, "setfit": setfit_selected,
        "training_counts": full_train.sif_label.value_counts().to_dict(),
        "development_counts": fixed_dev.sif_label.value_counts().to_dict(),
        "unresolved_excluded": {"train": int((new_train_all.sif_label == "UNCERTAIN").sum()), "development": int((new_dev_all.sif_label == "UNCERTAIN").sum())},
        "artifacts": artifacts,
        "annotation_freeze_manifest_sha256": sha256(DATA / "annotation_freeze_manifest_v0_4.json"),
    })
    print(json.dumps({"status": "trained_and_frozen", "selected_family": selected_name, "tfidf_gate": final_tfidf_selected["development_gate_passed"], "setfit_status": setfit_selected.get("status")}, indent=2))


def score_sif(model: Any, frame: pd.DataFrame, operating: dict[str, Any], setfit: bool = False) -> tuple[dict[str, Any], np.ndarray]:
    texts = frame.narrative.tolist()
    limit_report = None
    if setfit:
        texts, limit_report = setfit_texts(model, texts)
    scores, classes, positive_index = positive_scores(model, texts)
    labels = (frame.sif_label == SIF).astype(int).to_numpy()
    result = evaluate(labels, scores, float(operating["threshold"]), float(operating["lower"]), float(operating["upper"]))
    result["class_mapping"] = {"classes": classes, "positive_probability_column": positive_index}
    if limit_report:
        result["input_limit_handling"] = limit_report
    return result, scores


def evaluate_lsr_artifact(artifact: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    report: dict[str, Any] = {"artifact_version": artifact.get("version"), "rules": {}}
    aggregate = Counter()
    f1_values: list[float] = []
    for rule_id in RULE_IDS:
        spec = artifact["rules"].get(rule_id, {"available": False, "reason": "missing_rule"})
        counts = frame[f"{rule_id}_target"].value_counts().to_dict()
        if not spec.get("available"):
            report["rules"][rule_id] = {"status": "unavailable", "target_counts": counts, "reason": spec.get("reason", "unavailable")}
            continue
        valid = frame[frame[f"{rule_id}_target"].isin(["POSITIVE", "NEGATIVE"])]
        labels = (valid[f"{rule_id}_target"] == "POSITIVE").astype(int).to_numpy()
        if not len(valid) or len(set(labels)) < 2:
            report["rules"][rule_id] = {"status": "insufficient_two_class_evaluation_support", "target_counts": counts, "threshold": spec["threshold"]}
            continue
        scores = spec["classifier"].predict_proba(artifact["vectorizer"].transform(valid.narrative))[:, 1]
        metrics = evaluate(labels, scores, float(spec["threshold"]), float(spec.get("borderline_threshold", max(0.05, spec["threshold"] - 0.10))), float(spec["threshold"]))["binary_prediction_metrics"]
        report["rules"][rule_id] = {"status": "evaluated", "target_counts": counts, "threshold": spec["threshold"], "metrics": metrics}
        for aggregate_key, metric_key in (
            ("tp", "true_positives"), ("fp", "false_positives"),
            ("tn", "true_negatives"), ("fn", "false_negatives"),
        ):
            aggregate[aggregate_key] += metrics[metric_key]
        f1_values.append(metrics["f1"])
    tp, fp, tn, fn = aggregate["tp"], aggregate["fp"], aggregate["tn"], aggregate["fn"]
    report["aggregate"] = {
        "available_rules": [rule for rule in RULE_IDS if artifact["rules"].get(rule, {}).get("available")],
        "unavailable_rules": [rule for rule in RULE_IDS if not artifact["rules"].get(rule, {}).get("available")],
        "unavailable_rules_excluded": True,
        "evaluated_rules": len(f1_values),
        "micro_precision": tp / (tp + fp) if tp + fp else 0.0,
        "micro_recall": tp / (tp + fn) if tp + fn else 0.0,
        "micro_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        "macro_f1": float(np.mean(f1_values)) if f1_values else None,
        "aggregate_confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }
    return report


def evaluate_frozen() -> None:
    verify_annotation_freeze()
    selection_path = ARTIFACTS / "selection_manifest_v0_4.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection["status"] != "FROZEN_CANDIDATE_AND_THRESHOLDS_BEFORE_FINAL_ASSESSMENT":
        raise RuntimeError("candidate is not frozen")
    for name in ("tfidf", "lsr"):
        item = selection["artifacts"][name]
        if sha256(ARTIFACTS / item["path"]) != item["sha256"]:
            raise RuntimeError(f"{name} artifact changed after freeze")
    final_all = pd.read_csv(DATA / "fresh_final_assessment_v0_4.csv", dtype=str, keep_default_na=False)
    final = final_all[final_all.sif_label.isin([SIF, NON_SIF])].copy()
    regression = binary_frame(OLD_DATA / "protected_test_v0_2.csv")
    baseline = joblib.load(BASELINE_ARTIFACT)
    baseline_operating = {"threshold": 0.40, "lower": 0.35, "upper": 0.45}
    selected_name = selection["selected_family"]
    candidate = None
    candidate_is_setfit = selected_name == "setfit_v0.4"
    if selected_name == "tfidf_v0.4":
        candidate = joblib.load(ARTIFACTS / "sif_tfidf_v0_4.joblib")
    elif candidate_is_setfit:
        from setfit import SetFitModel
        if directory_sha256(ARTIFACTS / "setfit_candidate_v0_4") != selection["artifacts"]["setfit"]["directory_sha256"]:
            raise RuntimeError("SetFit artifact changed after freeze")
        candidate = SetFitModel.from_pretrained(str(ARTIFACTS / "setfit_candidate_v0_4"), local_files_only=True)

    datasets: dict[str, Any] = {}
    prediction_frames: list[pd.DataFrame] = []
    for dataset_name, frame in (("fresh_final_assessment", final), ("old_90_report_regression_benchmark", regression)):
        labels = (frame.sif_label == SIF).astype(int).to_numpy()
        baseline_result, baseline_scores = score_sif(baseline, frame, baseline_operating)
        dataset_report: dict[str, Any] = {
            "rows_with_binary_reference": len(frame), "uncertain_reference_rows_excluded": int((final_all.sif_label == "UNCERTAIN").sum()) if dataset_name == "fresh_final_assessment" else 0,
            "class_counts": frame.sif_label.value_counts().to_dict(),
            "all_sif_reference": constant_baseline(labels, 1), "all_non_sif_reference": constant_baseline(labels, 0),
            "active_baseline_v0.1": baseline_result,
        }
        predictions = pd.DataFrame({"dataset": dataset_name, "incident_id": frame.incident_id, "reference_label": frame.sif_label, "active_baseline_score": baseline_scores})
        if candidate is not None:
            candidate_result, candidate_scores = score_sif(candidate, frame, selection["selected_operating_point"], candidate_is_setfit)
            dataset_report["selected_candidate"] = {"family": selected_name, **candidate_result}
            predictions["selected_candidate_score"] = candidate_scores
        datasets[dataset_name] = dataset_report
        prediction_frames.append(predictions)

    fresh_metrics = datasets["fresh_final_assessment"]
    if candidate is None:
        gates = {"candidate_selected_on_development": False}
    else:
        baseline_binary = fresh_metrics["active_baseline_v0.1"]["binary_prediction_metrics"]
        candidate_binary = fresh_metrics["selected_candidate"]["binary_prediction_metrics"]
        gates = {
            "candidate_selected_on_development": True,
            "candidate_f2_at_least_baseline": candidate_binary["f2"] >= baseline_binary["f2"],
            "candidate_recall_not_below_baseline_by_more_than_0.03": candidate_binary["recall"] >= baseline_binary["recall"] - 0.03,
            "candidate_specificity_not_below_baseline_by_more_than_0.03": candidate_binary["specificity"] >= baseline_binary["specificity"] - 0.03,
            "candidate_balanced_accuracy_at_least_baseline": candidate_binary["balanced_accuracy"] >= baseline_binary["balanced_accuracy"],
            "runtime_adapter_supported": selected_name == "tfidf_v0.4",
        }
    sif_promote = bool(gates) and all(gates.values())
    lsr_candidate = joblib.load(ARTIFACTS / "lsr_model_v0_4.joblib")
    lsr_active = joblib.load(ACTIVE_LSR_ARTIFACT)
    lsr_reports = {
        "active_v0.2": evaluate_lsr_artifact(lsr_active, final_all),
        "candidate_v0.4": evaluate_lsr_artifact(lsr_candidate, final_all),
    }
    candidate_lsr = lsr_reports["candidate_v0.4"]
    active_lsr = lsr_reports["active_v0.2"]
    new_rules = set(candidate_lsr["aggregate"]["available_rules"]) - set(active_lsr["aggregate"]["available_rules"])
    new_rule_checks = {
        rule: (
            candidate_lsr["rules"][rule].get("status") == "evaluated"
            and candidate_lsr["rules"][rule]["target_counts"].get("POSITIVE", 0) >= 2
            and candidate_lsr["rules"][rule]["metrics"]["f1"] >= 0.60
        ) for rule in sorted(new_rules)
    }
    lsr_gates = {
        "candidate_has_at_least_active_rule_coverage": len(candidate_lsr["aggregate"]["available_rules"]) >= len(active_lsr["aggregate"]["available_rules"]),
        "candidate_macro_f1_not_below_active_by_more_than_0.05": (
            candidate_lsr["aggregate"]["macro_f1"] is not None and active_lsr["aggregate"]["macro_f1"] is not None
            and candidate_lsr["aggregate"]["macro_f1"] >= active_lsr["aggregate"]["macro_f1"] - 0.05
        ),
        "new_rules_have_two_positive_final_examples_and_f1_at_least_0.60": all(new_rule_checks.values()) if new_rule_checks else False,
    }
    lsr_promote = all(lsr_gates.values())
    report = {
        "report_version": "domain-expansion-v0.4", "generated_at_utc": utc_now(),
        "fresh_final_status": "ONE_TIME_FROZEN_AI_ASSISTED_ASSESSMENT_NOT_HSE_EXPERT_GROUND_TRUTH",
        "old_regression_status": "DIAGNOSTIC_ONLY_ALREADY_INFORMED_PRIOR_MODEL_WORK",
        "selection_manifest_sha256": sha256(selection_path),
        "sif": {"datasets": datasets, "promotion_gates": gates, "decision": "PROMOTE_CANDIDATE" if sif_promote else "RETAIN_ACTIVE_BASELINE"},
        "lsr": {"evaluations": lsr_reports, "new_rule_checks": new_rule_checks, "promotion_gates": lsr_gates, "decision": "PROMOTE_CANDIDATE" if lsr_promote else "RETAIN_ACTIVE_V0.2"},
        "runtime_generative_llm_calls": False,
    }
    json_write(REPORTS / "final_evaluation_v0_4.json", report)
    pd.concat(prediction_frames, ignore_index=True).to_csv(REPORTS / "sif_predictions_v0_4.csv", index=False, lineterminator="\n")
    print(json.dumps({"sif_decision": report["sif"]["decision"], "lsr_decision": report["lsr"]["decision"], "fresh_binary_rows": len(final)}, indent=2))


def evaluate_setfit_posthoc() -> None:
    """Describe the already-frozen SetFit candidate without reopening selection.

    TF-IDF was the predeclared selected family, so SetFit was deliberately not
    part of the original promotion calculation.  This report is read-only
    follow-up evidence requested after finalisation; it cannot change the
    selected artifact, thresholds, promotion decision, or runtime.
    """
    verify_annotation_freeze()
    selection_path = ARTIFACTS / "selection_manifest_v0_4.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("setfit", {}).get("status") != "trained":
        raise RuntimeError("No trained SetFit candidate is available for post-hoc reporting")
    setfit_item = selection.get("artifacts", {}).get("setfit")
    setfit_path = ARTIFACTS / "setfit_candidate_v0_4"
    if not setfit_item or directory_sha256(setfit_path) != setfit_item["directory_sha256"]:
        raise RuntimeError("SetFit artifact differs from its frozen candidate manifest")
    from setfit import SetFitModel
    model = SetFitModel.from_pretrained(str(setfit_path), local_files_only=True)
    datasets: dict[str, Any] = {}
    for name, path in (
        ("fresh_final_assessment", DATA / "fresh_final_assessment_v0_4.csv"),
        ("old_90_report_regression_benchmark", OLD_DATA / "protected_test_v0_2.csv"),
    ):
        frame_all = pd.read_csv(path, dtype=str, keep_default_na=False)
        frame = frame_all[frame_all.sif_label.isin([SIF, NON_SIF])].copy()
        result, _ = score_sif(model, frame, selection["setfit"], setfit=True)
        labels = (frame.sif_label == SIF).astype(int).to_numpy()
        datasets[name] = {
            "rows_with_binary_reference": len(frame),
            "uncertain_reference_rows_excluded": int((frame_all.sif_label == "UNCERTAIN").sum()),
            "class_counts": frame.sif_label.value_counts().to_dict(),
            "all_sif_reference": constant_baseline(labels, 1),
            "all_non_sif_reference": constant_baseline(labels, 0),
            "setfit": result,
        }
    report = {
        "status": "POSTHOC_DESCRIPTIVE_NOT_USED_FOR_SELECTION_OR_PROMOTION",
        "generated_at_utc": utc_now(),
        "selection_manifest_sha256": sha256(selection_path),
        "frozen_operating_point": selection["setfit"],
        "datasets": datasets,
        "limitations": [
            "TF-IDF was selected before final assessment under the declared tie preference.",
            "This post-hoc report must not be used to reopen threshold selection or claim independent validation.",
        ],
    }
    json_write(REPORTS / "setfit_posthoc_evaluation_v0_4.json", report)
    print(json.dumps({"status": report["status"], "fresh_binary_rows": datasets["fresh_final_assessment"]["rows_with_binary_reference"]}, indent=2))


def finalize() -> None:
    evaluation_path = REPORTS / "final_evaluation_v0_4.json"
    selection_path = ARTIFACTS / "selection_manifest_v0_4.json"
    if not evaluation_path.exists() or not selection_path.exists():
        raise RuntimeError("training and frozen final evaluation must finish before finalization")
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    promoted = evaluation["sif"]["decision"] == "PROMOTE_CANDIDATE" or evaluation["lsr"]["decision"] == "PROMOTE_CANDIDATE"
    if promoted:
        raise RuntimeError("A candidate passed promotion gates; integrate and benchmark the exact artifact before finalizing")
    dependency_versions: dict[str, str | None] = {}
    for package in ("numpy", "pandas", "scikit-learn", "joblib", "setfit", "sentence-transformers", "torch"):
        try:
            dependency_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependency_versions[package] = None
    artifact_paths = [
        ARTIFACTS / "sif_tfidf_v0_4.joblib",
        ARTIFACTS / "lsr_model_v0_4.joblib",
        selection_path,
    ]
    report_paths = [
        REPORTS / "annotation_agreement_v0_4.json",
        REPORTS / "sif_learning_curve_v0_4.json",
        REPORTS / "sif_tfidf_development_search_v0_4.csv",
        REPORTS / "sif_setfit_development_search_v0_4.csv",
        REPORTS / "lsr_development_evaluation_v0_4.json",
        evaluation_path,
        REPORTS / "sif_predictions_v0_4.csv",
        REPORTS / "setfit_posthoc_evaluation_v0_4.json",
    ]
    data_paths = [
        DATA / "selection_freeze_manifest_v0_4.json",
        DATA / "annotation_freeze_manifest_v0_4.json",
        DATA / "annotations_final_v0_4.csv",
        DATA / "train_addition_v0_4.csv",
        DATA / "development_addition_v0_4.csv",
        DATA / "fresh_final_assessment_v0_4.csv",
    ]
    setfit_path = ARTIFACTS / "setfit_candidate_v0_4"
    manifest = {
        "version": "domain-expansion-v0.4", "created_at_utc": utc_now(), "random_seed": SEED,
        "active_sif_model": "sif-v0.1", "active_lsr_model": "iogp-lsr-v0.2",
        "candidate_sif_promoted": False, "candidate_lsr_promoted": False,
        "runtime_changed": False, "runtime_generative_llm_calls": False,
        "offline_annotation_model": "gpt-5.6-sol", "offline_annotation_is_hse_ground_truth": False,
        "latency": {"status": "reused_v0.2_benchmark_runtime_unchanged", "report": "reports/domain_adaptation_v0_2/runtime_benchmark.json"},
        "comparative_llm_benchmark": "not_run_no_authorised_comparable_runtime_benchmark",
        "software": {"python": platform.python_version(), "platform": platform.platform(), **dependency_versions},
        "artifacts": [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in artifact_paths],
        "setfit_artifact": {"path": str(setfit_path.relative_to(ROOT)).replace("\\", "/"), "directory_sha256": directory_sha256(setfit_path)} if setfit_path.exists() else None,
        "reports": [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)} for path in report_paths],
        "data": [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "rows": len(pd.read_csv(path, dtype=str, keep_default_na=False)) if path.suffix == ".csv" else None, "sha256": sha256(path)} for path in data_paths],
        "rollback": "No runtime promotion occurred. The backend remains on artifacts/supervised for SIF and domain_adapted_v0_2/lsr_model.joblib for IOGP mapping.",
    }
    json_write(ARTIFACTS / "artifact_manifest_v0_4.json", manifest)
    print(json.dumps({"status": "finalized", "runtime_changed": False}, indent=2))


def classify_retrieval_strata(text: str) -> list[str]:
    strata = [rule for rule, pattern in RULE_PATTERNS.items() if pattern.search(text)]
    if HIGH_RISK.search(text):
        strata.append("HIGH_RISK")
    if HAZARD_TERM.search(text) and HARD_NEGATIVE.search(text):
        strata.append("HAZARD_TERM_POSSIBLE_NON_SIF")
    return strata or ["GENERAL"]


def protected_frames() -> Iterable[pd.DataFrame]:
    paths = [
        ROOT / "data" / "domain_adaptation_v0_2" / "merged_incidents_v0_2.csv",
        ROOT / "data" / "domain_adaptation_v0_2" / "protected_test_v0_2.csv",
        ROOT / "data" / "domain_adaptation_v0_3" / "fresh_assessment_v0_3.csv",
        ROOT / "data" / "domain_adaptation_v0_3" / "lsr_candidate_review_v0_3.csv",
    ]
    for directory in (ROOT / "data" / "blind_test_v0_2", ROOT / "data" / "blind_test_v0_3"):
        paths.extend(directory.glob("*.csv"))
    for path in paths:
        if path.exists():
            yield pd.read_csv(path, dtype=str, keep_default_na=False)


def additional_exclusions(pool: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    ids: set[str] = set()
    source_ids: set[str] = set()
    groups: set[str] = set()
    hashes: set[str] = set()
    protected_texts: list[str] = []
    protected_files = 0
    for frame in protected_frames():
        protected_files += 1
        for column in ("incident_id", "candidate_id"):
            if column in frame:
                ids.update(value for value in frame[column] if value)
        if "source_record_id" in frame:
            source_ids.update(value for value in frame.source_record_id if value)
        if "duplicate_group" in frame:
            groups.update(value for value in frame.duplicate_group if value)
        narratives = frame.narrative if "narrative" in frame else []
        for narrative in narratives:
            norm = normalized_text(narrative)
            if norm:
                protected_texts.append(norm)
                hashes.add(hashlib.sha256(norm.encode("utf-8")).hexdigest())

    base = eligible_pool().copy()
    base = base[
        ~base.candidate_id.isin(ids)
        & ~base.source_record_id.isin(source_ids)
        & ~base.duplicate_group.isin(groups)
        & ~base.normalized_narrative_sha256.isin(hashes)
    ].copy()
    return base, {
        "protected_files_read": protected_files,
        "excluded_incident_ids": len(ids),
        "excluded_source_ids": len(source_ids),
        "excluded_duplicate_groups": len(groups),
        "excluded_normalized_hashes": len(hashes),
        "protected_normalized_texts": protected_texts,
    }


def diverse_preselection(pool: pd.DataFrame, target: int = 1600) -> pd.DataFrame:
    frame = pool.copy()
    frame["retrieval_strata"] = frame.narrative.map(lambda text: ";".join(classify_retrieval_strata(text)))
    frame["primary_stratum"] = frame.retrieval_strata.str.split(";").str[0]
    frame["selection_key"] = frame.candidate_id.map(stable_key)
    frame["length_band"] = pd.cut(
        frame.narrative.str.len(), bins=[0, 180, 360, 720, float("inf")],
        labels=["short", "medium", "long", "very_long"], include_lowest=True,
    ).astype(str)
    frame["activity_key"] = frame.activity_if_known.str.casefold().str.strip().replace("", "unknown")

    buckets: dict[str, list[dict[str, Any]]] = {}
    for stratum in list(RULE_PATTERNS) + ["HIGH_RISK", "HAZARD_TERM_POSSIBLE_NON_SIF", "GENERAL"]:
        subset = frame[frame.retrieval_strata.str.split(";").map(lambda values: stratum in values)]
        buckets[stratum] = subset.sort_values("selection_key").to_dict("records")
    quotas = {rule: 75 for rule in RULE_PATTERNS}
    quotas.update({"HIGH_RISK": 260, "HAZARD_TERM_POSSIBLE_NON_SIF": 300, "GENERAL": target})
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    group_ids: set[str] = set()
    activity_counts: Counter[str] = Counter()
    year_counts: Counter[str] = Counter()

    def add_from(bucket: list[dict[str, Any]], limit: int, enforce_caps: bool = True) -> None:
        for row in bucket:
            if len(selected) >= target or limit <= 0:
                return
            if row["candidate_id"] in selected_ids or row["duplicate_group"] in group_ids:
                continue
            if enforce_caps and (activity_counts[row["activity_key"]] >= 8 or year_counts[row["source_year"]] >= 180):
                continue
            selected.append(row)
            selected_ids.add(row["candidate_id"])
            group_ids.add(row["duplicate_group"])
            activity_counts[row["activity_key"]] += 1
            year_counts[row["source_year"]] += 1
            limit -= 1

    for name, quota in quotas.items():
        add_from(buckets[name], quota)
    if len(selected) < target:
        add_from(frame.sort_values("selection_key").to_dict("records"), target - len(selected), enforce_caps=False)
    return pd.DataFrame(selected)


def remove_near_duplicates(frame: pd.DataFrame, protected_texts: list[str], target: int) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    reference_texts = list(protected_texts)
    grams, inverted = build_near_duplicate_index(reference_texts)
    accepted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in frame.sort_values("selection_key").to_dict("records"):
        norm = normalized_text(row["narrative"])
        match = high_similarity_match(norm, reference_texts, grams, inverted)
        if match:
            excluded.append({"incident_id": row["candidate_id"], "reason": "high_similarity_near_duplicate", "jaccard": match[0], "sequence_ratio": match[1]})
            continue
        accepted.append(row)
        new_index = len(reference_texts)
        reference_texts.append(norm)
        new_grams = token_3grams(norm)
        grams.append(new_grams)
        for gram in new_grams:
            inverted[gram].append(new_index)
        if len(accepted) == target:
            break
    result = pd.DataFrame(accepted)
    return result, excluded


def prepare() -> None:
    source_path = DATA / "selected_source_v0_4.csv"
    manifest_path = DATA / "selection_freeze_manifest_v0_4.json"
    if source_path.exists() or manifest_path.exists():
        if not (source_path.exists() and manifest_path.exists()):
            raise RuntimeError("v0.4 selection is partially present; refusing to regenerate it")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(source_path) != manifest["selected_source_sha256"]:
            raise RuntimeError("v0.4 selected source differs from its freeze manifest")
        print(json.dumps({"status": "already_frozen", "rows": manifest["rows"]}, indent=2))
        return

    raw = pd.read_csv(POOL, dtype=str, keep_default_na=False)
    eligible, exclusion = additional_exclusions(raw)
    preliminary = diverse_preselection(eligible, target=1800)
    selected, near_excluded = remove_near_duplicates(preliminary, exclusion.pop("protected_normalized_texts"), TARGET_ROWS)
    if len(selected) != TARGET_ROWS:
        raise RuntimeError(f"Only {len(selected)} duplicate-isolated records could be selected")

    selected = selected.sort_values("selection_key").reset_index(drop=True)
    selected["partition"] = "train_addition"
    selected.loc[: FINAL_ROWS - 1, "partition"] = "fresh_final_assessment"
    selected.loc[FINAL_ROWS : FINAL_ROWS + DEV_ROWS - 1, "partition"] = "development_addition"
    selected["expansion_id"] = [f"EXP-V0.4-{number:04d}" for number in range(1, len(selected) + 1)]
    selected["normalized_narrative_sha256"] = selected.narrative.map(
        lambda text: hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()
    )
    selected["selection_basis"] = "deterministic_diversity_and_keyword_retrieval_before_annotation_no_model_predictions"
    output_columns = [
        "expansion_id", "candidate_id", "source", "source_record_id", "source_year",
        "report_type_if_known", "activity_if_known", "location_if_known", "narrative",
        "source_native_outcome", "source_native_classification", "duplicate_group",
        "normalized_narrative_sha256", "retrieval_strata", "primary_stratum", "length_band",
        "partition", "selection_basis",
    ]
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    selected[output_columns].to_csv(source_path, index=False, lineterminator="\n")
    batch_files = []
    for batch_number, start in enumerate(range(0, TARGET_ROWS, 250), 1):
        path = DATA / f"annotation_batch_{batch_number:02d}_input.csv"
        selected.iloc[start : start + 250][output_columns].to_csv(path, index=False, lineterminator="\n")
        batch_files.append({"path": path.name, "rows": min(250, TARGET_ROWS - start), "sha256": sha256(path)})
    pd.DataFrame(near_excluded).to_csv(DATA / "near_duplicate_exclusions_v0_4.csv", index=False, lineterminator="\n")
    manifest = {
        "status": "FROZEN_BEFORE_ANNOTATION_OR_MODEL_PREDICTIONS",
        "frozen_at_utc": utc_now(),
        "seed": SEED,
        "rows": len(selected),
        "partition_counts": selected.partition.value_counts().to_dict(),
        "source_counts": selected.source.value_counts().to_dict(),
        "year_counts": selected.source_year.value_counts().sort_index().to_dict(),
        "length_band_counts": selected.length_band.value_counts().to_dict(),
        "retrieval_stratum_counts": {name: int(selected.retrieval_strata.str.contains(fr"(?:^|;){name}(?:;|$)", regex=True).sum()) for name in list(RULE_PATTERNS) + ["HIGH_RISK", "HAZARD_TERM_POSSIBLE_NON_SIF", "GENERAL"]},
        "selection_policy": "Keyword/patterns select candidates only. Stable hashing and activity/year caps provide diversity. Labels are assigned later by contextual GPT-5.6 Sol review.",
        "partition_policy": "Exactly 150 fresh final, 150 development, and 700 training additions assigned by stable hash before annotation; no prediction-based selection.",
        "near_duplicate_policy": {"token_3gram_jaccard": 0.82, "character_sequence_ratio": 0.92, "excluded_rows": len(near_excluded)},
        "guide": {"path": str(GUIDE.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(GUIDE), "version": GUIDE_VERSION},
        "rules": {"path": str(RULES.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(RULES)},
        "annotation_version": ANNOTATION_VERSION,
        "selected_source_sha256": sha256(source_path),
        "batch_files": batch_files,
        "exclusion_summary": exclusion,
        "limitations": ["The available unused real-report pool is OSHA SIR only; source diversity cannot be increased without external acquisition.", "Source-native severe-injury status is retained as metadata and is never used as the SIF target."],
    }
    json_write(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "rows": len(selected), "partitions": manifest["partition_counts"], "near_duplicates_excluded": len(near_excluded)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "validate-pass1", "make-second-pass", "make-systematic-lsr08-review", "recover-stalled-second-pass-batch-02", "validate-pass2", "make-adjudication", "assemble", "train", "evaluate", "evaluate-setfit-posthoc", "finalize"])
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    elif args.phase == "validate-pass1":
        frame = load_and_validate_pass(1)
        print(json.dumps({"status": "valid", "pass": 1, "rows": len(frame)}, indent=2))
    elif args.phase == "make-second-pass":
        make_second_pass()
    elif args.phase == "make-systematic-lsr08-review":
        make_systematic_lsr08_review()
    elif args.phase == "recover-stalled-second-pass-batch-02":
        recover_stalled_second_pass_batch_02()
    elif args.phase == "validate-pass2":
        frame = load_and_validate_pass(2)
        print(json.dumps({"status": "valid", "pass": 2, "rows": len(frame)}, indent=2))
    elif args.phase == "make-adjudication":
        make_adjudication()
    elif args.phase == "assemble":
        assemble()
    elif args.phase == "train":
        train_models()
    elif args.phase == "evaluate":
        evaluate_frozen()
    elif args.phase == "evaluate-setfit-posthoc":
        evaluate_setfit_posthoc()
    elif args.phase == "finalize":
        finalize()


if __name__ == "__main__":
    main()
