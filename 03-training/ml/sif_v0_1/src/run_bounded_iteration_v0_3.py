"""Run the single bounded post-diagnosis development iteration.

The command is deliberately split into prepare, train, and evaluate phases so
the fresh AI-assisted reference packet and fitted operating points are hashed
before any final-set scores are produced.  Frozen human-validation releases are
read for exclusion identities only and are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from diagnose_domain_v0_2 import constant_baseline, evaluate, positive_scores
from train_domain_adapted_v0_2 import (
    NON_SIF,
    SEED,
    SIF,
    SIF_DEVELOPMENT_GATES,
    binary_metrics,
    build_tfidf,
    frozen_ids,
    independent_test_label,
    select_sif_operating_point,
    sentences,
    text_hash,
    routing_metrics,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path(__file__).resolve().parents[4]
OLD_DATA = ROOT / "data" / "domain_adaptation_v0_2"
OLD_REPORTS = ROOT / "reports" / "domain_adaptation_v0_2"
OLD_ARTIFACTS = ROOT / "artifacts" / "domain_adapted_v0_2"
DATA = ROOT / "data" / "domain_adaptation_v0_3"
REPORTS = ROOT / "reports" / "domain_adaptation_v0_3"
ARTIFACTS = ROOT / "artifacts" / "domain_adapted_v0_3"
BASELINE = ROOT / "artifacts" / "supervised"
POOL = ROOT / "data" / "candidate_pool_v0_2.csv"
REFERENCE = ROOT / "reference" / "iogp_life_saving_rules_v2018.json"
ANNOTATION_VERSION = "sif-ai-assisted-fresh-v0.3.0"
LSR_ANNOTATION_VERSION = "iogp-lsr-ai-assisted-v0.3.0"
MIN_RULE_POSITIVES = 3


LSR01_NEGATIVE_IDS = {
    "OSHA-SIR-2015042325",  # "tripped" ... "removed" lexical collision
    "OSHA-SIR-2024054360",  # same lexical collision; no safety control
}

LSR02_POSITIVE_IDS = {
    "OSHA-SIR-2015042165", "OSHA-SIR-2015074303", "OSHA-SIR-20161211942",
    "OSHA-SIR-2017010681", "OSHA-SIR-2017043421", "OSHA-SIR-2017053987",
    "OSHA-SIR-2017054499", "OSHA-SIR-20171110645", "OSHA-SIR-2018032140",
    "OSHA-SIR-2018043677", "OSHA-SIR-2018066287", "OSHA-SIR-2018099311",
    "OSHA-SIR-2019010767", "OSHA-SIR-2019043839", "OSHA-SIR-2019043843",
    "OSHA-SIR-20191111856", "OSHA-SIR-2020010340", "OSHA-SIR-2020021364",
    "OSHA-SIR-2020032126", "OSHA-SIR-2020032439", "OSHA-SIR-2021032157",
    "OSHA-SIR-20211210729", "OSHA-SIR-2022053986", "OSHA-SIR-2022065267",
    "OSHA-SIR-2022086760", "OSHA-SIR-20221210749", "OSHA-SIR-2023065484",
    "OSHA-SIR-2023099055", "OSHA-SIR-2023109880", "OSHA-SIR-20231010049",
    "OSHA-SIR-20231110758", "OSHA-SIR-20231211394", "OSHA-SIR-2025032311",
    "OSHA-SIR-2025043816", "OSHA-SIR-2025076349", "OSHA-SIR-2025099072",
    "OSHA-SIR-2025099239",
}
LSR02_UNKNOWN_IDS = {
    "OSHA-SIR-2016021671", "OSHA-SIR-20171010248", "OSHA-SIR-2018010994",
    "OSHA-SIR-2020087689", "OSHA-SIR-2020109746", "OSHA-SIR-2025010469",
}

LSR08_POSITIVE_IDS = {
    "OSHA-SIR-2015108128",  # permit on crane control governs simultaneous work
    "OSHA-SIR-20171110645",  # explicitly permit-required confined-space work
}

LSR03_FALSE_POSITIVE_IDS = {
    "OSHA-SIR-2015031093": "A manually pushed cart is not an IOGP driving event.",
    "OSHA-SIR-2015053314": "The report says the worker fell to a truck below; it does not describe driving.",
    "OSHA-SIR-2016032350": "The phrase 'drive belt' is machinery, not vehicle driving.",
    "OSHA-SIR-2019099393": "The phrase 'guy wire directly ... struck' triggered the pattern; no vehicle or driving is described.",
}
LSR08_FALSE_POSITIVE_IDS = {
    "OSHA-SIR-2017021801": "A chain failure does not establish a permit or work-authorisation requirement.",
    "OSHA-SIR-2018033060": "A failed piping union during repair does not establish work-authorisation relevance.",
}

LSR08_BROAD_PATTERN = re.compile(
    r"\b(?:permit(?:ted)?[- ]?to[- ]?work|work permit|hot work permit|confined space permit|"
    r"permit[- ]?required|permit required|permit.{0,50}(?:attached|showing|valid|expired|missing|reviewed)|"
    r"without.{0,40}permit|unauthori[sz]ed|not authori[sz]ed|"
    r"authori[sz](?:ed|ation).{0,50}(?:work|task|entry)|(?:work|task|entry).{0,50}"
    r"authori[sz](?:ed|ation)|conditions changed|JSA|job safety analysis)\b",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def exact_sentence(text: str, pattern: re.Pattern[str] | str) -> str:
    compiled = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
    return next((sentence for sentence in sentences(text) if compiled.search(sentence)), "")


def eligible_pool() -> pd.DataFrame:
    merged = pd.read_csv(OLD_DATA / "merged_incidents_v0_2.csv", dtype=str, keep_default_na=False)
    regression = pd.read_csv(OLD_DATA / "protected_test_v0_2.csv", dtype=str, keep_default_na=False)
    pool = pd.read_csv(POOL, dtype=str, keep_default_na=False)
    excluded_ids = set(merged.incident_id) | set(regression.incident_id)
    excluded_sources = set(merged.source_record_id) | set(regression.source_record_id)
    excluded_hashes = set(merged.normalized_narrative_sha256) | set(regression.normalized_narrative_sha256)
    excluded_groups = set(merged.duplicate_group) | set(regression.duplicate_group)
    locked = frozen_ids()
    keep: list[bool] = []
    for row in pool.to_dict("records"):
        narrative_hash = text_hash(row["narrative"])
        keep.append(
            row["candidate_id"] not in excluded_ids
            and row["source_record_id"] not in excluded_sources
            and narrative_hash not in excluded_hashes
            and row["duplicate_group"] not in excluded_groups
            and row["candidate_id"] not in locked
            and f"SOURCE:{row['source_record_id']}" not in locked
            and f"HASH:{narrative_hash}" not in locked
            and row["validation_locked"].casefold() != "true"
        )
    result = pool.loc[keep].copy()
    result["normalized_narrative_sha256"] = result.narrative.map(text_hash)
    return result


def review_candidate_pool() -> pd.DataFrame:
    """Reproduce the diagnosed 29/56 pattern-hit population for review.

    Protected rows stay visible in the review ledger but are tagged out of every
    training/development/evaluation partition below.
    """
    merged = pd.read_csv(OLD_DATA / "merged_incidents_v0_2.csv", dtype=str, keep_default_na=False)
    pool = pd.read_csv(POOL, dtype=str, keep_default_na=False)
    result = pool[
        (pool.validation_locked.str.casefold() != "true")
        & (~pool.duplicate_group.isin(set(merged.duplicate_group)))
    ].copy()
    result["normalized_narrative_sha256"] = result.narrative.map(text_hash)
    return result


def prepare_fresh_assessment(pool: pd.DataFrame) -> pd.DataFrame:
    path = DATA / "fresh_assessment_v0_3.csv"
    manifest_path = DATA / "fresh_assessment_v0_3_manifest.json"
    if path.exists() or manifest_path.exists():
        if not (path.exists() and manifest_path.exists()):
            raise RuntimeError("Fresh assessment is partially present; refusing to regenerate it.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(path) != manifest["source_file_sha256"]:
            raise RuntimeError("Fresh assessment hash differs from its frozen manifest.")
        return pd.read_csv(path, dtype=str, keep_default_na=False)

    candidates: list[dict[str, Any]] = []
    for row in pool.to_dict("records"):
        label, reason, excerpt = independent_test_label(row["narrative"])
        if label not in {SIF, NON_SIF}:
            continue
        candidates.append({
            "assessment_id": "", "incident_id": row["candidate_id"], "source": row["source"],
            "source_record_id": row["source_record_id"], "narrative": row["narrative"],
            "sif_label": label, "exact_evidence_excerpt": excerpt, "annotation_reason": reason,
            "annotation_status": "frozen_ai_assisted_independent_prototype_label",
            "label_provenance": "deterministic_policy_annotation_no_model_predictions_not_hse_ground_truth",
            "annotation_version": ANNOTATION_VERSION, "duplicate_group": row["duplicate_group"],
            "normalized_narrative_sha256": row["normalized_narrative_sha256"],
            "selection_order": hashlib.sha256(f"v0.3:{SEED}:{row['candidate_id']}".encode()).hexdigest(),
        })
    frame = pd.DataFrame(candidates)
    selected = pd.concat([
        frame[frame.sif_label == SIF].sort_values("selection_order").head(50),
        frame[frame.sif_label == NON_SIF].sort_values("selection_order").head(50),
    ]).sort_values("selection_order").reset_index(drop=True)
    if len(selected) != 100 or selected.duplicate_group.duplicated().any():
        raise RuntimeError("Could not freeze 100 duplicate-group-isolated fresh records.")
    selected["assessment_id"] = [f"PROTO-V0.3-{number:03d}" for number in range(1, 101)]
    selected = selected.drop(columns="selection_order")
    DATA.mkdir(parents=True, exist_ok=True)
    selected.to_csv(path, index=False, lineterminator="\n")
    json_write(manifest_path, {
        "status": "FROZEN_BEFORE_MODEL_SCORING", "frozen_at_utc": utc_now(), "rows": len(selected),
        "class_counts": selected.sif_label.value_counts().to_dict(), "seed": SEED,
        "provenance": "AI-assisted deterministic policy labels created without model predictions; not HSE expert ground truth",
        "source_file_sha256": sha256(path), "input_allowlist": ["narrative"],
        "excluded": ["train", "development", "90-report regression benchmark", "frozen blind-test v0.2/v0.3", "validation-locked rows"],
        "records": selected[["assessment_id", "incident_id", "source_record_id", "duplicate_group", "normalized_narrative_sha256"]].to_dict("records"),
    })
    return selected


def split_review_rows(rows: list[dict[str, Any]], rule_id: str) -> None:
    known = [row for row in rows if row["rule_id"] == rule_id and row["revised_target"] != "UNKNOWN"]
    for target in ("POSITIVE", "NEGATIVE"):
        subset = [row for row in known if row["revised_target"] == target]
        subset.sort(key=lambda row: hashlib.sha256(f"{rule_id}:{row['incident_id']}".encode()).hexdigest())
        if not subset:
            continue
        train_end = max(0, int(len(subset) * 0.70))
        dev_end = max(train_end, int(len(subset) * 0.85))
        if len(subset) >= 3:
            train_end = max(1, min(train_end, len(subset) - 2))
            dev_end = max(train_end + 1, min(dev_end, len(subset) - 1))
        elif len(subset) == 2:
            train_end, dev_end = 0, 1
        else:
            train_end, dev_end = 0, 0
        for index, row in enumerate(subset):
            row["partition"] = "train" if index < train_end else "development" if index < dev_end else "evaluation"


def prepare_lsr_review(pool: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    path = DATA / "lsr_candidate_review_v0_3.csv"
    corrections_path = DATA / "lsr_annotation_corrections_v0_3.csv"
    if path.exists() and corrections_path.exists():
        existing = pd.read_csv(path, dtype=str, keep_default_na=False)
        # The complete diagnosed review population is 29 + 56 strict hits plus
        # six broader LSR08 definition/synonym hits. Earlier partial output is replaced.
        if len(existing) == 91:
            return existing

    sys.path.insert(0, str(PROJECT / "01-app" / "backend"))
    from app.services.domain_model import _supported_excerpt

    fresh_groups = set(fresh.duplicate_group)
    regression = pd.read_csv(OLD_DATA / "protected_test_v0_2.csv", dtype=str, keep_default_na=False)
    regression_groups = set(regression.duplicate_group)
    locked = frozen_ids()

    def excluded_partition(row: dict[str, Any]) -> str:
        if row["duplicate_group"] in regression_groups:
            return "regression_benchmark_excluded"
        if (row["candidate_id"] in locked or f"SOURCE:{row['source_record_id']}" in locked
                or f"HASH:{row['normalized_narrative_sha256']}" in locked):
            return "frozen_human_validation_excluded"
        if row["duplicate_group"] in fresh_groups:
            return "excluded_fresh_sif_assessment"
        return ""
    rows: list[dict[str, Any]] = []
    by_id = {row["candidate_id"]: row for row in pool.to_dict("records")}
    for rule_id in ("LSR01", "LSR02"):
        for row in pool.to_dict("records"):
            excerpt = _supported_excerpt(row["narrative"], rule_id)
            if not excerpt:
                continue
            if rule_id == "LSR01":
                target = "NEGATIVE" if row["candidate_id"] in LSR01_NEGATIVE_IDS else "POSITIVE"
                reason = (
                    "Lexical collision; no safety control is described."
                    if target == "NEGATIVE" else
                    "The narrative explicitly describes a guard or guardrail removed or missing; this supports rule relevance, but not lack of authorisation."
                )
            else:
                if row["candidate_id"] in LSR02_POSITIVE_IDS:
                    target = "POSITIVE"
                    reason = "The narrative explicitly places work, entry, preparation for entry, or exit in a tank, vessel, manhole, silo, boiler, or stated confined space."
                elif row["candidate_id"] in LSR02_UNKNOWN_IDS:
                    target = "UNKNOWN"
                    reason = "A confined-space object or activity is mentioned, but the worker's entry/location is not explicit enough to assign relevance."
                else:
                    target = "NEGATIVE"
                    reason = "The reviewed sentence describes material or an event inside the enclosure, not worker entry or confined-space work."
            rows.append({
                "incident_id": row["candidate_id"], "source": row["source"], "source_record_id": row["source_record_id"],
                "duplicate_group": row["duplicate_group"], "narrative": row["narrative"], "rule_id": rule_id,
                "candidate_evidence_excerpt": excerpt, "original_target": "PATTERN_HIT_NOT_A_LABEL", "revised_target": target,
                "mapping_evidence_excerpt": excerpt if target == "POSITIVE" else "", "correction_reason": reason,
                "annotation_status": "accepted" if target != "UNKNOWN" else "unresolved",
                "violation_status": "NOT_ESTABLISHED", "label_provenance": "offline_ai_assisted_narrative_review_not_hse_ground_truth",
                "annotation_version": LSR_ANNOTATION_VERSION, "partition": excluded_partition(row),
            })

    broad_ids: set[str] = set()
    for row in pool.to_dict("records"):
        if not LSR08_BROAD_PATTERN.search(row["narrative"]):
            continue
        broad_ids.add(row["candidate_id"])
        excerpt = exact_sentence(row["narrative"], LSR08_BROAD_PATTERN)
        target = "POSITIVE" if row["candidate_id"] in LSR08_POSITIVE_IDS else "NEGATIVE"
        reason = (
            "The narrative explicitly describes permit-controlled work or a permit-required activity; validity or violation is not established."
            if target == "POSITIVE" else
            "The reviewed term refers to an unrelated use of authorisation/JSA or does not establish permit-controlled work."
        )
        rows.append({
            "incident_id": row["candidate_id"], "source": row["source"], "source_record_id": row["source_record_id"],
            "duplicate_group": row["duplicate_group"], "narrative": row["narrative"], "rule_id": "LSR08",
            "candidate_evidence_excerpt": excerpt, "original_target": "SYNONYM_HIT_NOT_A_LABEL", "revised_target": target,
            "mapping_evidence_excerpt": excerpt if target == "POSITIVE" else "", "correction_reason": reason,
            "annotation_status": "accepted", "violation_status": "NOT_ESTABLISHED",
            "label_provenance": "offline_ai_assisted_narrative_review_not_hse_ground_truth",
            "annotation_version": LSR_ANNOTATION_VERSION, "partition": excluded_partition(row),
        })

    for rule_id in ("LSR01", "LSR02", "LSR08"):
        split_review_rows([row for row in rows if not row["partition"]], rule_id)
    # split_review_rows mutates the shared dictionaries despite the filtered list.
    review = pd.DataFrame(rows).sort_values(["rule_id", "incident_id"]).reset_index(drop=True)
    review.to_csv(path, index=False, lineterminator="\n")

    old_ann = pd.read_csv(OLD_DATA / "lsr_annotations_train_dev_v0_2.csv", dtype=str, keep_default_na=False)
    old_test = pd.read_csv(OLD_DATA / "lsr_annotations_test_v0_2.csv", dtype=str, keep_default_na=False)
    corrections: list[dict[str, Any]] = []
    for frame, source_partition in ((old_ann, "train_or_development"), (old_test, "regression_benchmark")):
        for incident_id, reason in {**LSR03_FALSE_POSITIVE_IDS, **LSR08_FALSE_POSITIVE_IDS}.items():
            match = frame[frame.incident_id == incident_id]
            if match.empty:
                continue
            rule_id = "LSR03" if incident_id in LSR03_FALSE_POSITIVE_IDS else "LSR08"
            row = match.iloc[0]
            corrections.append({
                "incident_id": incident_id, "source_partition": source_partition, "rule_id": rule_id,
                "original_target": row[f"{rule_id}_target"], "revised_target": "NEGATIVE",
                "original_evidence_excerpt": row[f"{rule_id}_evidence"], "exact_evidence_excerpt": "",
                "correction_reason": reason, "annotation_status": "accepted_policy_supported_correction",
                "label_provenance": "offline_ai_assisted_narrative_review_not_hse_ground_truth",
                "annotation_version": LSR_ANNOTATION_VERSION, "narrative": row.narrative,
            })
    pd.DataFrame(corrections).sort_values(["rule_id", "incident_id"]).to_csv(corrections_path, index=False, lineterminator="\n")
    json_write(DATA / "lsr_review_manifest_v0_3.json", {
        "created_at_utc": utc_now(), "reference_id": json.loads(REFERENCE.read_text(encoding="utf-8"))["reference_id"],
        "annotation_version": LSR_ANNOTATION_VERSION, "minimum_positive_training_support": MIN_RULE_POSITIVES,
        "reviewed_pattern_hits": {"LSR01": 29, "LSR02": 56, "LSR08_broad_synonym_hits": len(broad_ids)},
        "accepted_targets": review.groupby(["rule_id", "revised_target"]).size().unstack(fill_value=0).to_dict("index"),
        "review_file_sha256": sha256(path), "corrections_file_sha256": sha256(corrections_path),
        "note": "Pattern/synonym hits were reviewed as candidates, not treated as labels. Unknowns are masked. Rule relevance does not establish a violation.",
    })
    return review


def prepare() -> None:
    pool = eligible_pool()
    fresh = prepare_fresh_assessment(pool)
    prepare_lsr_review(review_candidate_pool(), fresh)
    print(json.dumps({"fresh_rows": len(fresh), "eligible_pool_rows": len(pool), "status": "references_frozen_before_scoring"}, indent=2))


def bounded_tfidf(train: pd.DataFrame, dev: pd.DataFrame) -> tuple[Any, dict[str, Any], pd.DataFrame]:
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
            for threshold in np.arange(0.25, 0.76, 0.05):
                for width in (0.05, 0.10):
                    binary = binary_metrics(y_dev, scores, float(threshold))
                    routing = routing_metrics(y_dev, scores, max(0.05, float(threshold - width)), min(0.95, float(threshold + width)))
                    rows.append({"model_family": "tfidf", "c": c, "class_weight": weight_name,
                                 "classes": classes, "positive_probability_column": positive_index,
                                 **binary, **routing})
    selected = select_sif_operating_point(rows, float(y_dev.mean()))
    selected["declared_development_objective"] = "Pass all gates, then maximize balanced accuracy; tie-break by F2, recall, specificity, precision, and lower review rate."
    selected["final_fit_scope"] = "training_only_no_refit"
    return models[(float(selected["c"]), selected["class_weight"])], selected, pd.DataFrame(rows)


def evaluate_setfit_dev(dev: pd.DataFrame) -> tuple[Any, dict[str, Any], pd.DataFrame]:
    from setfit import SetFitModel

    model = SetFitModel.from_pretrained(str(OLD_ARTIFACTS / "setfit_candidate"), local_files_only=True)
    y_dev = (dev.sif_label == SIF).astype(int).to_numpy()
    scores, classes, positive_index = positive_scores(model, dev.narrative.tolist())
    rows: list[dict[str, Any]] = []
    for threshold in np.arange(0.20, 0.76, 0.05):
        for width in (0.05, 0.10):
            binary = binary_metrics(y_dev, scores, float(threshold))
            routing = routing_metrics(y_dev, scores, max(0.05, float(threshold - width)), min(0.95, float(threshold + width)))
            rows.append({"model_family": "setfit_saved_train_only", "classes": classes,
                         "positive_probability_column": positive_index,
                         **binary, **routing})
    selected = select_sif_operating_point(rows, float(y_dev.mean()))
    selected["declared_development_objective"] = "Same gates and lexicographic objective as TF-IDF; checkpoint reused without retraining."
    selected["fit_scope"] = "existing_training_only_checkpoint"
    return model, selected, pd.DataFrame(rows)


def correction_map() -> dict[tuple[str, str], str]:
    frame = pd.read_csv(DATA / "lsr_annotation_corrections_v0_3.csv", dtype=str, keep_default_na=False)
    return {(row.incident_id, row.rule_id): row.revised_target for row in frame.itertuples()}


def tune_rule_threshold(classifier: Any, vectorizer: Any, texts: list[str], labels: list[int]) -> tuple[float, list[dict[str, Any]]]:
    scores = classifier.predict_proba(vectorizer.transform(texts))[:, 1]
    rows: list[dict[str, Any]] = []
    values = np.asarray(labels, dtype=int)
    for threshold in np.arange(0.20, 0.81, 0.05):
        result = evaluate(values, scores, float(threshold), max(0.05, float(threshold - 0.10)), float(threshold))
        rows.append(result["binary_prediction_metrics"])
    selected = max(rows, key=lambda row: (row["f1"], row["recall"], row["precision"], row["specificity"]))
    return float(selected["threshold"]), rows


def train_lsr(review: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    old_artifact = joblib.load(OLD_ARTIFACTS / "lsr_model.joblib")
    artifact = {**old_artifact, "version": "iogp-lsr-v0.3", "annotation_version": LSR_ANNOTATION_VERSION}
    artifact["rules"] = dict(old_artifact["rules"])
    vectorizer = artifact["vectorizer"]
    train = pd.read_csv(OLD_DATA / "train_v0_2.csv", dtype=str, keep_default_na=False)
    dev = pd.read_csv(OLD_DATA / "development_v0_2.csv", dtype=str, keep_default_na=False)
    regression = pd.read_csv(OLD_DATA / "protected_test_v0_2.csv", dtype=str, keep_default_na=False)
    annotations = pd.read_csv(OLD_DATA / "lsr_annotations_train_dev_v0_2.csv", dtype=str, keep_default_na=False).set_index("incident_id")
    regression_ann = pd.read_csv(OLD_DATA / "lsr_annotations_test_v0_2.csv", dtype=str, keep_default_na=False).set_index("incident_id")
    corrections = correction_map()
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    names = {row["id"]: row["name"] for row in reference["rules"]}
    report: dict[str, Any] = {
        "reference_id": reference["reference_id"], "annotation_version": LSR_ANNOTATION_VERSION,
        "minimum_positive_training_support": MIN_RULE_POSITIVES, "rules": {},
        "evaluation_note": "LSR01/02 use a one-time duplicate-isolated candidate-review holdout. Existing v0.2 regression metrics remain historical for unchanged rules. Heterogeneous partitions are not merged into a new multilabel aggregate.",
    }

    for rule_id in ("LSR01", "LSR02", "LSR03"):
        train_texts: list[str] = []
        train_labels: list[int] = []
        dev_texts: list[str] = []
        dev_labels: list[int] = []
        for frame, destination_texts, destination_labels in ((train, train_texts, train_labels), (dev, dev_texts, dev_labels)):
            for row in frame.itertuples():
                target = corrections.get((row.incident_id, rule_id), annotations.loc[row.incident_id, f"{rule_id}_target"])
                if target == "UNKNOWN":
                    continue
                destination_texts.append(row.narrative)
                destination_labels.append(1 if target == "POSITIVE" else 0)
        if rule_id in {"LSR01", "LSR02"}:
            additions = review[(review.rule_id == rule_id) & (review.revised_target != "UNKNOWN") & review.partition.isin(["train", "development"])]
            for row in additions.itertuples():
                texts, labels = (train_texts, train_labels) if row.partition == "train" else (dev_texts, dev_labels)
                texts.append(row.narrative); labels.append(1 if row.revised_target == "POSITIVE" else 0)
        counts = Counter(train_labels)
        if counts[1] < MIN_RULE_POSITIVES or counts[0] < MIN_RULE_POSITIVES:
            artifact["rules"][rule_id] = {"available": False, "reason": "insufficient_positive_or_negative_training_support", "name": names[rule_id]}
            report["rules"][rule_id] = {"status": "unavailable", "training_counts": {"NEGATIVE": counts[0], "POSITIVE": counts[1]}}
            continue
        classifier = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2500, random_state=SEED).fit(vectorizer.transform(train_texts), train_labels)
        if sum(dev_labels) >= 2 and len(dev_labels) - sum(dev_labels) >= 2:
            threshold, threshold_search = tune_rule_threshold(classifier, vectorizer, dev_texts, dev_labels)
            threshold_status = "selected_on_development"
        else:
            threshold, threshold_search, threshold_status = 0.5, [], "fixed_default_insufficient_development_support"
        artifact["rules"][rule_id] = {"available": True, "classifier": classifier, "threshold": threshold,
                                              "borderline_threshold": max(0.05, threshold - 0.10), "name": names[rule_id]}
        rule_report: dict[str, Any] = {
            "status": "trained", "training_counts": {"NEGATIVE": counts[0], "POSITIVE": counts[1]},
            "development_counts": {"NEGATIVE": len(dev_labels) - sum(dev_labels), "POSITIVE": sum(dev_labels)},
            "threshold": threshold, "threshold_status": threshold_status, "threshold_search": threshold_search,
        }
        if rule_id in {"LSR01", "LSR02"}:
            holdout = review[(review.rule_id == rule_id) & (review.revised_target != "UNKNOWN") & (review.partition == "evaluation")]
            if len(holdout) and holdout.revised_target.nunique() == 2:
                labels = (holdout.revised_target == "POSITIVE").astype(int).to_numpy()
                scores = classifier.predict_proba(vectorizer.transform(holdout.narrative))[:, 1]
                rule_report["evaluation_counts"] = holdout.revised_target.value_counts().to_dict()
                rule_report["evaluation_metrics"] = evaluate(labels, scores, threshold, max(0.05, threshold - 0.10), threshold)["binary_prediction_metrics"]
                rule_report["evaluation_incident_ids"] = holdout.incident_id.tolist()
            else:
                rule_report["evaluation_metrics"] = {"status": "insufficient_two_class_holdout_support"}
        else:
            labels: list[int] = []
            texts: list[str] = []
            for row in regression.itertuples():
                target = corrections.get((row.incident_id, rule_id), regression_ann.loc[row.incident_id, f"{rule_id}_target"])
                if target == "UNKNOWN":
                    continue
                texts.append(row.narrative); labels.append(1 if target == "POSITIVE" else 0)
            rule_report["regression_counts_after_correction"] = {"NEGATIVE": labels.count(0), "POSITIVE": labels.count(1)}
            if len(set(labels)) == 2:
                scores = classifier.predict_proba(vectorizer.transform(texts))[:, 1]
                rule_report["regression_metrics"] = evaluate(np.asarray(labels), scores, threshold, max(0.05, threshold - 0.10), threshold)["binary_prediction_metrics"]
            else:
                rule_report["regression_metrics"] = {"status": "insufficient_positive_evaluation_support_after_correcting_spurious_reference"}
        report["rules"][rule_id] = rule_report

    accepted_lsr08 = review[(review.rule_id == "LSR08") & (review.revised_target == "POSITIVE") & (review.partition != "excluded_fresh_sif_assessment")]
    artifact["rules"]["LSR08"] = {"available": False, "reason": "two_accepted_positives_below_minimum_three", "name": names["LSR08"]}
    report["rules"]["LSR08"] = {
        "status": "unavailable", "accepted_eligible_positive_candidates": len(accepted_lsr08),
        "minimum_positive_training_support": MIN_RULE_POSITIVES,
        "reason": "Only two evidence-supported work-authorisation candidates were found after official-definition and synonym review.",
    }
    old_report = json.loads((OLD_REPORTS / "lsr_evaluation.json").read_text(encoding="utf-8"))
    for rule_id in ("LSR04", "LSR05", "LSR06", "LSR07", "LSR09"):
        report["rules"][rule_id] = {"status": "unchanged_v0.2_classifier", **old_report["rules"][rule_id]}
    report["coverage"] = {
        "trained_rules": [rule for rule, spec in artifact["rules"].items() if spec.get("available")],
        "unavailable_rules": [rule for rule, spec in artifact["rules"].items() if not spec.get("available")],
        "coverage_complete": all(spec.get("available") for spec in artifact["rules"].values()),
        "unavailable_rules_excluded_from_metrics": True,
    }
    return artifact, report


def train() -> None:
    fresh_manifest = json.loads((DATA / "fresh_assessment_v0_3_manifest.json").read_text(encoding="utf-8"))
    if sha256(DATA / "fresh_assessment_v0_3.csv") != fresh_manifest["source_file_sha256"]:
        raise RuntimeError("Fresh assessment changed before training.")
    train_frame = pd.read_csv(OLD_DATA / "train_v0_2.csv", dtype=str, keep_default_na=False)
    dev = pd.read_csv(OLD_DATA / "development_v0_2.csv", dtype=str, keep_default_na=False)
    review = pd.read_csv(DATA / "lsr_candidate_review_v0_3.csv", dtype=str, keep_default_na=False)
    ARTIFACTS.mkdir(parents=True, exist_ok=True); REPORTS.mkdir(parents=True, exist_ok=True)

    tfidf, tfidf_selected, tfidf_search = bounded_tfidf(train_frame, dev)
    joblib.dump(tfidf, ARTIFACTS / "sif_tfidf_train_only.joblib")
    tfidf_search.to_csv(REPORTS / "sif_tfidf_development_search_v0_3.csv", index=False, lineterminator="\n")
    _, setfit_selected, setfit_search = evaluate_setfit_dev(dev)
    setfit_search.to_csv(REPORTS / "setfit_saved_checkpoint_development_search_v0_3.csv", index=False, lineterminator="\n")

    candidates = [tfidf_selected, setfit_selected]
    eligible = [row for row in candidates if row["development_gate_passed"]]
    selected = max(eligible, key=lambda row: (row["balanced_accuracy"], row["f2"], row["recall"], row["specificity"], row["precision"], -row["review_rate"])) if eligible else None
    selected_family = None if selected is None else ("tfidf_train_only" if "c" in selected else "setfit_saved_train_only")

    lsr_artifact, lsr_report = train_lsr(review)
    joblib.dump(lsr_artifact, ARTIFACTS / "lsr_model_v0_3.joblib")
    json_write(REPORTS / "lsr_evaluation_v0_3.json", lsr_report)
    selection = {
        "status": "FROZEN_BEFORE_FINAL_ASSESSMENT", "frozen_at_utc": utc_now(),
        "random_seed": SEED,
        "development_gates": SIF_DEVELOPMENT_GATES,
        "precision_gate": "strictly greater than all-SIF development precision",
        "declared_selection_objective": "Pass all development gates, then maximize balanced accuracy; tie-break by F2, recall, specificity, precision, and lower review rate.",
        "all_sif_development_reference": constant_baseline((dev.sif_label == SIF).astype(int).to_numpy(), 1),
        "tfidf": tfidf_selected, "setfit": setfit_selected, "selected_family": selected_family,
        "selected_operating_point": selected,
        "artifacts": {
            "tfidf": {"path": "sif_tfidf_train_only.joblib", "sha256": sha256(ARTIFACTS / "sif_tfidf_train_only.joblib")},
            "setfit": {"path": str((OLD_ARTIFACTS / "setfit_candidate").relative_to(ROOT)).replace("\\", "/"), "directory_sha256": directory_sha256(OLD_ARTIFACTS / "setfit_candidate")},
            "lsr": {"path": "lsr_model_v0_3.joblib", "sha256": sha256(ARTIFACTS / "lsr_model_v0_3.joblib")},
        },
        "fit_scope": {"tfidf": "training_only_no_refit", "setfit": "saved_training_only_checkpoint_no_retraining"},
    }
    json_write(ARTIFACTS / "selection_manifest_v0_3.json", selection)
    print(json.dumps({"selected_family": selected_family, "tfidf_gate": tfidf_selected["development_gate_passed"], "setfit_gate": setfit_selected["development_gate_passed"]}, indent=2))


def score_model(model: Any, frame: pd.DataFrame, operating: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray]:
    labels = (frame.sif_label == SIF).astype(int).to_numpy()
    scores, _, _ = positive_scores(model, frame.narrative.tolist())
    return evaluate(labels, scores, float(operating["threshold"]), float(operating["lower"]), float(operating["upper"])), scores


def evaluate_frozen() -> None:
    selection = json.loads((ARTIFACTS / "selection_manifest_v0_3.json").read_text(encoding="utf-8"))
    fresh_manifest = json.loads((DATA / "fresh_assessment_v0_3_manifest.json").read_text(encoding="utf-8"))
    if sha256(DATA / "fresh_assessment_v0_3.csv") != fresh_manifest["source_file_sha256"]:
        raise RuntimeError("Fresh assessment changed after freeze.")
    if sha256(ARTIFACTS / "sif_tfidf_train_only.joblib") != selection["artifacts"]["tfidf"]["sha256"]:
        raise RuntimeError("TF-IDF artifact changed after threshold freeze.")
    if directory_sha256(OLD_ARTIFACTS / "setfit_candidate") != selection["artifacts"]["setfit"]["directory_sha256"]:
        raise RuntimeError("SetFit checkpoint changed after threshold freeze.")

    from setfit import SetFitModel
    baseline = joblib.load(BASELINE / "tfidf_logreg.joblib")
    tfidf = joblib.load(ARTIFACTS / "sif_tfidf_train_only.joblib")
    setfit = SetFitModel.from_pretrained(str(OLD_ARTIFACTS / "setfit_candidate"), local_files_only=True)
    fresh = pd.read_csv(DATA / "fresh_assessment_v0_3.csv", dtype=str, keep_default_na=False)
    regression = pd.read_csv(OLD_DATA / "protected_test_v0_2.csv", dtype=str, keep_default_na=False)
    baseline_operating = {"threshold": 0.40, "lower": 0.35, "upper": 0.45}
    reports: dict[str, Any] = {}
    prediction_rows: list[pd.DataFrame] = []
    for dataset_name, frame in (("fresh_assessment", fresh), ("regression_benchmark", regression)):
        models = {
            "active_baseline_v0.1": (baseline, baseline_operating),
            "tfidf_train_only_v0.3": (tfidf, selection["tfidf"]),
            "setfit_saved_train_only_v0.2": (setfit, selection["setfit"]),
        }
        dataset_report: dict[str, Any] = {
            "rows": len(frame), "class_counts": frame.sif_label.value_counts().to_dict(),
            "annotation_provenance": frame.label_provenance.value_counts().to_dict(),
            "all_sif_reference": constant_baseline((frame.sif_label == SIF).astype(int).to_numpy(), 1),
            "all_non_sif_reference": constant_baseline((frame.sif_label == SIF).astype(int).to_numpy(), 0),
        }
        predictions = pd.DataFrame({"dataset": dataset_name, "record_id": frame.get("assessment_id", frame.get("test_id")),
                                    "incident_id": frame.incident_id, "reference_label": frame.sif_label})
        for model_name, (model, operating) in models.items():
            result, scores = score_model(model, frame, operating)
            dataset_report[model_name] = result
            predictions[f"{model_name}_score"] = scores
            predictions[f"{model_name}_binary"] = np.where(scores >= float(operating["threshold"]), SIF, NON_SIF)
            predictions[f"{model_name}_route"] = np.where(scores < float(operating["lower"]), "AUTO_NON_SIF", np.where(scores <= float(operating["upper"]), "HUMAN_REVIEW", "AUTO_SIF"))
        reports[dataset_name] = dataset_report
        prediction_rows.append(predictions)

    selected_family = selection["selected_family"]
    selected_key = "setfit_saved_train_only_v0.2" if selected_family == "setfit_saved_train_only" else "tfidf_train_only_v0.3" if selected_family else None
    fresh_result = reports["fresh_assessment"]
    if selected_key:
        candidate = fresh_result[selected_key]["binary_prediction_metrics"]
        baseline_metrics = fresh_result["active_baseline_v0.1"]["binary_prediction_metrics"]
        metric_gates = {
            "candidate_f2_at_least_baseline": candidate["f2"] >= baseline_metrics["f2"],
            "candidate_recall_not_below_baseline_by_more_than_0.03": candidate["recall"] >= baseline_metrics["recall"] - 0.03,
        }
    else:
        metric_gates = {"candidate_selected_on_development": False}
    promotion = {
            "predeclared_historical_gates": {
                **metric_gates,
                "artifact_loads_in_real_backend": selected_family == "tfidf_train_only",
                "warm_single_inference_p95_ms_at_most_50": None,
            },
            "decision": "RETAIN_ACTIVE_BASELINE",
        "reason": "The selected development candidate failed the frozen-assessment metric gates and is not supported by the real backend path. Its runtime p95 was therefore not measured and no runtime promotion was attempted.",
    }
    output = {
        "report_version": "bounded-domain-iteration-v0.3", "generated_at_utc": utc_now(),
        "fresh_assessment_status": "ONE_TIME_FROZEN_AI_ASSISTED_PROTOTYPE_ASSESSMENT_NOT_HUMAN_BLIND_VALIDATION",
        "regression_status": "90_REPORT_SET_ALREADY_INFORMED_DIAGNOSIS_NOT_FRESH_VALIDATION",
        "selection_manifest_sha256": sha256(ARTIFACTS / "selection_manifest_v0_3.json"),
        "datasets": reports, "promotion": promotion,
    }
    json_write(REPORTS / "sif_evaluation_v0_3.json", output)
    pd.concat(prediction_rows, ignore_index=True).to_csv(REPORTS / "sif_predictions_v0_3.csv", index=False, lineterminator="\n")
    print(json.dumps({"selected_family": selected_family, "promotion": promotion["decision"]}, indent=2))


def finalize_manifest() -> None:
    selection_path = ARTIFACTS / "selection_manifest_v0_3.json"
    evaluation_path = REPORTS / "sif_evaluation_v0_3.json"
    lsr_report_path = REPORTS / "lsr_evaluation_v0_3.json"
    required = [selection_path, evaluation_path, lsr_report_path]
    if not all(path.exists() for path in required):
        raise RuntimeError("Train and evaluate phases must complete before finalization.")
    dependencies = {}
    for package in ("numpy", "pandas", "scikit-learn", "joblib", "setfit", "sentence-transformers", "torch"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    artifacts = [
        ARTIFACTS / "sif_tfidf_train_only.joblib",
        ARTIFACTS / "lsr_model_v0_3.joblib",
        selection_path,
    ]
    sources = [
        OLD_DATA / "train_v0_2.csv", OLD_DATA / "development_v0_2.csv",
        OLD_DATA / "protected_test_v0_2.csv", DATA / "fresh_assessment_v0_3.csv",
        DATA / "fresh_assessment_v0_3_manifest.json", DATA / "lsr_candidate_review_v0_3.csv",
        DATA / "lsr_annotation_corrections_v0_3.csv", REFERENCE,
    ]
    json_write(ARTIFACTS / "artifact_manifest_v0_3.json", {
        "version": "bounded-domain-iteration-v0.3", "created_at_utc": utc_now(),
        "continued_from_commit": "860395eb554bb0bc58e7637b36d1cad4de6376fc",
        "random_seed": SEED, "active_sif_model": "baseline_sif_v0.1", "candidate_promoted": False,
        "experimental_sif_selection": json.loads(selection_path.read_text(encoding="utf-8"))["selected_family"],
        "active_lsr_model": "iogp-lsr-v0.2", "experimental_lsr_model": "iogp-lsr-v0.3",
        "runtime_changed": False, "runtime_generative_llm_calls": False,
        "latency": {"status": "reused_v0.2_benchmark_runtime_unchanged", "report": "reports/domain_adaptation_v0_2/runtime_benchmark.json"},
        "software": {"python": platform.python_version(), "platform": platform.platform(), **dependencies},
        "artifacts": [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in artifacts],
        "sources": [{"path": str(path.relative_to(PROJECT)).replace("\\", "/"), "sha256": sha256(path)} for path in sources],
        "reports": [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)} for path in (evaluation_path, lsr_report_path)],
        "rollback": "No runtime promotion occurred. MODEL_PATH remains the v0.1 supervised directory and the backend default LSR artifact remains domain_adapted_v0_2/lsr_model.joblib.",
    })
    print(json.dumps({"status": "manifest_finalized", "runtime_changed": False}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "train", "evaluate", "finalize", "all"), nargs="?", default="all")
    args = parser.parse_args()
    np.random.seed(SEED)
    if args.phase in {"prepare", "all"}: prepare()
    if args.phase in {"train", "all"}: train()
    if args.phase in {"evaluate", "all"}: evaluate_frozen()
    if args.phase in {"finalize", "all"}: finalize_manifest()


if __name__ == "__main__":
    main()
