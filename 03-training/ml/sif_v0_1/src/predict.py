"""Safe local inference for the selected AI-assisted SIF v0.1 prototype."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib

from preprocess import clean_narrative, project_root


ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"
ARTIFACTS = ROOT / "artifacts" / "supervised"
MODEL_VERSION = "sif_v0.1"
MODEL_STATUS = "AI_ASSISTED_SUPERVISED_PROTOTYPE"
_ENCODER: tuple[Any, Any] | None = None
_THRESHOLD_CACHE: dict[str, dict[str, Any]] = {}
_MODEL_CACHE: dict[str, Any] = {}
POLICY_REVIEW_BAND = (0.35, 0.45)
SUPPORTED_MODEL_ARTIFACTS = {
    "embedding_logreg": "embedding_logreg.joblib",
    "tfidf_word_12_char_35": "tfidf_logreg.joblib",
}


def _review_response(reason: str, status: str = MODEL_STATUS) -> dict[str, Any]:
    return {
        "model_version": MODEL_VERSION,
        "model_status": status,
        "sif_score": None,
        "decision": "HUMAN_REVIEW",
        "review_required": True,
        "reason": reason,
    }


def _embedding_score(text: str, artifact: dict[str, Any]) -> float:
    global _ENCODER
    if _ENCODER is None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(artifact["model_id"], local_files_only=True)
        model = AutoModel.from_pretrained(artifact["model_id"], local_files_only=True)
        model.eval()
        _ENCODER = tokenizer, model
    tokenizer, model = _ENCODER
    import torch

    with torch.no_grad():
        batch = tokenizer([text], padding=True, truncation=True, max_length=256, return_tensors="pt")
        hidden = model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        vector = torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy().astype("float32")
    return float(artifact["classifier"].predict_proba(vector)[0, 1])


def _threshold_info(artifacts: Path) -> dict[str, Any] | None:
    threshold_path = artifacts / "threshold.json"
    cache_key = str(threshold_path.resolve())
    if cache_key in _THRESHOLD_CACHE:
        return _THRESHOLD_CACHE[cache_key]
    if not threshold_path.exists():
        return None
    try:
        threshold_info = json.loads(threshold_path.read_text(encoding="utf-8"))
        lower, upper = [float(value) for value in threshold_info["human_review_band"]]
        if (lower, upper) != POLICY_REVIEW_BAND:
            return None
        threshold_info["sif_threshold"] = float(threshold_info["sif_threshold"])
        _THRESHOLD_CACHE[cache_key] = threshold_info
        return threshold_info
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _load_model(path: Path) -> Any:
    cache_key = str(path.resolve())
    if cache_key not in _MODEL_CACHE:
        _MODEL_CACHE[cache_key] = joblib.load(path)
    return _MODEL_CACHE[cache_key]


def predict(text: object, artifact_dir: Path | None = None) -> dict[str, Any]:
    """Score one narrative with the selected artifact; never claim probability calibration."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    narrative = clean_narrative(text)
    if not narrative:
        return _review_response("empty_narrative")

    artifacts = artifact_dir or ARTIFACTS
    threshold_info = _threshold_info(artifacts)
    if threshold_info is None:
        return _review_response("model_artifact_missing_or_invalid", status="ARTIFACT_MISSING")
    selected_model = threshold_info.get("model")
    try:
        artifact_name = SUPPORTED_MODEL_ARTIFACTS.get(selected_model)
        if artifact_name == "embedding_logreg.joblib":
            path = artifacts / artifact_name
            if not path.exists():
                return _review_response("model_artifact_missing", status="ARTIFACT_MISSING")
            score = _embedding_score(narrative, _load_model(path))
        elif artifact_name == "tfidf_logreg.joblib":
            path = artifacts / artifact_name
            if not path.exists():
                return _review_response("model_artifact_missing", status="ARTIFACT_MISSING")
            score = float(_load_model(path).predict_proba([narrative])[0, 1])
        else:
            return _review_response("invalid_model_selection", status="ARTIFACT_MISSING")
    except Exception:
        return _review_response("model_inference_failed", status="INFERENCE_FAILED")

    if not 0.0 <= score <= 1.0:
        return _review_response("model_score_out_of_range", status="INFERENCE_FAILED")
    lower, upper = POLICY_REVIEW_BAND
    decision = "NON_SIF_POTENTIAL" if score < lower else "HUMAN_REVIEW" if score <= upper else "SIF_POTENTIAL"
    review_required = decision == "HUMAN_REVIEW"
    return {
        "model_version": MODEL_VERSION,
        "model_status": MODEL_STATUS,
        "sif_score": round(score, 5),
        "decision": decision,
        "review_required": review_required,
        "thresholds": {"non_sif_upper_exclusive": lower, "review_lower_inclusive": lower, "review_upper_inclusive": upper, "sif_lower_exclusive": upper},
        "calibration_status": "uncalibrated",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    print(json.dumps(predict(args.text), indent=2))
