from __future__ import annotations

import re
from typing import Any

RULES = {
    "Energy Isolation": ["isolation", "stored pressure", "energized", "electrical", "lockout", "depressuris", "live line", "pressure"],
    "Line of Fire": ["line of fire", "release path", "struck", "pinch point", "between", "flange", "suspended load"],
    "Working at Height": ["height", "scaffold", "fall protection", "harness", "ladder", "platform edge"],
    "Safe Mechanical Lifting": ["lifting", "crane", "hoist", "sling", "load", "rigging", "suspended"],
    "Driving": ["vehicle", "revers", "blind spot", "forklift", "collision", "traffic", "driving"],
    "Confined Space": ["confined", "toxic", "atmosphere", "gas test", "entry permit"],
    "Hot Work": ["hot work", "spark", "ignition", "flammable", "welding", "fire"],
    "Work Authorisation": ["permit", "authorization", "work authorisation", "work authorization", "permit to work"],
    "Bypassing Safety Controls": ["procedure bypass", "control bypass", "override", "disabling safety", "crossing a barrier"],
}
HAZARDS = {
    "stored energy": ["pressure", "energized", "stored energy", "hydraulic"],
    "line-of-fire exposure": ["release path", "line of fire", "flange", "pinch", "suspended"],
    "mechanical lifting": ["lifting", "crane", "load", "sling", "hoist"],
    "fall exposure": ["height", "scaffold", "harness", "ladder"],
    "vehicle movement": ["vehicle", "revers", "blind spot", "forklift"],
    "toxic atmosphere": ["toxic", "gas", "confined"],
    "fire/explosion": ["flammable", "ignition", "fire", "hot work"],
}
ACTIVITIES = {
    "Valve Maintenance": ["valve maintenance", "process valve", "maintenance", "repair", "turnaround"],
    "Mechanical Lifting": ["lifting", "crane", "hoist", "rigging", "sling", "suspended load"],
    "Drilling": ["drilling", "drill floor", "well intervention", "rig floor"],
    "Driving": ["driving", "vehicle", "forklift", "traffic", "revers"],
    "Hot Work": ["hot work", "welding", "cutting", "grinding"],
    "Pressure Testing": ["pressure test", "hydrotest", "pneumatic test", "pressuriz"],
    "Electrical Maintenance": ["electrical maintenance", "electrical", "wiring", "control panel", "power source"],
    "Inspection": ["inspection", "inspected", "walkdown"],
}
BARRIER_FAILURES = {
    "isolation / control verification failure": ["not been completely", "not completely isolated", "incomplete", "not verified", "isolation failure", "isolation gap", "without isolation"],
    "permit or authorization control failure": ["permit bypass", "permit violation", "permit missing", "without a permit", "no permit", "authorization failure", "procedure bypass", "control bypass"],
    "line-of-fire exclusion failure": ["exclusion failure", "barrier failure", "no exclusion zone", "without an exclusion zone"],
    "fall-protection control failure": ["without harness", "fall protection absent", "unprotected edge", "no fall protection"],
}

BARRIER_CANDIDATES = {
    "isolation / control verification failure": ["isolation", "lockout", "zero energy"],
    "permit or authorization control failure": ["permit", "authorization", "authorisation"],
    "line-of-fire exclusion failure": ["release path", "line of fire", "pinch point", "suspended load"],
    "fall-protection control failure": ["harness", "fall protection", "unprotected edge"],
}

def _hits(text: str, terms: list[str]) -> list[str]: return [t for t in terms if t in text.lower()]

def _location(text: str) -> str | None:
    match = re.search(r"\b(?:at|in|on)\s+((?:site|facility|plant|yard|platform|rig|station|terminal)\s+[a-z0-9][a-z0-9 ._-]{0,50})", text, re.I)
    return match.group(1).strip(" .,") if match else None

def analyze_text(narrative: str) -> dict[str, Any]:
    if not narrative or len(narrative.strip()) < 12: raise ValueError("Provide a report narrative of at least 12 characters.")
    text=narrative.lower(); rule_scores=[]
    for rule,terms in RULES.items():
        found=_hits(text,terms)
        if found: rule_scores.append((rule,min(.96,.48+.12*len(found)),found))
    rule_scores.sort(key=lambda r:r[1],reverse=True)
    hazards=[name for name,terms in HAZARDS.items() if _hits(text,terms)]
    high_cues=_hits(text,["stored pressure","pressure","energized","suspended","height","toxic","flammable","release path","flange","critical control","bypass"])
    exposure=_hits(text,["worker","technician","standing","within","under","near","occupied"])
    failures=_hits(text,["not been completely","not completely isolated","incomplete","failed","bypass","missing","without","not verified","deviation"])
    score=.08+.095*min(5,len(high_cues))+.07*min(3,len(exposure))+.1*min(3,len(failures))
    if any(x in text for x in ["released","fell","struck","contact","collapse"]): score+=.15
    if any(x in text for x in ["housekeeping","paper","minor","cleaned"]): score-=.16
    probability=round(max(.03,min(.97,score)),2); risk="High" if probability>=.65 else "Medium" if probability>=.35 else "Low"
    cue_text={"stored pressure":"stored pressure is described","pressure":"pressure exposure is described","release path":"a person is in a potential release path","not been completely":"isolation appears incomplete","not completely isolated":"isolation appears incomplete","incomplete":"a control is described as incomplete","suspended":"suspended-load exposure is described","height":"work at height is described","energized":"hazardous energy may be present"}
    evidence=[cue_text[t] for t in dict.fromkeys(high_cues+failures) if t in cue_text]
    precursors=[]
    isolation_failure = any(x in text for x in ["not been completely", "not completely isolated", "isolation failure", "isolation gap", "without isolation", "not verified", "incomplete isolation"])
    permit_failure = any(x in text for x in ["permit bypass", "permit violation", "permit missing", "without a permit", "no permit", "authorization failure", "procedure bypass", "control bypass"])
    if isolation_failure: precursors.append("isolation verification gap")
    if any(x in text for x in ["release path","flange","suspended","pinch"]): precursors.append("line-of-fire exposure")
    if permit_failure: precursors.append("permit or critical-control deviation")
    if any(x in text for x in ["vehicle", "driver", "driving"]) and any(x in text for x in ["speeding", "revers", "collision", "pedestrian", "spotter"]): precursors.append("vehicle separation gap")
    if any(x in text for x in ["crane", "hoist", "sling", "rigging", "suspended load"]) and any(x in text for x in ["dropped", "dropped", "swung", "slipped", "load path"]): precursors.append("lifting exclusion gap")
    if any(x in text for x in ["welding", "torch", "hot work", "flammable"]) and any(x in text for x in ["gas test", "vapour", "ignition"]): precursors.append("hot-work control deviation")
    if any(x in text for x in ["height", "platform", "scaffold", "ladder"]) and any(x in text for x in ["fall protection", "harness", "unprotected", "edge"]): precursors.append("fall-protection gap")
    if "confined space" in text and any(x in text for x in ["attendant", "gas test", "rescue plan", "entry"]): precursors.append("confined-space entry gap")
    if any(x in text for x in ["guard", "interlock", "bypass"]): precursors.append("safeguard bypass concern")
    activity=next((name for name,terms in ACTIVITIES.items() if _hits(text,terms)),"Unclassified")
    barrier_failures=[name for name,terms in BARRIER_FAILURES.items() if _hits(text,terms)]
    barrier_candidates=[name for name,terms in BARRIER_CANDIDATES.items() if _hits(text,terms) and name not in barrier_failures]
    if probability >= .65:
        classification, sif_potential = "SIF Potential", True
    elif probability < .35:
        classification, sif_potential = "Non-SIF Potential", False
    else:
        classification, sif_potential = "Needs Review", None
    if barrier_candidates:
        evidence.extend(f"Candidate control topic (not an asserted failure): {candidate}" for candidate in barrier_candidates)
    return {"sif_probability":probability,"risk":risk,"classification":classification,"classification_basis":"Rules threshold; not a calibrated probability.","model_mode":"Transparent Rules Engine","model_version":"rules-v1.0","evidence":evidence or ["No strong SIF precursor language detected; human review remains available."],"evidence_note":"These are textual signals, not proof of causation.","rules":{"primary":{"rule":rule_scores[0][0],"confidence":round(rule_scores[0][1],2)} if rule_scores else None,"secondary":[{"rule":r,"confidence":round(c,2)} for r,c,_ in rule_scores[1:3]]},"activity":activity,"location":_location(narrative),"hazards":hazards or ["not classified"],"precursors":precursors or ["no strong precursor pattern"],"barrier_failures":barrier_failures,"barrier_candidates":barrier_candidates,"priority":"Immediate review" if probability>=.65 else "Review" if probability>=.35 else "Monitor","review_required":probability>=.35,"high_potential":None,"sif_potential":sif_potential,"sif_label_status":"rules_classified" if sif_potential is not None else "unresolved"}
