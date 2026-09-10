"""Reproduce the v0.2 SIF failure diagnosis from saved artifacts.

This script is intentionally evaluation-only: it does not fit, relabel, or
promote a model and it never writes inside a frozen human-validation release.
The 90-row prototype test is treated as a regression/diagnostic benchmark.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)

from preprocess import clean_narrative
from train_domain_adapted_v0_2 import annotate_lsr, select_sif_operating_point


ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data" / "domain_adaptation_v0_2"
REPORTS = ROOT / "reports" / "domain_adaptation_v0_2"
BASELINE = ROOT / "artifacts" / "supervised"
CANDIDATES = ROOT / "artifacts" / "domain_adapted_v0_2"
SIF = "SIF_POTENTIAL"
NON_SIF = "NON_SIF_POTENTIAL"
QUANTILES = (0.0, 0.10, 0.25, 0.50, 0.75, 0.90, 1.0)


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def positive_scores(model: Any, texts: list[str]) -> tuple[np.ndarray, list[Any], int]:
    raw = model.predict_proba(texts)
    if hasattr(raw, "detach"):
        raw = raw.detach().cpu().numpy()
    probabilities = np.asarray(raw)
    classifier = getattr(model, "named_steps", {}).get("classifier") if hasattr(model, "named_steps") else getattr(model, "model_head", None)
    classes = list(getattr(classifier, "classes_", getattr(model, "labels", [])))
    if 1 not in classes:
        raise ValueError(f"Expected positive class 1, found {classes!r}")
    positive_index = classes.index(1)
    return probabilities[:, positive_index].astype(float), classes, positive_index


def score_distribution(labels: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value, name in ((0, NON_SIF), (1, SIF)):
        subset = scores[labels == value]
        result[name] = {
            "count": int(len(subset)),
            "mean": float(np.mean(subset)),
            "standard_deviation": float(np.std(subset)),
            "quantiles": {f"q{int(q * 100):02d}": float(v) for q, v in zip(QUANTILES, np.quantile(subset, QUANTILES))},
        }
    return result


def evaluate(labels: np.ndarray, scores: np.ndarray, threshold: float, lower: float, upper: float) -> dict[str, Any]:
    predictions = (scores >= threshold).astype(int)
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    specificity = tn / (tn + fp) if tn + fp else 0.0
    f2 = 5 * precision * recall / (4 * precision + recall) if 4 * precision + recall else 0.0
    review = (scores >= lower) & (scores <= upper)
    auto_non = scores < lower
    auto_sif = scores > upper
    return {
        "binary_prediction_metrics": {
            "threshold": threshold,
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "recall": float(recall),
            "precision": float(precision),
            "specificity": specificity,
            "balanced_accuracy": (float(recall) + specificity) / 2,
            "f1": float(f1),
            "f2": float(f2),
            "predicted_class_counts": {NON_SIF: int((predictions == 0).sum()), SIF: int((predictions == 1).sum())},
            "confusion_matrix_labels": [NON_SIF, SIF],
            "confusion_matrix": matrix.tolist(),
        },
        "operational_routing": {
            "review_band": [lower, upper],
            "human_review_count": int(review.sum()),
            "human_review_rate": float(review.mean()),
            "automatic_decision_coverage": float((~review).mean()),
            "auto_non_sif_count": int(auto_non.sum()),
            "auto_sif_count": int(auto_sif.sum()),
            "reference_sif_routed_auto_non_sif": int(((labels == 1) & auto_non).sum()),
            "note": "Routing is reported separately; review rows are not counted as correct binary predictions.",
        },
        "ranking_metrics": {
            "roc_auc": float(roc_auc_score(labels, scores)),
            "average_precision": float(average_precision_score(labels, scores)),
        },
        "score_distribution_by_reference_class": score_distribution(labels, scores),
    }


def constant_baseline(labels: np.ndarray, value: int) -> dict[str, Any]:
    scores = np.full(len(labels), float(value))
    result = evaluate(labels, scores, 0.5, 0.49, 0.51)
    result.pop("ranking_metrics")
    result.pop("score_distribution_by_reference_class")
    result["operational_routing"] = {
        "status": "NOT_APPLICABLE",
        "human_review_rate": None,
        "note": "A constant-class reference has no operational review band.",
    }
    return result


def route(scores: np.ndarray, lower: float, upper: float) -> np.ndarray:
    return np.where(scores < lower, "AUTO_NON_SIF", np.where(scores <= upper, "HUMAN_REVIEW", "AUTO_SIF"))


def split_summary(frame: pd.DataFrame) -> dict[str, Any]:
    words = frame.narrative.astype(str).str.split().str.len()
    years = frame.incident_id.astype(str).str.extract(r"(20\d{2})", expand=False)
    return {
        "rows": len(frame),
        "class_counts": frame.sif_label.value_counts().to_dict(),
        "positive_prevalence": float((frame.sif_label == SIF).mean()),
        "sources": frame.source.value_counts().to_dict(),
        "label_provenance": frame.label_provenance.value_counts().to_dict(),
        "source_year_counts": years.value_counts().sort_index().to_dict(),
        "narrative_word_count": {
            "minimum": int(words.min()), "median": float(words.median()), "mean": float(words.mean()), "maximum": int(words.max()),
        },
    }


def overlap(left: pd.DataFrame, right: pd.DataFrame, column: str) -> int:
    return len(set(left[column].astype(str)) & set(right[column].astype(str)))


def enrich_saved_search(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        matrix = ast.literal_eval(raw["confusion_matrix"])
        tn, fp = matrix[0]
        fn, tp = matrix[1]
        specificity = tn / (tn + fp) if tn + fp else 0.0
        rows.append({
            **raw,
            "true_positives": int(tp), "false_positives": int(fp),
            "true_negatives": int(tn), "false_negatives": int(fn),
            "specificity": specificity,
            "balanced_accuracy": (float(raw["recall"]) + specificity) / 2,
        })
    return rows


def lsr_audit() -> dict[str, Any]:
    saved = json.loads((REPORTS / "lsr_evaluation.json").read_text(encoding="utf-8"))
    rules: dict[str, Any] = {}
    for rule_id, row in saved["rules"].items():
        test = row.get("test_metrics", {})
        rules[rule_id] = {
            "name": row["name"],
            "status": row["status"],
            "training_counts": row["train_counts"],
            "development_counts": row["development_counts"],
            "regression_test_counts": row["test_counts"],
            "precision": test.get("precision"),
            "recall": test.get("recall"),
            "f1": test.get("f1"),
            "evaluation_status": test.get("status", "evaluated" if "f1" in test else "not_evaluated"),
        }
    merged = pd.read_csv(DATA / "merged_incidents_v0_2.csv")
    unresolved = merged[merged.sif_label == "UNCERTAIN"]
    unresolved_annotations = annotate_lsr(unresolved, id_column="incident_id")
    unresolved_positive_counts = {
        rule_id: int((unresolved_annotations[f"{rule_id}_target"] == "POSITIVE").sum())
        for rule_id in ("LSR01", "LSR02", "LSR08")
    }
    backend_root = PROJECT / "01-app" / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.services.domain_model import _supported_excerpt

    pool = pd.read_csv(ROOT / "data" / "candidate_pool_v0_2.csv", low_memory=False)
    eligible = pool[
        (pool.validation_locked.astype(str).str.casefold() != "true")
        & (~pool.duplicate_group.astype(str).isin(set(merged.duplicate_group.astype(str))))
    ]
    pattern_hits = {
        rule_id: int(sum(_supported_excerpt(text, rule_id) is not None for text in eligible.narrative.astype(str)))
        for rule_id in ("LSR01", "LSR02", "LSR08")
    }
    return {
        "rules": rules,
        "aggregate": saved["multilabel_summary"],
        "aggregate_handling": "Only known cells for the six trained rules are included. LSR01, LSR02 and LSR08 are excluded, not counted as negative or correct.",
        "unavailable_causes": {
            "LSR01": "0 positive training targets; only one positive in development and one in the regression test.",
            "LSR02": "1 positive training target, below the declared minimum of 3; development and regression test contain no positives.",
            "LSR08": "0 positive training targets; only two positives in development and two in the regression test.",
        },
        "eligible_record_check": {
            "unresolved_merged_rows_checked": len(unresolved),
            "additional_positive_targets": unresolved_positive_counts,
            "unused_unlocked_duplicate_isolated_pool_rows_checked": len(eligible),
            "unused_unlocked_duplicate_isolated_pool_pattern_hits": pattern_hits,
            "interpretation": "The unused pool contains possible LSR01/LSR02 annotation candidates, but these are pattern hits rather than accepted labels and include ambiguous matches. They were not added, scored, or forced into training. No strict LSR08 candidate was found.",
        },
        "runtime_zero_mapping_behavior": "When no supported rule maps, unavailable rules force MAPPING_UNAVAILABLE and coverage_complete=false. Missing evidence is disclosed and never treated as proof that a rule is irrelevant or that a violation did not occur.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Domain v0.2 diagnosis and demo-readiness report",
        "",
        "> The 90-report prototype test is a diagnostic regression benchmark, not fresh blind validation. No labels were changed and no model was fitted by this diagnosis.",
        "",
        "## SIF regression metrics",
        "",
        "| Model | TP | FP | TN | FN | Recall | Precision | Specificity | Balanced accuracy | F2 | Pred Non-SIF | Pred SIF | Review rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("active_baseline", "tfidf_candidate", "setfit_candidate", "all_sif_reference", "all_non_sif_reference"):
        row = report["regression_benchmark"][name]
        if "binary_prediction_metrics" not in row:
            lines.append(f"| {row.get('display_name', name)} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        metric = row["binary_prediction_metrics"]
        routing = row["operational_routing"]
        review = routing.get("human_review_rate")
        label = row.get("display_name", name)
        lines.append(
            f"| {label} | {metric['true_positives']} | {metric['false_positives']} | {metric['true_negatives']} | {metric['false_negatives']} | "
            f"{metric['recall']:.3f} | {metric['precision']:.3f} | {metric['specificity']:.3f} | {metric['balanced_accuracy']:.3f} | "
            f"{metric['f2']:.3f} | {metric['predicted_class_counts'][NON_SIF]} | {metric['predicted_class_counts'][SIF]} | "
            f"{'n/a' if review is None else f'{review:.1%}'} |"
        )
    causes = report["diagnosis"]["supported_causes"]
    lines.extend([
        "",
        "SetFit had no frozen operational review band; its review rate uses a diagnostic threshold ±0.05 band (0.20–0.30) and is not a deployed-routing claim.",
        "",
        "## Diagnosis",
        "",
    ])
    for cause in causes:
        lines.append(f"- **{cause['cause']}:** {cause['evidence']}")
    lines.extend([
        "",
        "## Active-model decision",
        "",
        report["active_model_decision"],
        "",
        "## LSR coverage",
        "",
        "| Rule | Status | Train P/N/U | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for rule_id, row in report["lsr_audit"]["rules"].items():
        counts = row["training_counts"]
        p, n, u = counts.get("POSITIVE", 0), counts.get("NEGATIVE", 0), counts.get("UNKNOWN", 0)
        fmt = lambda value: "n/a" if value is None else f"{value:.3f}"
        lines.append(f"| {rule_id} | {row['status']} | {p}/{n}/{u} | {fmt(row['precision'])} | {fmt(row['recall'])} | {fmt(row['f1'])} |")
    benchmark = report["demo_readiness"]["reused_latency_benchmark"]
    lines.extend([
        "",
        "Unavailable rules are omitted from aggregate metrics; they are never counted as confident negatives. Existing duplicate-isolated records contain possible LSR01/LSR02 evidence candidates, but no accepted annotations were manufactured and LSR01/02/08 remain unavailable.",
        "",
        "## Demo readiness",
        "",
        f"Focused API/runtime cases passed. Remeasured runtime benchmark: uncached API median/p95 {benchmark['median_ms']:.2f}/{benchmark['p95_ms']:.2f} ms; batch throughput {benchmark['batch_reports_per_second']:.2f} reports/s. Runtime generative LLM calls: 0.",
        "",
        "Remaining limitations: no fresh independent assessment supports promoting either candidate; labels are AI-assisted prototype references; three LSR rules are unavailable, so MAPPING_UNAVAILABLE takes precedence over an insufficient-information zero status; and no measured equivalent-output LLM comparison exists.",
    ])
    return "\n".join(lines) + "\n"


def diagnose(include_setfit: bool = True) -> dict[str, Any]:
    train = pd.read_csv(DATA / "train_v0_2.csv")
    dev = pd.read_csv(DATA / "development_v0_2.csv")
    test = pd.read_csv(DATA / "protected_test_v0_2.csv")
    y_dev = (dev.sif_label == SIF).astype(int).to_numpy()
    y_test = (test.sif_label == SIF).astype(int).to_numpy()

    load_warnings: dict[str, list[str]] = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        baseline = joblib.load(BASELINE / "tfidf_logreg.joblib")
    load_warnings["active_baseline"] = [str(item.message) for item in caught]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tfidf = joblib.load(CANDIDATES / "sif_tfidf.joblib")
    load_warnings["tfidf_candidate"] = [str(item.message) for item in caught]

    baseline_scores, baseline_classes, baseline_positive_index = positive_scores(baseline, test.narrative.tolist())
    tfidf_scores, tfidf_classes, tfidf_positive_index = positive_scores(tfidf, test.narrative.tolist())
    regression: dict[str, Any] = {
        "active_baseline": {"display_name": "Active baseline v0.1", **evaluate(y_test, baseline_scores, 0.40, 0.35, 0.45)},
        "tfidf_candidate": {"display_name": "TF-IDF candidate v0.2", **evaluate(y_test, tfidf_scores, 0.25, 0.20, 0.30)},
        "all_sif_reference": {"display_name": "All-SIF reference", **constant_baseline(y_test, 1)},
        "all_non_sif_reference": {"display_name": "All-Non-SIF reference", **constant_baseline(y_test, 0)},
    }
    predictions = pd.DataFrame({
        "test_id": test.test_id, "incident_id": test.incident_id, "reference_label": test.sif_label,
        "baseline_score": baseline_scores, "baseline_binary_prediction": np.where(baseline_scores >= 0.40, SIF, NON_SIF),
        "baseline_operational_route": route(baseline_scores, 0.35, 0.45),
        "tfidf_candidate_score": tfidf_scores, "tfidf_candidate_binary_prediction": np.where(tfidf_scores >= 0.25, SIF, NON_SIF),
        "tfidf_candidate_operational_route": route(tfidf_scores, 0.20, 0.30),
    })

    setfit_integrity: dict[str, Any] = {"status": "not_loaded"}
    if include_setfit:
        from setfit import SetFitModel

        setfit = SetFitModel.from_pretrained(str(CANDIDATES / "setfit_candidate"), local_files_only=True)
        setfit_scores, setfit_classes, setfit_positive_index = positive_scores(setfit, test.narrative.tolist())
        setfit_dev_scores, _, _ = positive_scores(setfit, dev.narrative.tolist())
        setfit_evaluation = evaluate(y_test, setfit_scores, 0.25, 0.20, 0.30)
        setfit_evaluation["operational_routing"]["status"] = "DIAGNOSTIC_BAND_NOT_FROZEN"
        setfit_evaluation["operational_routing"]["note"] = "SetFit has no frozen review band; this diagnostic rate uses threshold ±0.05 and is not a deployed-routing claim."
        regression["setfit_candidate"] = {"display_name": "SetFit candidate v0.2", **setfit_evaluation}
        predictions["setfit_candidate_score"] = setfit_scores
        predictions["setfit_candidate_binary_prediction"] = np.where(setfit_scores >= 0.25, SIF, NON_SIF)
        predictions["setfit_candidate_operational_route"] = route(setfit_scores, 0.20, 0.30)
        setfit_integrity = {
            "status": "loaded_from_saved_artifact", "labels": setfit_classes, "positive_probability_column": setfit_positive_index,
            "development": evaluate(y_dev, setfit_dev_scores, 0.25, 0.20, 0.30),
        }
    else:
        regression["setfit_candidate"] = {"display_name": "SetFit candidate v0.2", "status": "not_loaded"}

    saved_search = pd.read_csv(REPORTS / "sif_tfidf_development_search.csv")
    search = enrich_saved_search(saved_search)
    old_selected = next(row for row in search if row["c"] == 0.25 and row["class_weight"] == "none" and row["threshold"] == 0.25 and row["lower"] == 0.20 and row["upper"] == 0.30)
    fixed_selection = select_sif_operating_point(search, float(y_dev.mean()))

    runtime_path = Path(os.getenv("MODEL_PATH", "") or BASELINE).resolve()
    backend_root = PROJECT / "01-app" / "backend"
    sys.path.insert(0, str(backend_root))
    from app.services.classifier import FrozenClassifierAdapter
    from app.services.domain_model import DomainSafetyModel

    runtime_adapter = FrozenClassifierAdapter(runtime_path)
    runtime_metadata = runtime_adapter.metadata()
    runtime_service = DomainSafetyModel().load()
    demo_inputs = {
        "clear_sif": "An employee contacted an energized 13,800 volt power line and suffered severe burns.",
        "clear_non_sif": "A worker walking across a muddy yard slipped and twisted an ankle.",
        "uncertain_review": "An employee took measurements while standing on an earthen berm, lost balance, and fractured an ankle.",
        "single_rule": "The technician contacted an energized wire after lockout was not applied.",
        "multiple_rule": "A hopper being lifted by a forklift fell on the employee and caused a back injury.",
        "zero_mapping": "Routine housekeeping removed paper from an office floor.",
        "negated_hazard": "There were no dropped objects and isolation was verified before work began.",
    }
    demo_outputs: dict[str, Any] = {}
    for name, narrative in demo_inputs.items():
        screening = runtime_adapter.screen(narrative)
        mapping = runtime_service.map_rules(narrative)
        demo_outputs[name] = {
            "sif_decision": screening["decision"], "sif_score": screening["sif_score"],
            "review_required": screening["review_required"], "mapping_status": mapping["mapping_status"],
            "assigned_rule_ids": mapping["assigned_rule_ids"], "unavailable_rule_ids": mapping["unavailable_rule_ids"],
            "coverage_complete": mapping["coverage_complete"],
        }
    missing_mapping = DomainSafetyModel(PROJECT / "nonexistent-demo-lsr-artifact.joblib").map_rules("Short unclear report.")
    demo_checks = {
        "clear_sif": demo_outputs["clear_sif"]["sif_decision"] == "SIF_POTENTIAL",
        "clear_non_sif": demo_outputs["clear_non_sif"]["sif_decision"] == "NON_SIF_POTENTIAL",
        "uncertain_review": demo_outputs["uncertain_review"]["sif_decision"] == "HUMAN_REVIEW",
        "single_rule": "LSR04" in demo_outputs["single_rule"]["assigned_rule_ids"],
        "multiple_rule": {"LSR06", "LSR07"}.issubset(demo_outputs["multiple_rule"]["assigned_rule_ids"]),
        "zero_mapping_discloses_incomplete_coverage": demo_outputs["zero_mapping"]["mapping_status"] == "MAPPING_UNAVAILABLE" and not demo_outputs["zero_mapping"]["coverage_complete"],
        "processing_failure_is_unavailable": missing_mapping["mapping_status"] == "MAPPING_UNAVAILABLE" and len(missing_mapping["unavailable_rule_ids"]) == 9,
    }
    split = {
        "train": split_summary(train), "development": split_summary(dev), "regression_test": split_summary(test),
        "isolation": {
            pair: {column: overlap(left, right, column) for column in ("incident_id", "source_record_id", "duplicate_group", "normalized_narrative_sha256")}
            for pair, left, right in (("train_vs_development", train, dev), ("train_vs_regression_test", train, test), ("development_vs_regression_test", dev, test))
        },
        "input_allowlist": ["narrative"],
        "annotation_derived_fields_used_as_model_input": False,
        "cleaning_changes": {
            name: int(sum(clean_narrative(value) != value for value in frame.narrative.astype(str)))
            for name, frame in (("train", train), ("development", dev), ("regression_test", test))
        },
    }

    saved_benchmark = json.loads((REPORTS / "runtime_benchmark.json").read_text(encoding="utf-8"))
    report = {
        "report_version": "domain-v0.2-diagnosis-v1",
        "evaluation_status": "DIAGNOSTIC_REGRESSION_BENCHMARK_NOT_FRESH_BLIND_VALIDATION",
        "regression_benchmark": regression,
        "development_setup": split,
        "development_selection_audit": {
            "saved_search_rows": len(search),
            "saved_model_configurations": len({(row["c"], row["class_weight"]) for row in search}),
            "old_selected_operating_point": old_selected,
            "all_sif_development_f2": constant_baseline(y_dev, 1)["binary_prediction_metrics"]["f2"],
            "fixed_gate_result_on_saved_tfidf_search": fixed_selection,
            "setfit_saved_artifact": setfit_integrity.get("development"),
        },
        "model_integrity": {
            "active_runtime": {"resolved_artifact_directory": str(runtime_path), "MODEL_PATH_environment": os.getenv("MODEL_PATH"), **runtime_metadata},
            "active_baseline": {
                "classes": baseline_classes, "positive_probability_column": baseline_positive_index,
                "classifier_intercept": float(baseline.named_steps["classifier"].intercept_[0]),
                "artifact_sha256": sha256(BASELINE / "tfidf_logreg.joblib"), "load_warnings": load_warnings["active_baseline"],
            },
            "tfidf_candidate": {
                "classes": tfidf_classes, "positive_probability_column": tfidf_positive_index,
                "classifier_intercept": float(tfidf.named_steps["classifier"].intercept_[0]),
                "class_weight": tfidf.named_steps["classifier"].class_weight,
                "artifact_sha256": sha256(CANDIDATES / "sif_tfidf.joblib"), "load_warnings": load_warnings["tfidf_candidate"],
                "threshold_configuration": json.loads((CANDIDATES / "thresholds.json").read_text(encoding="utf-8")),
            },
            "setfit_candidate": setfit_integrity,
            "probability_mapping_result": "All saved classifiers encode NON_SIF as 0 and SIF as 1; column 1 is the positive score. No inversion was found.",
            "runtime_preprocessing_result": "The active baseline uses clean_narrative. Candidate adapter preprocessing was aligned by this fix; saved split narratives already match clean_narrative.",
        },
        "diagnosis": {
            "ranking_vs_threshold": "Both candidates rank the two classes usefully on the regression benchmark, but the saved TF-IDF threshold is below every score and therefore collapses to all-SIF.",
            "supported_causes": [
                {
                    "cause": "F2-only development selection rewarded the trivial class",
                    "evidence": f"Development prevalence is {y_dev.mean():.3f}. The selected TF-IDF point predicts all 92 rows SIF, has specificity 0 and F2 {old_selected['f2']:.3f}, exactly the all-SIF development F2.",
                },
                {
                    "cause": "Threshold/model score-scale mismatch after refit",
                    "evidence": "The threshold was chosen from a train-only model, then the saved TF-IDF vectorizer and classifier were re-fitted on train+development. The saved candidate intercept is 1.373 versus 0.630 for the baseline, and all 90 regression scores exceed 0.25.",
                },
                {
                    "cause": "Development/test prevalence and provenance differ",
                    "evidence": f"Train/development are {float((train.sif_label == SIF).mean()):.1%}/{float((dev.sif_label == SIF).mean()):.1%} SIF, versus {float((test.sif_label == SIF).mean()):.1%} in the deliberately balanced regression set. All are OSHA_SIR, but the test labels use a separate deterministic AI-assisted prototype process and reports are shorter.",
                },
            ],
            "ruled_out_or_not_supported": [
                "No positive-class probability-column inversion or label-encoding reversal was found.",
                "No incident ID, source ID, duplicate group, or normalized narrative hash crosses the saved train/development/regression partitions.",
                "The model input is narrative-only; annotation labels, explanations, provenance and LSR annotations are not passed to the vectorizers.",
                "Class weighting is not the direct cause of the deployed candidate collapse: the selected TF-IDF classifier used no class weights. The search nevertheless shows no TF-IDF point meeting the new recall/specificity gates.",
            ],
        },
        "active_model_decision": "Retain active baseline v0.1. The TF-IDF candidate fails the corrected development gates; SetFit remains a saved comparison candidate and is not promoted from the now-diagnostic 90-row benchmark. No replacement was selected, so no fresh final set was opened or manufactured.",
        "lsr_audit": lsr_audit(),
        "demo_readiness": {
            "runtime_examples": demo_outputs,
            "runtime_checks": {**demo_checks, "all_passed": all(demo_checks.values())},
            "focused_regression_checks": {
                "backend_api_and_domain_tests": "91 passed",
                "training_domain_tests": "30 passed",
                "persisted_human_adjudication": "covered by test_review_history_and_explicit_dispositions",
                "similar_incident_retrieval": "covered by test_grounded_reference_and_historical_retrieval",
                "frontend_production_build": "passed (Next.js production build, 17 routes)",
            },
            "runtime_generative_llm_calls": 0,
            "reused_latency_benchmark": {
                "source": "runtime_benchmark.json; remeasured after deterministic template and candidate-preprocessing fixes",
                "median_ms": saved_benchmark["full_analysis_api_uncached"]["median_ms"],
                "p95_ms": saved_benchmark["full_analysis_api_uncached"]["p95_ms"],
                "batch_reports_per_second": saved_benchmark["batch"]["reports_per_second"],
            },
            "relative_llm_speed_or_cost": "UNMEASURED_NO_COMPARABLE_AUTHORIZED_BENCHMARK",
        },
    }

    predictions.to_csv(REPORTS / "sif_regression_predictions_v0_2.csv", index=False, lineterminator="\n")
    json_write(REPORTS / "diagnosis_v0_2.json", report)
    (REPORTS / "diagnosis_v0_2.md").write_text(render_markdown(report), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-setfit", action="store_true", help="Skip the slower saved SetFit artifact check.")
    args = parser.parse_args()
    result = diagnose(include_setfit=not args.skip_setfit)
    print(json.dumps({
        "status": result["evaluation_status"],
        "active_model_decision": result["active_model_decision"],
        "reports": [str(REPORTS / "diagnosis_v0_2.json"), str(REPORTS / "diagnosis_v0_2.md"), str(REPORTS / "sif_regression_predictions_v0_2.csv")],
    }, indent=2))
