"""Adapter for the frozen SIF classifier used by the operational API.

The rules engine remains responsible for extraction and evidence cues.  This
module owns screening only, so a classifier failure can never be mistaken for
either a positive or a negative decision.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
_configured_model_path = os.getenv("MODEL_PATH", "").strip()
if _configured_model_path:
    _model_path = Path(_configured_model_path).expanduser()
    MODEL_ARTIFACT_DIR = _model_path if _model_path.is_absolute() else PROJECT_ROOT / _model_path
else:
    MODEL_ARTIFACT_DIR = PROJECT_ROOT / "03-training" / "ml" / "sif_v0_1" / "artifacts" / "supervised"
DEFAULT_ARTIFACT_DIR = MODEL_ARTIFACT_DIR
PREDICT_PATH = PROJECT_ROOT / "03-training" / "ml" / "sif_v0_1" / "src" / "predict.py"
POLICY_REVIEW_BAND = (0.35, 0.45)
_PREDICTOR: Any = None
_ADAPTERS: dict[str, "FrozenClassifierAdapter"] = {}


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _predict_module() -> Any:
    global _PREDICTOR
    if _PREDICTOR is not None:
        return _PREDICTOR
    src_dir = str(PREDICT_PATH.parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    spec = importlib.util.spec_from_file_location("sif_sentinel_frozen_predict", PREDICT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load frozen predictor from {PREDICT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PREDICTOR = module
    return module


class FrozenClassifierAdapter:
    def __init__(self, artifact_dir: Path | None = None) -> None:
        self.artifact_dir = Path(artifact_dir or DEFAULT_ARTIFACT_DIR)
        self._metadata: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        if self._metadata is not None:
            return self._metadata
        threshold_path = self.artifact_dir / "threshold.json"
        info: dict[str, Any] = {}
        try:
            info = json.loads(threshold_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._metadata = {
                "model_version": "sif-v0.1",
                "model_identity": None,
                "model_hash": None,
                "configuration_hash": _sha256(threshold_path),
                "status": "ARTIFACT_MISSING",
                "thresholds": self._thresholds(),
                "calibration_status": "uncalibrated",
            }
            return self._metadata
        selected = info.get("model")
        supported_models = getattr(_predict_module(), "SUPPORTED_MODEL_ARTIFACTS", {})
        artifact_name = supported_models.get(selected) if isinstance(supported_models, dict) else None
        model_path = self.artifact_dir / artifact_name if artifact_name else None
        try:
            band = tuple(float(value) for value in info.get("human_review_band", ()))
        except (TypeError, ValueError):
            band = ()
        self._metadata = {
            "model_version": "sif-v0.1",
            "model_identity": selected,
            "model_hash": _sha256(model_path) if model_path is not None else None,
            "configuration_hash": _sha256(threshold_path),
            "status": "READY" if model_path is not None and model_path.exists() and band == POLICY_REVIEW_BAND else "ARTIFACT_INVALID",
            "thresholds": self._thresholds(info),
            "calibration_status": "uncalibrated",
        }
        return self._metadata

    @staticmethod
    def _thresholds(info: dict[str, Any] | None = None) -> dict[str, float]:
        info = info or {}
        try:
            selected_threshold = float(info.get("sif_threshold", 0.4))
        except (TypeError, ValueError):
            selected_threshold = 0.4
        return {
            "non_sif_upper_exclusive": POLICY_REVIEW_BAND[0],
            "review_lower_inclusive": POLICY_REVIEW_BAND[0],
            "review_upper_inclusive": POLICY_REVIEW_BAND[1],
            "sif_lower_exclusive": POLICY_REVIEW_BAND[1],
            "selected_sif_threshold": selected_threshold,
        }

    def screen(self, narrative: str) -> dict[str, Any]:
        try:
            result = _predict_module().predict(narrative, artifact_dir=self.artifact_dir)
        except Exception:
            result = {
                "model_version": "sif-v0.1",
                "model_status": "INFERENCE_FAILED",
                "sif_score": None,
                "decision": "HUMAN_REVIEW",
                "review_required": True,
                "reason": "model_inference_failed",
            }
        score = result.get("sif_score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = None
            lower, upper = POLICY_REVIEW_BAND
            expected = "NON_SIF_POTENTIAL" if score is not None and score < lower else "HUMAN_REVIEW" if score is not None and score <= upper else "SIF_POTENTIAL" if score is not None else "HUMAN_REVIEW"
            if score is None or not 0.0 <= score <= 1.0 or result.get("decision") != expected:
                result = {"model_version": "sif-v0.1", "model_status": "INFERENCE_FAILED", "sif_score": None, "decision": "HUMAN_REVIEW", "review_required": True, "reason": "invalid_model_output"}
        elif result.get("decision") != "HUMAN_REVIEW":
            result = {"model_version": "sif-v0.1", "model_status": "INFERENCE_FAILED", "sif_score": None, "decision": "HUMAN_REVIEW", "review_required": True, "reason": "invalid_model_output"}
        meta = self.metadata()
        return {**result, "model_identity": meta["model_identity"], "model_hash": meta["model_hash"], "configuration_hash": meta["configuration_hash"], "thresholds": result.get("thresholds", meta["thresholds"]), "calibration_status": result.get("calibration_status", meta["calibration_status"])}


def get_classifier(artifact_dir: Path | None = None) -> FrozenClassifierAdapter:
    resolved = Path(artifact_dir or DEFAULT_ARTIFACT_DIR).resolve()
    key = str(resolved)
    if key not in _ADAPTERS:
        _ADAPTERS[key] = FrozenClassifierAdapter(resolved)
    return _ADAPTERS[key]


def analyze_with_classifier(narrative: str, supplemental: dict[str, Any], artifact_dir: Path | None = None) -> dict[str, Any]:
    screening = get_classifier(artifact_dir).screen(narrative)
    decision = screening.get("decision")
    score = screening.get("sif_score")
    if decision == "SIF_POTENTIAL":
        classification, risk, sif_potential, review_required = "SIF Potential", "High", True, False
    elif decision == "NON_SIF_POTENTIAL":
        classification, risk, sif_potential, review_required = "Non-SIF Potential", "Low", False, False
    else:
        classification, risk, sif_potential, review_required = "Needs Review", "Medium", None, True
    analysis = dict(supplemental)
    analysis.update({
        "sif_probability": score,
        "risk": risk,
        "classification": classification,
        "classification_basis": "Frozen classifier raw score; not calibrated as a probability.",
        "model_mode": "Frozen supervised classifier",
        "model_version": screening.get("model_version", "sif-v0.1"),
        "priority": "Immediate attention" if decision == "SIF_POTENTIAL" else "Review" if review_required else "Monitor",
        "review_required": review_required,
        "sif_potential": sif_potential,
        "sif_label_status": "classifier_screened" if sif_potential is not None else "unresolved",
        "screening": {
            "model_identity": screening.get("model_identity"),
            "model_hash": screening.get("model_hash"),
            "configuration_hash": screening.get("configuration_hash"),
            "raw_score": score,
            "decision": decision,
            "thresholds": screening.get("thresholds"),
            "calibration_status": screening.get("calibration_status", "uncalibrated"),
            "failure_reason": screening.get("reason"),
        },
    })
    return analysis


def classifier_metadata(artifact_dir: Path | None = None) -> dict[str, Any]:
    return get_classifier(artifact_dir).metadata()
