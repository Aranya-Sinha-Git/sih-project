"""Reproducible AI-assisted SIF v0.1 prototype training workflow.

This module intentionally trains only on the accepted binary consensus export.  It
never reads unresolved records or the locked external validation data.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline

from preprocess import clean_narrative, normalize_text, project_root, text_hash


SEED = 26165
SIF = "SIF_POTENTIAL"
NON_SIF = "NON_SIF_POTENTIAL"
STATUS = "AI_ASSISTED_SUPERVISED_PROTOTYPE"
LABEL_STATUS = "AI_ASSISTED_CONSENSUS"
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
NEAR_DUPLICATE_THRESHOLD = 0.95
ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"
DATA = ROOT / "data"
AI_DATA = DATA / "ai_labeling"
SPLITS = DATA / "splits"
ARTIFACTS = ROOT / "artifacts" / "supervised"
REPORTS = ROOT / "reports"


@dataclass(frozen=True)
class Split:
    train: np.ndarray
    validation: np.ndarray


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first: int, second: int) -> None:
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            self.parent[max(first_root, second_root)] = min(first_root, second_root)


def _json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _label_number(label: str) -> int:
    if label == SIF:
        return 1
    if label == NON_SIF:
        return 0
    raise ValueError(f"Unexpected final label: {label}")


def load_accepted_data() -> pd.DataFrame:
    """Load and validate only the 449 accepted binary AI-assisted labels."""
    labels = pd.read_csv(AI_DATA / "training_labels_v0_1.csv")
    required = {
        "candidate_id",
        "narrative",
        "final_sif_label",
        "label_provenance",
        "agreement_pattern",
        "final_confidence",
        "source",
    }
    if set(labels.columns) != required:
        raise ValueError("training_labels_v0_1.csv has an unexpected schema")
    labels["narrative"] = labels["narrative"].map(clean_narrative)
    if len(labels) != 449:
        raise ValueError(f"Expected 449 accepted rows, found {len(labels)}")
    if labels["candidate_id"].isna().any() or labels["candidate_id"].duplicated().any():
        raise ValueError("Accepted labels must have unique non-empty candidate IDs")
    if (labels["narrative"] == "").any():
        raise ValueError("Accepted labels contain missing narratives")
    if not set(labels["final_sif_label"]).issubset({SIF, NON_SIF}):
        raise ValueError("Only accepted binary labels may be trained")
    class_counts = labels["final_sif_label"].value_counts().to_dict()
    if class_counts != {SIF: 365, NON_SIF: 84}:
        raise ValueError(f"Unexpected accepted label counts: {class_counts}")

    metadata = pd.read_csv(DATA / "labeling_queue.csv", usecols=["candidate_id", "source_record_id"])
    labels = labels.merge(metadata, on="candidate_id", how="left", validate="one_to_one")
    if labels["source_record_id"].isna().any() or labels["source_record_id"].duplicated().any():
        raise ValueError("Missing or duplicate source_record_id metadata")
    labels["target"] = labels["final_sif_label"].map(_label_number).astype(int)
    return labels


def assign_event_groups(data: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Group exact and near-identical narratives before any split is made."""
    narratives = data["narrative"].tolist()
    union_find = UnionFind(len(data))
    exact_pairs = 0
    source_pairs = 0
    near_pairs = 0

    by_hash: dict[str, int] = {}
    by_source_record: dict[str, int] = {}
    for index, row in data.reset_index(drop=True).iterrows():
        narrative_hash = text_hash(row["narrative"])
        if narrative_hash in by_hash:
            union_find.union(index, by_hash[narrative_hash])
            exact_pairs += 1
        else:
            by_hash[narrative_hash] = index
        source_record_id = str(row["source_record_id"])
        if source_record_id in by_source_record:
            union_find.union(index, by_source_record[source_record_id])
            source_pairs += 1
        else:
            by_source_record[source_record_id] = index

    if len(data) > 1:
        vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True
        )
        matrix = vectorizer.fit_transform([normalize_text(text) for text in narratives])
        similarity = (matrix @ matrix.T).toarray()
        for left in range(len(data)):
            for right in np.flatnonzero(similarity[left, left + 1 :] >= NEAR_DUPLICATE_THRESHOLD) + left + 1:
                union_find.union(left, int(right))
                near_pairs += 1

    groups: dict[int, list[int]] = {}
    for index in range(len(data)):
        groups.setdefault(union_find.find(index), []).append(index)
    ordered_groups = sorted(groups.values(), key=lambda members: min(members))
    event_group = [""] * len(data)
    for number, members in enumerate(ordered_groups, start=1):
        group_id = f"event_group_{number:04d}"
        for member in members:
            event_group[member] = group_id
    grouped = data.copy()
    grouped["event_group"] = event_group
    sizes = Counter(event_group)
    audit = {
        "exact_duplicate_pairs": exact_pairs,
        "duplicate_source_record_pairs": source_pairs,
        "near_duplicate_pairs_at_or_above_0_95": near_pairs,
        "event_groups": len(sizes),
        "multi_record_event_groups": sum(size > 1 for size in sizes.values()),
        "largest_event_group": max(sizes.values(), default=0),
    }
    return grouped, audit


def create_split(data: pd.DataFrame) -> tuple[Split, list[dict[str, float]]]:
    """Choose the best fixed 5-fold group-stratified candidate near the 80/20 target."""
    y = data["target"].to_numpy()
    groups = data["event_group"].to_numpy()
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    candidates: list[tuple[tuple[float, float, float], Split, dict[str, float]]] = []
    for fold, (train_index, validation_index) in enumerate(splitter.split(data["narrative"], y, groups)):
        validation_rate = float(y[validation_index].mean())
        target_rate = float(y.mean())
        info = {
            "fold": float(fold),
            "train_rows": float(len(train_index)),
            "validation_rows": float(len(validation_index)),
            "validation_fraction": float(len(validation_index) / len(data)),
            "train_sif_rate": float(y[train_index].mean()),
            "validation_sif_rate": validation_rate,
        }
        score = (
            abs(info["validation_fraction"] - 0.20),
            abs(validation_rate - target_rate),
            abs(len(validation_index) - round(0.20 * len(data))),
        )
        candidates.append((score, Split(train_index, validation_index), info))
    _, selected, selected_info = min(candidates, key=lambda item: item[0])
    all_info = [info for _, _, info in candidates]
    if len(np.unique(y[selected.train])) != 2 or len(np.unique(y[selected.validation])) != 2:
        raise ValueError("Grouped split did not preserve both classes")
    return selected, [{**info, "selected": info["fold"] == selected_info["fold"]} for info in all_info]


def write_split_files(data: pd.DataFrame, split: Split) -> dict[str, Any]:
    SPLITS.mkdir(parents=True, exist_ok=True)
    fields = ["candidate_id", "final_sif_label", "source", "source_record_id", "event_group"]
    train = data.iloc[split.train][fields].sort_values("candidate_id")
    validation = data.iloc[split.validation][fields].sort_values("candidate_id")
    train.to_csv(SPLITS / "train_ids.csv", index=False)
    validation.to_csv(SPLITS / "validation_ids.csv", index=False)
    train_groups, validation_groups = set(train["event_group"]), set(validation["event_group"])
    if train_groups & validation_groups:
        raise ValueError("Event group leakage between train and validation")
    return {
        "seed": SEED,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "train_groups": len(train_groups),
        "validation_groups": len(validation_groups),
        "event_group_overlap": 0,
        "source_distribution_train": train["source"].value_counts().to_dict(),
        "source_distribution_validation": validation["source"].value_counts().to_dict(),
        "class_distribution_train": train["final_sif_label"].value_counts().to_dict(),
        "class_distribution_validation": validation["final_sif_label"].value_counts().to_dict(),
    }


def write_audit(data: pd.DataFrame, group_audit: dict[str, int]) -> dict[str, Any]:
    lengths = data["narrative"].str.len()
    leakage_columns = [
        column
        for column in data.columns
        if column in {"final_sif_label", "target", "label_provenance", "agreement_pattern", "final_confidence"}
    ]
    audit = {
        "dataset": "data/ai_labeling/training_labels_v0_1.csv",
        "training_label_status": LABEL_STATUS,
        "ai_assisted_not_expert_ground_truth": True,
        "accepted_binary_rows": int(len(data)),
        "expected_counts_verified": {SIF: int((data.target == 1).sum()), NON_SIF: int((data.target == 0).sum())},
        "unresolved_rows_excluded": 51,
        "missing_narratives": int((data.narrative == "").sum()),
        "duplicate_candidate_ids": int(data.candidate_id.duplicated().sum()),
        "duplicate_normalized_narratives": int(data.narrative.map(normalize_text).duplicated().sum()),
        "source_distribution": data.source.value_counts().to_dict(),
        "label_provenance_distribution": data.label_provenance.value_counts().to_dict(),
        "narrative_length_characters": {
            "min": int(lengths.min()),
            "median": float(lengths.median()),
            "mean": round(float(lengths.mean()), 4),
            "max": int(lengths.max()),
        },
        "model_input_fields": ["narrative"],
        "leakage_fields_excluded_from_model_input": leakage_columns + ["candidate_id", "source", "source_record_id", "event_group"],
        "near_duplicate_method": "character word-boundary TF-IDF cosine similarity >= 0.95, unioned with exact narrative and source-record groups",
        **group_audit,
    }
    _json(REPORTS / "training_data_audit.json", audit)
    return audit


def build_tfidf_pipeline(config: str) -> Pipeline:
    word = TfidfVectorizer(
        ngram_range=(1, 2), min_df=1, max_df=0.98, sublinear_tf=True, strip_accents="unicode"
    )
    if config == "tfidf_word_12":
        features: Any = word
    elif config == "tfidf_word_12_char_35":
        features = FeatureUnion(
            [
                ("word", word),
                ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
            ]
        )
    else:
        raise ValueError(f"Unknown TF-IDF configuration: {config}")
    return Pipeline(
        [("features", features), ("classifier", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED))]
    )


def metrics_for(y_true: np.ndarray, score: np.ndarray, threshold: float) -> dict[str, Any]:
    prediction = (score >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, prediction, average="binary", zero_division=0
    )
    beta = 2.0
    f2 = (1 + beta**2) * precision * recall / max(beta**2 * precision + recall, 1e-12)
    matrix = confusion_matrix(y_true, prediction, labels=[0, 1])
    tn, fp, fn, tp = [int(value) for value in matrix.ravel()]
    return {
        "threshold": round(float(threshold), 2),
        "precision": float(precision),
        "recall": float(recall),
        "false_negative_rate": float(fn / max(1, fn + tp)),
        "f1": float(f1),
        "f2": float(f2),
        "accuracy": float((prediction == y_true).mean()),
        "pr_auc": float(average_precision_score(y_true, score)),
        "roc_auc": float(roc_auc_score(y_true, score)) if len(np.unique(y_true)) == 2 else None,
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "false_negatives": fn,
        "support": {SIF: int((y_true == 1).sum()), NON_SIF: int((y_true == 0).sum())},
    }


def threshold_rows(model: str, y_true: np.ndarray, scores: np.ndarray) -> list[dict[str, Any]]:
    return [{"model": model, **metrics_for(y_true, scores, threshold)} for threshold in np.arange(0.20, 0.801, 0.05)]


def select_threshold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = next(row for row in rows if row["threshold"] == 0.5)
    precision_floor = max(0.75, 0.95 * baseline["precision"])
    viable = [row for row in rows if row["precision"] >= precision_floor]
    if not viable:
        viable = rows
    return max(viable, key=lambda row: (row["recall"], -row["false_negative_rate"], row["f2"], row["precision"], row["f1"]))


def comparison_key(metrics: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        metrics["recall"],
        -metrics["false_negative_rate"],
        metrics["f2"],
        metrics["precision"],
        metrics["f1"],
    )


def encode_sentences(texts: list[str], cache_key: str | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Encode using frozen all-MiniLM-L6-v2 mean pooling, caching the full matrix."""
    cache_dir = ARTIFACTS / "embedding_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = cache_key or hashlib.sha256((MODEL_ID + "\n" + "\n".join(texts)).encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{fingerprint}.npy"
    if cache_path.exists():
        return np.load(cache_path), {"cache_path": str(cache_path.relative_to(ROOT)), "cache_hit": True, "fingerprint": fingerprint}

    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, local_files_only=True)
    model = AutoModel.from_pretrained(MODEL_ID, local_files_only=True)
    model.eval()
    encoded_batches: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(texts), 32):
            batch = tokenizer(texts[start : start + 32], padding=True, truncation=True, max_length=256, return_tensors="pt")
            hidden = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            encoded_batches.append(pooled.cpu().numpy().astype("float32"))
    embeddings = np.vstack(encoded_batches)
    np.save(cache_path, embeddings)
    return embeddings, {"cache_path": str(cache_path.relative_to(ROOT)), "cache_hit": False, "fingerprint": fingerprint}


def train_and_evaluate(data: pd.DataFrame, split: Split) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    texts = data["narrative"].tolist()
    y = data["target"].to_numpy()
    train_texts = [texts[index] for index in split.train]
    validation_texts = [texts[index] for index in split.validation]
    y_train, y_validation = y[split.train], y[split.validation]
    threshold_records: list[dict[str, Any]] = []
    model_results: dict[str, Any] = {}

    for config in ("tfidf_word_12", "tfidf_word_12_char_35"):
        model = build_tfidf_pipeline(config).fit(train_texts, y_train)
        scores = model.predict_proba(validation_texts)[:, 1]
        rows = threshold_rows(config, y_validation, scores)
        chosen = select_threshold(rows)
        threshold_records.extend(rows)
        model_results[config] = {"family": "TF-IDF", "selected_threshold": chosen, "validation_scores": scores, "validation_model": model}

    embeddings, embedding_cache = encode_sentences(texts)
    embedding_classifier = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED).fit(embeddings[split.train], y_train)
    embedding_scores = embedding_classifier.predict_proba(embeddings[split.validation])[:, 1]
    embedding_rows = threshold_rows("embedding_logreg", y_validation, embedding_scores)
    embedding_chosen = select_threshold(embedding_rows)
    threshold_records.extend(embedding_rows)
    model_results["embedding_logreg"] = {
        "family": "Frozen SentenceTransformer embeddings",
        "selected_threshold": embedding_chosen,
        "validation_scores": embedding_scores,
        "validation_model": embedding_classifier,
        "embedding_cache": embedding_cache,
        "embedding_dimension": int(embeddings.shape[1]),
    }

    threshold_frame = pd.DataFrame(threshold_records)
    threshold_frame = threshold_frame[["model", "threshold", "precision", "recall", "false_negative_rate", "f1", "f2"]]
    threshold_frame.to_csv(REPORTS / "threshold_analysis.csv", index=False)

    best_tfidf_name = max(
        (name for name in model_results if name.startswith("tfidf_")),
        key=lambda name: comparison_key(model_results[name]["selected_threshold"]),
    )
    candidate_names = [best_tfidf_name, "embedding_logreg"]
    best_name = max(candidate_names, key=lambda name: comparison_key(model_results[name]["selected_threshold"]))
    return model_results, threshold_frame, {"best_tfidf": best_tfidf_name, "best_model": best_name, "y_validation": y_validation, "texts": texts, "embeddings": embeddings}


def write_error_reports(data: pd.DataFrame, split: Split, result: dict[str, Any], best_name: str) -> None:
    scores = result[best_name]["validation_scores"]
    threshold = result[best_name]["selected_threshold"]["threshold"]
    validation = data.iloc[split.validation].reset_index(drop=True)
    prediction = (scores >= threshold).astype(int)
    errors: list[dict[str, Any]] = []
    for row, score, predicted in zip(validation.itertuples(index=False), scores, prediction):
        if int(row.target) == int(predicted):
            continue
        errors.append(
            {
                "candidate_id": row.candidate_id,
                "source": row.source,
                "narrative": row.narrative,
                "true_label": SIF if row.target else NON_SIF,
                "predicted_label": SIF if predicted else NON_SIF,
                "score": round(float(score), 6),
                "error_type": "false_negative" if row.target == 1 else "false_positive",
            }
        )
    columns = ["candidate_id", "source", "narrative", "true_label", "predicted_label", "score", "error_type"]
    pd.DataFrame(errors, columns=columns).to_csv(REPORTS / "error_analysis.csv", index=False)
    pd.DataFrame([item for item in errors if item["error_type"] == "false_negative"], columns=columns).to_csv(
        REPORTS / "false_negatives.csv", index=False
    )


def write_top_features(model: Pipeline, config: str) -> None:
    features = model.named_steps["features"]
    if isinstance(features, FeatureUnion):
        names: list[str] = []
        for prefix, transformer in features.transformer_list:
            names.extend(f"{prefix}:{name}" for name in transformer.get_feature_names_out())
    else:
        names = list(features.get_feature_names_out())
    coefficients = model.named_steps["classifier"].coef_[0]
    rows: list[dict[str, Any]] = []
    for association, order in ((SIF, np.argsort(coefficients)[-25:][::-1]), (NON_SIF, np.argsort(coefficients)[:25])):
        for rank, index in enumerate(order, start=1):
            rows.append({"model": config, "association": association, "rank": rank, "feature": names[int(index)], "coefficient": round(float(coefficients[int(index)]), 6)})
    pd.DataFrame(rows).to_csv(REPORTS / "top_features.csv", index=False)


def refit_and_save(data: pd.DataFrame, result: dict[str, Any], selection: dict[str, Any]) -> tuple[dict[str, Any], float]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    best_tfidf = selection["best_tfidf"]
    best_name = selection["best_model"]
    full_texts = data["narrative"].tolist()
    y = data["target"].to_numpy()
    full_tfidf = build_tfidf_pipeline(best_tfidf).fit(full_texts, y)
    joblib.dump(full_tfidf, ARTIFACTS / "tfidf_logreg.joblib")
    write_top_features(full_tfidf, best_tfidf)

    full_embeddings = selection["embeddings"]
    full_embedding_classifier = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED).fit(full_embeddings, y)
    embedding_artifact = {
        "classifier": full_embedding_classifier,
        "model_id": MODEL_ID,
        "pooling": "attention-mask mean pooling with L2 normalization",
        "frozen_encoder": True,
        "embedding_dimension": int(full_embeddings.shape[1]),
    }
    joblib.dump(embedding_artifact, ARTIFACTS / "embedding_logreg.joblib")
    _json(
        ARTIFACTS / "embedding_metadata.json",
        {
            "model_id": MODEL_ID,
            "architecture": "frozen pretrained SentenceTransformer embeddings -> LogisticRegression",
            "fine_tuned": False,
            "pooling": embedding_artifact["pooling"],
            "embedding_dimension": embedding_artifact["embedding_dimension"],
            **result["embedding_logreg"]["embedding_cache"],
        },
    )

    threshold = float(result[best_name]["selected_threshold"]["threshold"])
    threshold_payload = {
        "model": best_name,
        "sif_threshold": threshold,
        "selection_rule": "maximise recall, then minimise SIF false-negative rate, then F2, precision and F1 subject to a validation precision floor of max(0.75, 95% of precision at 0.50)",
        "human_review_band": [round(max(0.0, threshold - 0.05), 2), round(min(1.0, threshold + 0.05), 2)],
        "not_probability_calibrated": True,
    }
    _json(ARTIFACTS / "threshold.json", threshold_payload)
    return threshold_payload, threshold


def write_status_and_docs(data: pd.DataFrame, split_info: dict[str, Any], result: dict[str, Any], selection: dict[str, Any], threshold_payload: dict[str, Any]) -> None:
    best_name = selection["best_model"]
    best = result[best_name]["selected_threshold"]
    tfidf = result[selection["best_tfidf"]]["selected_threshold"]
    embedding = result["embedding_logreg"]["selected_threshold"]
    model_status = {
        "model_version": "sif_v0.1",
        "status": STATUS,
        "external_validation_completed": False,
        "training_label_status": LABEL_STATUS,
        "accepted_ai_assisted_labels": len(data),
        "class_counts": {SIF: int((data.target == 1).sum()), NON_SIF: int((data.target == 0).sum())},
        "unresolved_excluded": 51,
        "selected_model": best_name,
        "selected_threshold": threshold_payload["sif_threshold"],
        "locked_external_validation": "IOGP 2025 remains untouched",
    }
    _json(ROOT / "MODEL_STATUS.json", model_status)
    _json(
        REPORTS / "supervised_training_status.json",
        {
            "trained": True,
            "status": STATUS,
            "training_rows": len(data),
            "split": split_info,
            "selected_model": best_name,
            "selected_threshold": threshold_payload["sif_threshold"],
            "validation_metrics": best,
        },
    )
    _json(
        REPORTS / "model_comparison.json",
        {
            "evaluation_scope": "internal agreement to AI-assisted consensus labels; not expert-validated SIF accuracy",
            "split_seed": SEED,
            "tfidf_model": selection["best_tfidf"],
            "tfidf_selected_threshold_metrics": tfidf,
            "embedding_model": f"frozen {MODEL_ID} -> LogisticRegression",
            "embedding_selected_threshold_metrics": embedding,
            "selected_prototype": best_name,
        },
    )

    def metric_line(metrics: dict[str, Any]) -> str:
        return (
            f"recall {metrics['recall']:.4f}; precision {metrics['precision']:.4f}; "
            f"F2 {metrics['f2']:.4f}; false negatives {metrics['false_negatives']}"
        )

    (ROOT / "TRAINING_REPORT.md").write_text(
        f"""# SIF NLP v0.1 Training Report

## Data and safeguards

- Training rows: 449 accepted binary AI-assisted labels ({int((data.target == 1).sum())} SIF potential; {int((data.target == 0).sum())} Non-SIF potential).
- Excluded: 51 unresolved records. No unresolved record was trained on.
- Label methodology: dual-pass consensus plus Pass C triple confirmation or 2-of-3 majority adjudication.
- Label status: `{LABEL_STATUS}`. These labels are not HSE expert ground truth.
- Model input: narrative only. IDs, source, source-record metadata, provenance, confidence, agreement pattern and labels were excluded from model features.
- Split: reproducible grouped stratified internal split, seed {SEED}; {split_info['train_rows']} train / {split_info['validation_rows']} validation; event-group overlap {split_info['event_group_overlap']}.
- External validation: not performed. IOGP 2025 remained locked and untouched.

## Internal agreement-to-consensus validation

These values measure reproduction of AI-assisted consensus labels on the internal validation partition; they are not validated real-world SIF accuracy.

| Model | Selected threshold | Recall | Precision | F2 | FNR | PR-AUC | ROC-AUC | False negatives |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TF-IDF (`{selection['best_tfidf']}`) | {tfidf['threshold']:.2f} | {tfidf['recall']:.4f} | {tfidf['precision']:.4f} | {tfidf['f2']:.4f} | {tfidf['false_negative_rate']:.4f} | {tfidf['pr_auc']:.4f} | {tfidf['roc_auc']:.4f} | {tfidf['false_negatives']} |
| Frozen embeddings (`{MODEL_ID}`) | {embedding['threshold']:.2f} | {embedding['recall']:.4f} | {embedding['precision']:.4f} | {embedding['f2']:.4f} | {embedding['false_negative_rate']:.4f} | {embedding['pr_auc']:.4f} | {embedding['roc_auc']:.4f} | {embedding['false_negatives']} |

## Prototype selection

Selected model: `{best_name}` at threshold {threshold_payload['sif_threshold']:.2f} ({metric_line(best)}). The decision rule prioritised SIF recall, false-negative rate, F2, precision and F1 in that order. Scores are not probability-calibrated. Scores within {threshold_payload['human_review_band'][0]:.2f}–{threshold_payload['human_review_band'][1]:.2f} are returned as `HUMAN_REVIEW`.

Human/HSE validation, calibration and external evaluation remain required before any operational use.
TF-IDF features are exported only as statistical associations, not causal explanations.
""",
        encoding="utf-8",
    )
    (ROOT / "MODEL_CARD.md").write_text(
        f"""# Model Card — SIF NLP v0.1

## Status

`{STATUS}`. This is an internal AI-assisted supervised prototype, not an expert-validated or production-approved model.

## Intended use

Narrative-only triage of reports for possible SIF potential. It must not approve work, replace safety procedures, or replace human/HSE review.

## Training data

The training set has 449 accepted AI-assisted binary labels: 365 `SIF_POTENTIAL` and 84 `NON_SIF_POTENTIAL`. It was created through dual/three-pass AI labeling. The 51 unresolved records were excluded. Labels are not HSE expert ground truth and are from `OSHA_SIR`, so source/domain transfer limits apply.

## Models

- TF-IDF word 1–2 grams, with an evaluated character n-gram variant, followed by class-weighted Logistic Regression.
- Frozen `{MODEL_ID}` sentence embeddings with attention-mask mean pooling and class-weighted Logistic Regression. The encoder was not fine-tuned.

The selected prototype is `{best_name}` at internal threshold {threshold_payload['sif_threshold']:.2f}. `sif_score` is an uncalibrated model score, not a validated probability. Scores in the {threshold_payload['human_review_band'][0]:.2f}–{threshold_payload['human_review_band'][1]:.2f} band require human review.

## Evaluation and limitations

Internal validation is a duplicate-safe grouped split with fixed seed {SEED}. Metrics measure agreement with AI-assisted consensus labels, not validated SIF outcomes. There is no external human/HSE validation and IOGP 2025 was not used or modified. Before operational use, obtain expert labels, validate externally, assess calibration and false-negative performance, and run shadow-mode HSE review.
""",
        encoding="utf-8",
    )


def train_all() -> dict[str, Any]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    data = load_accepted_data()
    data, group_audit = assign_event_groups(data)
    audit = write_audit(data, group_audit)
    split, split_candidates = create_split(data)
    split_info = write_split_files(data, split)
    audit["split_candidates"] = split_candidates
    audit["selected_split"] = split_info
    _json(REPORTS / "training_data_audit.json", audit)
    result, _, selection = train_and_evaluate(data, split)
    threshold_payload, _ = refit_and_save(data, result, selection)
    write_error_reports(data, split, result, selection["best_model"])
    write_status_and_docs(data, split_info, result, selection, threshold_payload)
    return {
        "training_rows": len(data),
        "train_rows": split_info["train_rows"],
        "validation_rows": split_info["validation_rows"],
        "tfidf": result[selection["best_tfidf"]]["selected_threshold"],
        "embedding": result["embedding_logreg"]["selected_threshold"],
        "best_model": selection["best_model"],
        "threshold": threshold_payload["sif_threshold"],
        "human_review_band": threshold_payload["human_review_band"],
    }


def validate_saved_split() -> None:
    """Test helper ensuring saved group IDs cannot leak between partitions."""
    train = pd.read_csv(SPLITS / "train_ids.csv")
    validation = pd.read_csv(SPLITS / "validation_ids.csv")
    if set(train.candidate_id) & set(validation.candidate_id):
        raise ValueError("Candidate ID leakage in saved split")
    if set(train.event_group) & set(validation.event_group):
        raise ValueError("Near-duplicate event-group leakage in saved split")


if __name__ == "__main__":
    print(json.dumps(train_all(), indent=2))
