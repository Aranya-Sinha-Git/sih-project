"""Cached, offline SIF + IOGP Life-Saving Rule inference.

The deployed SIF screen remains the promoted model artifact.  LSR relevance is
scored by the v0.2 multilabel model and explained with deterministic narrative
excerpts; this module never calls a generative model or a network service.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from .classifier import get_classifier


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LSR_ARTIFACT = PROJECT_ROOT / "03-training" / "ml" / "sif_v0_1" / "artifacts" / "domain_adapted_v0_2" / "lsr_model.joblib"
STATUS_PRECEDENCE = ["MAPPING_UNAVAILABLE", "INSUFFICIENT_INFORMATION", "BORDERLINE_MAPPING", "NO_CONFIDENT_MAPPING"]

RULE_PATTERNS: dict[str, tuple[str, ...]] = {
    "LSR01": (r"\b(?:guard|interlock|alarm|safety control|trip).{0,35}(?:bypass|disable|defeat|override|removed|missing|absent)\b", r"\bwithout (?:a )?guard\b"),
    "LSR02": (r"\bconfined space\b", r"\b(?:entered|inside|within) (?:a |the )?(?:tank|vessel|silo|manhole|reactor)\b"),
    "LSR03": (r"\b(?:driver|driving|vehicle|truck|car|ATV|UTV|bus|telehandler).{0,70}(?:crash|collision|collid|rollover|overturned|veered|struck|ran over|lost control)\b", r"\b(?:driver|driving|vehicle|truck|car|ATV|UTV|bus|telehandler).{0,45}(?:speeding|high speed|distracted|fatigued|seatbelt|journey management)\b"),
    "LSR04": (r"\b(?:energized|electric shock|power line|hot wire|stored pressure|trapped pressure|pressurized|residual pressure|lockout|tagout|zero energy|unexpectedly started|actuated)\b",),
    "LSR05": (r"\b(?:weld|welding|torch|hot tap|gouging|grinding).{0,80}(?:fire|flammable|gas|vapou?r|explos|ignit)\b", r"\b(?:flash fire|flammable gas|ignition source)\b"),
    "LSR06": (r"\b(?:struck by|pinned|crushed|caught between|line of fire|release path|whip|snapback|fell on|dropped|falling object|run over)\b", r"\b(?:pipe|load|equipment|vehicle|truck|forklift|cap|hose|cable).{0,55}(?:fell|struck|hit|pinned|crushed|released|whip)\b"),
    "LSR07": (r"\b(?:crane|hoist|forklift|telehandler|rigging|sling|suspended load|lifting operation).{0,75}(?:lift|lower|fell|fall|drop|failed|slipped|swung|struck)\b",),
    "LSR08": (r"\b(?:permit|work authori[sz]ation).{0,60}(?:missing|without|failed|expired|not authori[sz]ed)\b", r"\bwithout (?:a )?(?:valid )?permit\b"),
    "LSR09": (r"\b(?:fell|fall|working|climbing|descending).{0,80}(?:roof|ladder|scaffold|platform|derrick|catwalk|floor opening|height|feet|foot|ft)\b", r"\b(?:fall protection|harness|lanyard|tie off|anchor point)\b"),
}

VIOLATION_PATTERNS: dict[str, str] = {
    "LSR01": r"\b(?:bypassed|disabled|defeated|overrode|without (?:a )?guard|guard.{0,20}(?:removed|missing))\b",
    "LSR02": r"\b(?:without authori[sz]ation|atmosphere.{0,20}not tested|no attendant|no rescue plan|not isolated)\b",
    "LSR03": r"\b(?:speeding|distracted|fatigued|without (?:a )?seatbelt|not wearing (?:a )?seatbelt|lost control)\b",
    "LSR04": r"\b(?:not isolated|inadequate isolation|without lockout|trapped pressure|residual pressure|unexpectedly (?:started|actuated))\b",
    "LSR05": r"\b(?:flammable.{0,30}(?:not removed|not isolated)|gas test.{0,20}not|ignition source.{0,20}not controlled)\b",
    "LSR06": r"\b(?:in the line of fire|under (?:a )?(?:suspended|falling) load|between.{0,30}(?:vehicle|equipment)|no exclusion zone)\b",
    "LSR07": r"\b(?:sling|rigging|chain|hoist).{0,30}(?:failed|broke|slipped)|\b(?:load|equipment).{0,30}(?:not secured|fell|dropped)\b",
    "LSR08": r"\b(?:without (?:a )?(?:valid )?permit|not authori[sz]ed|conditions changed.{0,30}(?:continued|did not stop))\b",
    "LSR09": r"\b(?:without|no|not connected|not tied|failed|missing).{0,25}(?:fall protection|harness|lanyard|tie off)\b",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", " ".join((text or "").split())) if part.strip()]


def _supported_excerpt(text: str, rule_id: str) -> str | None:
    for sentence in _sentences(text):
        if re.search(r"\b(?:hypothetical|imaginary|training scenario only)\b", sentence, re.I):
            continue
        if re.search(r"\b(?:no|not|never)\s+(?:evidence of\s+)?(?:fire|explosion|fall|pressure release|contact|dropped objects?)\b", sentence, re.I):
            continue
        if re.search(r"\b(?:no|not|never)\s+(?:evidence of\s+)?(?:speeding|high speed|distracted driving|fatigue|seatbelt|journey-management failure)\b", sentence, re.I):
            continue
        if any(re.search(pattern, sentence, re.I) for pattern in RULE_PATTERNS[rule_id]):
            return sentence
    return None


class DomainSafetyModel:
    def __init__(self, lsr_artifact_path: Path = DEFAULT_LSR_ARTIFACT) -> None:
        self.lsr_artifact_path = Path(lsr_artifact_path)
        self.classifier = get_classifier()
        self.lsr: dict[str, Any] | None = None
        self.load_error: str | None = None
        self.artifact_hash: str | None = None

    def load(self) -> "DomainSafetyModel":
        # Materialize both artifacts once during startup. Classifier metadata also
        # validates the configured SIF model and causes no network traffic.
        self.classifier.metadata()
        if self.lsr is None and self.load_error is None:
            try:
                self.lsr = joblib.load(self.lsr_artifact_path)
                self.artifact_hash = _sha256(self.lsr_artifact_path)
            except Exception as error:
                self.load_error = f"{type(error).__name__}: {error}"
        return self

    def metadata(self) -> dict[str, Any]:
        self.load()
        unavailable_rule_ids = sorted(rule_id for rule_id, spec in (self.lsr or {}).get("rules", {}).items() if not spec.get("available"))
        supported_rule_ids = sorted(rule_id for rule_id, spec in (self.lsr or {}).get("rules", {}).items() if spec.get("available"))
        return {
            "sif": self.classifier.metadata(),
            "lsr_version": self.lsr.get("version") if self.lsr else None,
            "lsr_reference_id": self.lsr.get("reference", {}).get("reference_id") if self.lsr else None,
            "lsr_artifact_hash": self.artifact_hash,
            "lsr_status": "READY" if self.lsr else "MAPPING_UNAVAILABLE",
            "lsr_failure_reason": self.load_error,
            "supported_rule_ids": supported_rule_ids,
            "unavailable_rule_ids": unavailable_rule_ids,
            "coverage_complete": bool(self.lsr) and not unavailable_rule_ids,
            "runtime_generative_llm_calls": False,
        }

    def map_rules_batch(self, narratives: list[str]) -> list[dict[str, Any]]:
        self.load()
        if not self.lsr:
            return [self._unavailable_mapping(self.load_error or "lsr_artifact_not_loaded") for _ in narratives]
        started = time.perf_counter()
        try:
            matrix = self.lsr["vectorizer"].transform(narratives)
            scores: dict[str, np.ndarray] = {}
            for rule_id, spec in self.lsr["rules"].items():
                if spec.get("available"):
                    scores[rule_id] = spec["classifier"].predict_proba(matrix)[:, 1]
        except Exception as error:
            return [self._unavailable_mapping(f"processing_failure:{type(error).__name__}") for _ in narratives]
        preprocessing_ms = (time.perf_counter() - started) * 1000
        return [self._render_mapping(text, index, scores, preprocessing_ms / max(1, len(narratives))) for index, text in enumerate(narratives)]

    def map_rules(self, narrative: str) -> dict[str, Any]:
        return self.map_rules_batch([narrative])[0]

    def _render_mapping(self, text: str, index: int, scores: dict[str, np.ndarray], preprocessing_ms: float) -> dict[str, Any]:
        started = time.perf_counter()
        rules: list[dict[str, Any]] = []
        unavailable: list[str] = []
        assigned: list[str] = []
        borderline: list[str] = []
        for rule_id, spec in self.lsr["rules"].items():
            name = spec.get("name") or next((row["name"] for row in self.lsr["reference"]["rules"] if row["id"] == rule_id), rule_id)
            if not spec.get("available"):
                unavailable.append(rule_id)
                rules.append({"rule_id": rule_id, "name": name, "score": None, "score_type": "unavailable", "assignment_status": "UNAVAILABLE", "reason_code": spec.get("reason", "RULE_NOT_TRAINED"), "evidence": [], "violation_status": "NOT_ASSESSED", "rendered_explanation": f"{name} is unavailable because the training data did not support a classifier."})
                continue
            score = float(scores[rule_id][index])
            threshold = float(spec["threshold"]); borderline_threshold = float(spec["borderline_threshold"])
            excerpt = _supported_excerpt(text, rule_id)
            if score >= threshold and excerpt:
                status = "ASSIGNED"; reason = "MODEL_SCORE_AT_OR_ABOVE_RULE_THRESHOLD"; assigned.append(rule_id)
            elif score >= threshold:
                # A model score alone is not enough to expose a confident rule
                # mapping.  Keep the scored rule visible as borderline when the
                # deterministic criterion cannot ground it in the narrative;
                # this prevents contextual collisions such as maintenance
                # language being shown as Hot Work without inventing a keyword
                # suppression list.
                status = "BORDERLINE"; reason = "NO_EXTRACTABLE_SUPPORT_FOR_CONFIDENT_ASSIGNMENT"; borderline.append(rule_id)
            elif score >= borderline_threshold:
                status = "BORDERLINE"; reason = "MODEL_SCORE_IN_BORDERLINE_BAND"; borderline.append(rule_id)
            else:
                status = "BELOW_THRESHOLD"; reason = "MODEL_SCORE_BELOW_ASSIGNMENT_THRESHOLD"
            violation = "ESTABLISHED" if excerpt and re.search(VIOLATION_PATTERNS[rule_id], excerpt, re.I) else "NOT_ESTABLISHED"
            evidence = [{"excerpt": excerpt, "source": "submitted_narrative", "evidence_type": "criterion_aligned_sentence"}] if excerpt else []
            if status == "ASSIGNED" and excerpt:
                explanation = f"{name} is relevant. Supporting report excerpt: “{excerpt}”"
            elif status == "BORDERLINE":
                explanation = f"{name} is possible but below its assignment threshold; this does not prove the rule is irrelevant."
            else:
                explanation = f"{name} was assessed below its assignment threshold; this does not prove the rule is irrelevant."
            rules.append({"rule_id": rule_id, "name": name, "score": round(score, 6), "score_type": "uncalibrated_model_score", "assignment_threshold": threshold, "borderline_threshold": borderline_threshold, "assignment_status": status, "reason_code": reason, "evidence": evidence, "violation_status": violation, "rendered_explanation": explanation})
        word_count = len(re.findall(r"\b\w+\b", text))
        insufficient = word_count < 14 and not any(_supported_excerpt(text, rule_id) for rule_id in RULE_PATTERNS)
        if assigned:
            mapping_status, reason_code = "MAPPED", "ONE_OR_MORE_CONFIDENT_MAPPINGS"
        elif unavailable:
            mapping_status, reason_code = "MAPPING_UNAVAILABLE", "ONE_OR_MORE_RULE_CLASSIFIERS_UNAVAILABLE"
        elif insufficient:
            mapping_status, reason_code = "INSUFFICIENT_INFORMATION", "NARRATIVE_LACKS_ASSESSABLE_RULE_DETAIL"
        elif borderline:
            mapping_status, reason_code = "BORDERLINE_MAPPING", "ONE_OR_MORE_RULES_IN_BORDERLINE_BAND"
        else:
            mapping_status, reason_code = "NO_CONFIDENT_MAPPING", "ALL_AVAILABLE_RULE_SCORES_BELOW_ASSIGNMENT_THRESHOLDS"
        if assigned:
            rendered = f"Mapped {len(assigned)} IOGP Life-Saving Rule(s). Excerpts are supporting evidence, not a complete account of model reasoning."
        elif mapping_status == "MAPPING_UNAVAILABLE":
            rendered = "No confident mapping is shown because one or more rule classifiers are unavailable; unavailable rules are not treated as negatives."
        elif mapping_status == "INSUFFICIENT_INFORMATION":
            rendered = "The narrative lacks enough criterion-specific detail for a complete rule assessment."
        elif mapping_status == "BORDERLINE_MAPPING":
            rendered = "No rule met its assignment threshold; one or more available rules remain borderline."
        else:
            rendered = "All available rule scores are below their assignment thresholds; this does not prove that no rule applies."
        return {"schema_version": "sif-lsr-analysis-v1", "mapping_status": mapping_status, "reason_code": reason_code, "rendered_explanation": rendered, "assigned_rule_ids": assigned, "borderline_rule_ids": borderline, "unavailable_rule_ids": unavailable, "coverage_complete": not unavailable, "rules": rules, "status_precedence": STATUS_PRECEDENCE, "reference_id": self.lsr["reference"]["reference_id"], "model_version": self.lsr["version"], "artifact_hash": self.artifact_hash, "timings_ms": {"preprocessing_and_scoring": round(preprocessing_ms, 4), "evidence_and_templates": round((time.perf_counter() - started) * 1000, 4)}}

    def _unavailable_mapping(self, reason: str) -> dict[str, Any]:
        return {"schema_version": "sif-lsr-analysis-v1", "mapping_status": "MAPPING_UNAVAILABLE", "reason_code": "MODEL_REFERENCE_OR_PROCESSING_FAILURE", "rendered_explanation": "IOGP mapping is unavailable because the model, reference, or processing step failed.", "assigned_rule_ids": [], "borderline_rule_ids": [], "unavailable_rule_ids": [f"LSR{number:02d}" for number in range(1, 10)], "coverage_complete": False, "rules": [], "status_precedence": STATUS_PRECEDENCE, "reference_id": None, "model_version": None, "artifact_hash": None, "failure_reason": reason, "timings_ms": {"preprocessing_and_scoring": 0.0, "evidence_and_templates": 0.0}}


_SERVICE = DomainSafetyModel()


def get_domain_model() -> DomainSafetyModel:
    return _SERVICE
