"""Grouped internal validation and threshold/error reports for supervised models."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from preprocess import project_root

ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"; REPORTS = ROOT / "reports"; SPLITS = ROOT / "data" / "splits"


def _metrics(y_true, score, threshold):
    pred = (np.asarray(score) >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, pred, average="binary", zero_division=0)
    beta = 2; f2 = (1 + beta**2) * precision * recall / max(beta**2 * precision + recall, 1e-12)
    matrix = confusion_matrix(y_true, pred, labels=[0, 1]); fnr = matrix[1, 0] / max(1, matrix[1].sum())
    return {"threshold": round(float(threshold), 2), "precision": float(precision), "recall": float(recall), "f1": float(f1), "f2": float(f2), "false_negative_rate": float(fnr), "confusion_matrix": matrix.tolist()}


def binary_metrics(y_true, score, threshold):
    """Pure frozen-score metrics; this helper never fits or selects a threshold."""
    y_true = np.asarray(y_true, dtype=int)
    score = np.asarray(score, dtype=float)
    pred = (score >= float(threshold)).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, pred, average="binary", zero_division=0)
    beta = 2
    f2 = (1 + beta**2) * precision * recall / max(beta**2 * precision + recall, 1e-12)
    matrix = confusion_matrix(y_true, pred, labels=[0, 1])
    fn_ids = [int(index) for index, actual in enumerate(y_true) if actual == 1 and pred[index] == 0]
    return {"threshold": float(threshold), "precision": float(precision), "recall": float(recall), "f1": float(f1), "f2": float(f2), "confusion_matrix": matrix.tolist(), "false_negative_indices": fn_ids}


def evaluate_and_write(rows, pipeline_factory, model_name):
    REPORTS.mkdir(parents=True, exist_ok=True); SPLITS.mkdir(parents=True, exist_ok=True)
    texts = [row["narrative"] for row in rows]; labels = np.asarray([row["label"] for row in rows])
    groups = np.asarray([row.get("duplicate_group") or row.get("candidate_id") for row in rows])
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=26165)
    train_i, valid_i = next(splitter.split(texts, labels, groups))
    model = pipeline_factory().fit([texts[i] for i in train_i], labels[train_i])
    score = model.predict_proba([texts[i] for i in valid_i])[:, 1]; y = labels[valid_i]
    thresholds = [_metrics(y, score, threshold / 100) for threshold in range(20, 81, 5)]
    best = max(thresholds, key=lambda item: (item["recall"] >= 0.90, item["f2"], item["precision"]))
    overall = _metrics(y, score, best["threshold"])
    overall.update({"pr_auc": float(average_precision_score(y, score)), "roc_auc": float(roc_auc_score(y, score)), "support": {"sif": int(y.sum()), "non_sif": int((y == 0).sum())}})
    with (REPORTS / "threshold_analysis.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["threshold", "precision", "recall", "false_negative_rate", "f1", "f2"]); writer.writeheader(); writer.writerows(thresholds)
    errors = []
    for index, probability in zip(valid_i, score):
        row = rows[index]; pred = int(probability >= best["threshold"]); actual = row["label"]
        if pred != actual: errors.append({"candidate_id": row.get("candidate_id", ""), "source": row.get("source", ""), "narrative": row["narrative"], "true_label": actual, "predicted_label": pred, "score": round(float(probability), 5), "error_type": "false_negative" if actual else "false_positive"})
    for filename, content in (("error_analysis.csv", errors), ("false_negatives.csv", [r for r in errors if r["error_type"] == "false_negative"])):
        with (REPORTS / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["candidate_id", "source", "narrative", "true_label", "predicted_label", "score", "error_type"]); writer.writeheader(); writer.writerows(content)
    (SPLITS / "internal_validation_ids.json").write_text(json.dumps({"seed": 26165, "train_ids": [rows[i].get("candidate_id") for i in train_i], "validation_ids": [rows[i].get("candidate_id") for i in valid_i]}), encoding="utf-8")
    (REPORTS / f"{model_name}_metrics.json").write_text(json.dumps(overall, indent=2), encoding="utf-8")
    return {"model_name": model_name, "metrics": overall, "recommended_threshold": best["threshold"], "fitted_model": model}
