"""Deterministic explanation compatibility service.

The service intentionally performs no runtime generative-LLM or network
calls. The historical endpoint remains compatible and returns a template made
only from already-grounded evidence.
"""
from __future__ import annotations

from typing import Any


class LocalLLMService:
    prompt_version = "deterministic-evidence-template-v2"
    model = "none"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Retain constructor compatibility while ignoring former URL options.
        pass

    @property
    def configured(self) -> bool:
        return False

    def explain(self, narrative: str, screening: dict[str, Any], reference_evidence: list[dict[str, Any]], historical_evidence: list[dict[str, Any]], *, force: bool = False) -> dict[str, Any]:
        evidence = [*reference_evidence, *historical_evidence][:5]
        decision = str(screening.get("decision") or "UNKNOWN")
        if evidence:
            details = " ".join(
                f"[{item.get('evidence_id') or item.get('incident_id')}] {item.get('excerpt') or item.get('title') or 'No excerpt available.'}"
                for item in evidence
            )
            text = f"Screening decision: {decision}. Supporting retrieved evidence: {details}"
        else:
            text = f"Screening decision: {decision}. No supported retrieved evidence was located."
        return {
            "status": "deterministic",
            "completion_status": "completed",
            "text": text,
            "cited_evidence_ids": [item.get("evidence_id") or item.get("incident_id") for item in evidence],
            "failure_reason": None,
            "llm_model": None,
            "prompt_version": self.prompt_version,
            "latency_ms": 0,
            "cache_hit": False,
            "runtime_generative_llm_calls": False,
        }


_SERVICE = LocalLLMService()


def get_local_llm_service() -> LocalLLMService:
    return _SERVICE
