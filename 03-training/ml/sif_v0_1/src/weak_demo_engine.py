"""Transparent, unvalidated demonstration-only risk signals.

This module is deliberately separate from supervised inference.  Its score is not a
probability and must never be used for performance claims or operational approval.
"""
from __future__ import annotations

import re

SIGNAL_GROUPS = {
    "stored pressure": ("pressure", "pressur", "compressed gas", "hydraulic", "pneumatic", "blowout"),
    "electricity": ("electric", "energized", "live wire", "arc flash", "electrocution"),
    "suspended load": ("suspended load", "overhead load", "lifting", "crane", "rigging", "hoist"),
    "height": ("fall from height", "working at height", "ladder", "scaffold", "elevated"),
    "vehicle or moving equipment": ("forklift", "vehicle", "truck", "mobile equipment", "backing", "run over"),
    "fire or explosion": ("fire", "explosion", "ignition", "flammable", "burn"),
    "toxic atmosphere or confined space": ("confined space", "toxic gas", "hydrogen sulfide", "h2s", "asphyxi"),
    "moving machinery": ("rotating", "pinch point", "unguarded", "conveyor", "moving machinery"),
}
EXPOSURE_TERMS = ("worker", "employee", "personnel", "operator", "underneath", "beneath", "in the line of fire", "entered")
BARRIER_TERMS = ("not isolated", "isolation failure", "lockout", "bypassed", "missing guard", "no barricade", "no exclusion zone", "permit", "not verified")


def _present(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)


def score_text(text: object) -> dict:
    normalized = "" if text is None else str(text).lower()
    if not normalized.strip():
        return {"model_status": "WEAK_DEMO_UNVALIDATED", "demo_risk_score": 0.0, "decision": "HUMAN_REVIEW", "review_required": True, "signals": ["empty narrative"]}
    hazards = [name for name, terms in SIGNAL_GROUPS.items() if _present(normalized, terms)]
    exposure = _present(normalized, EXPOSURE_TERMS)
    barrier = _present(normalized, BARRIER_TERMS)
    # Hazard evidence is capped so repeated keywords cannot inflate the score indefinitely.
    score = min(0.60, 0.20 * len(hazards)) + (0.20 if exposure else 0.0) + (0.20 if barrier else 0.0)
    score = round(min(score, 1.0), 2)
    signals = hazards + (["personnel exposure"] if exposure else []) + (["barrier/control concern"] if barrier else [])
    if score >= 0.60:
        decision, review_required = "HIGH_DEMO_RISK", True
    elif score >= 0.25:
        decision, review_required = "HUMAN_REVIEW", True
    else:
        decision, review_required = "LOW_DEMO_SIGNAL", True
    return {"model_status": "WEAK_DEMO_UNVALIDATED", "demo_risk_score": score, "decision": decision, "review_required": review_required, "signals": signals or ["no configured high-energy signal"]}
