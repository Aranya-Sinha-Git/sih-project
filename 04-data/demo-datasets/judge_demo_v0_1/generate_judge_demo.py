"""Generate the synthetic judge demonstration corpus.

This module deliberately keeps scenario design separate from the upload schema.
The upload contains only source-labelled report fields; QA and runtime profile
files may contain design and observed-coverage metadata for demonstration QA.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2].parent
OUT_DIR = Path(__file__).resolve().parent
BACKEND = ROOT / "01-app" / "backend"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{OUT_DIR / '.profile_only.db'}")
sys.path.insert(0, str(BACKEND))

from app.main import AnalyzeInput, analyzed_results, normalize_report_date, trends  # noqa: E402
from app.services.classifier import classifier_metadata, get_classifier  # noqa: E402
from app.services.domain_model import get_domain_model  # noqa: E402
from app.services.engine import analyze_text  # noqa: E402

GENERATOR_VERSION = "judge_demo_generator_v0.1"
SEED = 26165
CORPUS_VERSION = "synthetic_judge_demo_v0_1"
START_WEEK = date(2026, 7, 20)

UPLOAD_COLUMNS = ["report_id", "report_date", "site", "activity", "report_type", "narrative", "source"]
WEEK_COUNTS = [50, 55, 55, 60, 65, 70, 70, 75]
REPORT_TYPE_COUNTS = {"Near Miss": 180, "Unsafe Condition": 130, "Incident": 100, "Unsafe Act": 90}
SITE_COUNTS = {
    "Aurora Basin": 100,
    "Blue Mesa Yard": 90,
    "Cedar Ridge Station": 85,
    "Delta Point Facility": 80,
    "Echo Valley Works": 75,
    "Frostline Depot": 70,
}
ACTIVITY_COUNTS = {
    "Valve Maintenance": 90,
    "Mechanical Lifting": 75,
    "Drilling": 65,
    "Pressure Testing": 60,
    "Driving": 60,
    "Hot Work": 55,
    "Inspection": 50,
    "Electrical Maintenance": 45,
}
SCENARIO_COUNTS = {
    "Energy isolation": 65,
    "Line of fire": 60,
    "Mechanical lifting": 55,
    "Driving": 50,
    "Hot work": 50,
    "Working at height": 45,
    "Confined space": 35,
    "Work authorization": 35,
    "Bypassed safety controls": 25,
    "Routine work": 80,
}
SCENARIO_LSR = {
    "Energy isolation": "LSR04",
    "Line of fire": "LSR06",
    "Mechanical lifting": "LSR07",
    "Driving": "LSR03",
    "Hot work": "LSR05",
    "Working at height": "LSR09",
    "Confined space": "LSR02",
    "Work authorization": "LSR08",
    "Bypassed safety controls": "LSR01",
    "Routine work": None,
}

SITE_WEEK_MATRIX = {
    "Aurora Basin": [5, 6, 7, 8, 10, 18, 21, 25],
    "Blue Mesa Yard": [5, 6, 7, 8, 9, 16, 19, 20],
    "Cedar Ridge Station": [10, 11, 11, 11, 12, 11, 10, 9],
    "Delta Point Facility": [10, 10, 10, 11, 11, 10, 9, 9],
    "Echo Valley Works": [8, 10, 10, 12, 14, 8, 5, 8],
    "Frostline Depot": [12, 12, 10, 10, 9, 7, 6, 4],
}

SCENARIO_SPEC = {
    "Energy isolation": {"area": "valve gallery", "equipment": "process valve and stored-pressure line", "control": "lockout, drain, and zero-energy verification", "high_event": "a technician loosened the flange while the isolation was not completely verified", "high_exposure": "the technician stood in the pressure release path", "medium_event": "the isolation status was uncertain while a technician prepared the flange", "medium_exposure": "the technician remained near the potential release path", "secondary": "a pressure gauge was checked before the work boundary was reset"},
    "Line of fire": {"area": "pipe rack laydown area", "equipment": "pipe spool and temporary lifting frame", "control": "exclusion zone, tag line, and hands-off positioning", "high_event": "the spool swung when the tag line slipped", "high_exposure": "a rigger stood in the line of fire beside the load path", "medium_event": "the load path shifted and the separation status was uncertain", "medium_exposure": "a rigger remained close to the potential release path", "secondary": "a small hand tool was moved outside the marked boundary"},
    "Mechanical lifting": {"area": "lifting pad", "equipment": "crane, sling, and suspended load", "control": "lift plan, inspected rigging, and exclusion zone", "high_event": "the sling slipped and the load dropped a short distance", "high_exposure": "the rigger was under or beside the suspended load", "medium_event": "the sling condition and load stability were not fully confirmed", "medium_exposure": "the rigger worked near the suspended-load path", "secondary": "the tag line was repositioned before the next lift"},
    "Driving": {"area": "internal access road", "equipment": "light vehicle and reversing camera", "control": "seatbelt, spotter, speed limit, and journey plan", "high_event": "the vehicle reversed quickly and veered toward a pedestrian route", "high_exposure": "a pedestrian was within the vehicle line of travel", "medium_event": "the route and spotter status were uncertain during a reversing manoeuvre", "medium_exposure": "a driver remained close to the pedestrian separation line", "secondary": "a parked trolley was moved clear of the marked route"},
    "Hot work": {"area": "fabrication bay", "equipment": "welding torch, gas cylinder, and nearby vapour source", "control": "permit, gas test, fire watch, and ignition-source control", "high_event": "welding started before the gas test was complete and a flammable vapour was observed", "high_exposure": "the welder was beside the potential fire and explosion path", "medium_event": "the gas test status and ignition controls were not fully confirmed", "medium_exposure": "the welder remained near the possible vapour path", "secondary": "a portable grinder was isolated before the bay was cleared"},
    "Working at height": {"area": "maintenance platform", "equipment": "access ladder, scaffold, and fall-protection lanyard", "control": "guardrail, harness, lanyard, and tie-off point", "high_event": "the worker approached an unprotected platform edge without fall protection", "high_exposure": "the worker was positioned at height above the lower deck", "medium_event": "the edge protection and tie-off status were not fully confirmed", "medium_exposure": "the worker remained near the platform edge", "secondary": "a hand tool was lowered to the ground before access resumed"},
    "Confined space": {"area": "vessel entry station", "equipment": "isolated vessel, gas monitor, and ventilation fan", "control": "entry permit, gas test, attendant, and rescue plan", "high_event": "a worker approached the confined space without a completed gas test or attendant", "high_exposure": "the entrant was at the vessel opening with a possible toxic atmosphere", "medium_event": "the entry authorization and atmosphere status were not fully confirmed", "medium_exposure": "the entrant remained near the vessel opening", "secondary": "a portable electrical lead was kept outside the entry boundary"},
    "Work authorization": {"area": "tie-in work front", "equipment": "work package, permit board, and process line", "control": "valid permit, scope check, and authorization handover", "high_event": "work began without a valid permit after the scope changed", "high_exposure": "the technician was at the work front while conditions were not authorized", "medium_event": "the permit status and changed conditions were not fully confirmed", "medium_exposure": "the technician remained at the boundary awaiting authorization", "secondary": "a hand tool was returned to the staging bench"},
    "Bypassed safety controls": {"area": "test stand", "equipment": "guarded drive, interlock, and control panel", "control": "guard, interlock, test procedure, and stop control", "high_event": "the guard interlock was bypassed during a functional test", "high_exposure": "the operator stood beside the moving-part zone", "medium_event": "the interlock status and test boundary were not fully confirmed", "medium_exposure": "the operator remained near the guarded equipment", "secondary": "a small tool was removed from the test stand before restart"},
    "Routine work": {"area": "workshop aisle", "equipment": "hand tool, bench, and disconnected source", "control": "housekeeping, ordinary footing, and task check", "high_event": "a minor obstruction was left beside the walking route during a routine check", "high_exposure": "a worker walked close to the obstruction", "medium_event": "the housekeeping status was not fully confirmed during a routine check", "medium_exposure": "a worker remained near the ordinary walking route", "secondary": "a loose label was replaced on a stored tool"},
}

LOW_OPENERS = [
    "a worker slipped on a dry step while walking beside the bench, lost balance, and rolled an ankle",
    "a worker tripped over a small item while walking, caught a finger on the case, and recovered",
    "a worker slipped while walking, checked the ankle, and did not fall",
]
MEDIUM_OPENERS = [
    "the worker paused after noticing that the task status was not fully confirmed",
    "the worker remained at the boundary while the control status was checked",
    "the worker noticed a change during the task and held position for clarification",
]

HIGH_TRIGGERS = {
    "Energy isolation": "Stored pressure was not completely isolated.",
    "Line of fire": "A suspended load fell and struck a worker.",
    "Mechanical lifting": "The crane, hoist, and rigging failed while the load was lifted. A suspended load fell and struck a worker.",
    "Driving": "The driver was distracted and the vehicle veered toward a pedestrian. A vehicle crash was narrowly avoided.",
    "Hot work": "Welding started near flammable gas before the ignition source was controlled.",
    "Working at height": "The worker was working at height without fall protection, harness, or lanyard.",
    "Confined space": "The confined space entry began without a gas test, attendant, or rescue plan.",
    "Work authorization": "Work began without a valid permit after the authorization changed.",
    "Bypassed safety controls": "The guard interlock was bypassed and the safety control was disabled.",
    "Routine work": "A routine task continued after a minor control deviation was observed.",
}

SUPPORTED_SCENARIOS_FOR_HIGH_COVERAGE = ["Driving", "Energy isolation", "Hot work", "Line of fire", "Mechanical lifting", "Working at height"]

LOW_SAFE_EQUIPMENT = {
    "Energy isolation": "a closed pressure valve and disconnected line",
    "Line of fire": "a parked load and marked floor",
    "Mechanical lifting": "a parked load and inspected sling",
    "Driving": "a parked vehicle and clear route",
    "Hot work": "a cool hot-work torch and closed cylinder",
    "Working at height": "a secured ladder and closed platform",
    "Confined space": "a closed vessel and idle gas monitor",
    "Work authorization": "a checked permit board and hand tool",
    "Bypassed safety controls": "a secured guard and idle control panel",
    "Routine work": "a hand tool and parked vehicle",
}

TARGET_DECISIONS = {"high": "SIF_POTENTIAL", "medium": "HUMAN_REVIEW", "low": "NON_SIF_POTENTIAL"}
MAPPING_BOOSTS = {
    "Driving": ["The vehicle was speeding and the driver lost control.", "The driver was distracted and the vehicle veered toward a pedestrian."],
    "Mechanical lifting": ["The crane, hoist, and rigging failed while the load was lifted.", "A suspended load fell and struck a worker."],
}


def _pool(mapping: dict[str, int], rng: random.Random) -> list[str]:
    values = [key for key, count in mapping.items() for _ in range(count)]
    rng.shuffle(values)
    return values


def _site_dates(rng: random.Random) -> list[tuple[str, date]]:
    pairs = [(site, START_WEEK + timedelta(days=7 * week + ((week + slot) % 5))) for site, counts in SITE_WEEK_MATRIX.items() for week, count in enumerate(counts) for slot in range(count)]
    rng.shuffle(pairs)
    return pairs


def _secondary_text(spec: dict[str, str], mode: str) -> str:
    if mode == "high":
        return f"A secondary check also covered this area, and {spec['secondary']} before work stopped."
    return f"A secondary check covered the nearby area, and {spec['secondary']} before work continued."


def _narrative(site: str, activity: str, scenario: str, mode: str, variant: int, secondary: str | None) -> str:
    spec = SCENARIO_SPEC[scenario]
    role = ["technician", "operator", "inspector", "rigger", "driver", "supervisor"][variant % 6]
    stage = ["pre-job setup", "isolation check", "equipment positioning", "task execution", "post-task check"][variant % 5]
    if mode == "high":
        trigger = HIGH_TRIGGERS[scenario]
        sentences = [
            f"At {site} in the {spec['area']}, the {role} prepared {activity.lower()} during the {stage} stage.",
            f"The equipment was {spec['equipment']}.",
            trigger,
            f"{spec['high_exposure']}.",
            f"The expected {spec['control']} was not verified.",
            "No serious injury occurred, but severe harm was credible.",
            "Work stopped, the control was restored, and the event was recorded.",
        ]
    elif mode == "medium":
        sentences = [
            f"At {site} in the {spec['area']}, the {role} prepared {activity.lower()} during the {stage} stage.",
            f"The work involved the {spec['equipment']}, but the active energy or movement status was not fully clear.",
            f"{spec['medium_event'].capitalize()} and {MEDIUM_OPENERS[variant % len(MEDIUM_OPENERS)]}.",
            f"{spec['medium_exposure']}, although no contact or release occurred.",
            f"The expected {spec['control']} was referenced, but the available evidence was incomplete or uncertain.",
            "The immediate outcome was a stopped or delayed task, with a credible serious consequence still requiring qualified review.",
            f"The supervisor paused work, requested verification, and recorded the observation at {site}.",
        ]
    else:
        sentences = [
            f"At {site} in the workshop aisle, during routine inspection, a worker used a small hand tool.",
            f"Nearby was {LOW_SAFE_EQUIPMENT[scenario]}, not in use.",
            "The worker slipped on a dry step while walking beside the bench, lost balance, and rolled an ankle.",
            "The worker caught a finger on the tool case but did not fall.",
            "No one was exposed to serious harm and no credible fatal outcome was identified.",
            "The ordinary footing control was present and verified.",
            "The ankle and finger were checked after the slip.",
            "The fingertip was checked.",
            "The worker removed the step and continued.",
        ]
    if secondary and mode == "high":
        sentences.insert(5, _secondary_text(spec, mode))
    text = " ".join(sentences)
    words = len(re.findall(r"\b\w+[\w/-]*\b", text))
    if words < 70:
        text += " The task status, work boundary, equipment condition, and immediate response were entered in the synthetic shift log for a complete demonstration record."
    return text


def _with_marker(text: str, index: int) -> str:
    return f"{text} Demo sequence {index:04d} was logged."


def _compact_lsr_narrative(site: str, activity: str, scenario: str, variant: int) -> str:
    spec = SCENARIO_SPEC[scenario]
    role = ["technician", "operator", "inspector", "rigger", "driver", "supervisor"][variant % 6]
    stage = ["setup", "verification", "positioning", "execution", "closeout"][variant % 5]
    scenario_activity = {"Driving": "driving", "Mechanical lifting": "mechanical lifting"}[scenario]
    return " ".join([
        f"At {site} in the {spec['area']}, the {role} prepared {scenario_activity} during {stage}.",
        f"The equipment was {spec['equipment']}.",
        " ".join(MAPPING_BOOSTS[scenario]),
        f"{spec['high_exposure']}.",
        f"The expected {spec['control']} was not verified.",
        "No serious injury occurred, but severe harm was credible.",
        "Work stopped, the control was restored, and the event was recorded.",
    ])


def _select_narrative(site: str, activity: str, scenario: str, mode: str, variant: int, secondary: str | None, index: int) -> str:
    """Select deterministic text that lands in the requested deployed band.

    The classifier is used only as a presentation-coverage constraint.  Its
    output is never written to the upload file; runtime observations remain in
    the QA/profile sidecars.
    """
    target = TARGET_DECISIONS[mode]
    candidates = [_with_marker(_narrative(site, activity, scenario, mode, variant + offset, secondary), index) for offset in range(6)]
    if mode == "high" and scenario in MAPPING_BOOSTS:
        base_candidates = list(candidates)
        for base in base_candidates:
            for boost in MAPPING_BOOSTS[scenario]:
                candidates.append(_with_marker(base + " " + boost, index))
        candidates.append(_with_marker(_compact_lsr_narrative(site, activity, scenario, variant), index))
        candidates.append(_with_marker(_compact_lsr_narrative(site, activity, scenario, variant + 1), index))
    if mode == "medium":
        low = _narrative(site, activity, scenario, "low", variant, secondary)
        candidates.extend([
            _with_marker(low + " The task was paused for a control check.", index),
            _with_marker(low + " The control status was uncertain and the supervisor paused the task.", index),
            _with_marker(low + " The barrier was reviewed before the task continued.", index),
            _with_marker(low + " The area was checked before work continued.", index),
            _with_marker(low + " The area was checked before work continued. The task was paused for review.", index),
            _with_marker(low + " A pressure line was nearby but no source was connected.", index),
            _with_marker(low + " A vehicle was parked nearby and no movement occurred.", index),
            _with_marker(low + " A load was parked and no lifting occurred.", index),
            _with_marker(low + " A ladder was secured and no one approached the edge.", index),
            _with_marker(low + " A control question was raised before continuing.", index),
        ])
    if mode == "low":
        low = _narrative(site, activity, scenario, "low", variant, secondary)
        candidates.extend([
            _with_marker(low + " The small condition was cleaned away.", index),
            _with_marker(low + " The area was cleaned and the routine task continued.", index),
        ])
    classifier = get_classifier()
    required_lsr = SCENARIO_LSR.get(scenario)
    supported_lsr = set(get_domain_model().metadata().get("supported_rule_ids", []))
    for candidate in candidates:
        if classifier.screen(candidate).get("decision") != target:
            continue
        if mode == "high" and required_lsr in supported_lsr and required_lsr not in get_domain_model().map_rules(candidate).get("assigned_rule_ids", []):
            continue
        if classifier.screen(candidate).get("decision") == target:
            return candidate
    observed = [(classifier.screen(candidate).get("decision"), round(float(classifier.screen(candidate).get("sif_score") or 0), 4)) for candidate in candidates]
    raise AssertionError(f"No {mode} narrative candidate for {scenario}/{site}: {observed}")


def _make_rows() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rng = random.Random(SEED)
    scenarios = _pool(SCENARIO_COUNTS, rng)
    required: list[str] = []
    for scenario in SUPPORTED_SCENARIOS_FOR_HIGH_COVERAGE:
        for _ in range(10):
            required.append(scenario)
            scenarios.remove(scenario)
    rng.shuffle(scenarios)
    scenarios = required + scenarios
    sites_dates = _site_dates(rng)
    activities = _pool(ACTIVITY_COUNTS, rng)
    report_types = _pool(REPORT_TYPE_COUNTS, rng)
    rows: list[dict[str, str]] = []
    qa: list[dict[str, Any]] = []
    for index, (scenario, (site, report_date), activity, report_type) in enumerate(zip(scenarios, sites_dates, activities, report_types), start=1):
        secondary = None
        if index % 4 == 0:
            choices = [name for name in SCENARIO_COUNTS if name != scenario]
            secondary = choices[(index + rng.randrange(len(choices))) % len(choices)]
        mode = "high" if index <= 160 else "medium" if index <= 280 else "low"
        variant = (index * 17 + rng.randrange(31)) % 12
        narrative = _select_narrative(site, activity, scenario, mode, variant, secondary, index)
        normalized = " ".join(narrative.casefold().split())
        rows.append({"report_id": f"DEMO500-{index:04d}", "report_date": normalize_report_date(report_date), "site": site, "activity": activity, "report_type": report_type, "narrative": narrative, "source": CORPUS_VERSION})
        qa.append({"report_id": f"DEMO500-{index:04d}", "scenario_family": scenario, "primary_lsr_design": SCENARIO_LSR[scenario] or "none", "secondary_scenario_design": secondary or "none", "cohort_id": f"{scenario.casefold().replace(' ', '_')}-cohort-{variant % 2 + 1}", "control_state_design": mode, "site_trend_design": {"Aurora Basin": "rising", "Blue Mesa Yard": "rising", "Cedar Ridge Station": "stable", "Delta Point Facility": "stable", "Echo Valley Works": "declining", "Frostline Depot": "declining"}[site], "word_count": len(re.findall(r"\b\w+[\w/-]*\b", narrative)), "normalized_narrative": normalized})
    return rows, qa


def _profile(rows: list[dict[str, str]], qa: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports = [AnalyzeInput.model_validate(row) for row in rows]
    started = time.perf_counter()
    analyses = analyzed_results(reports)
    elapsed = time.perf_counter() - started
    risks = Counter(analysis["risk"] for analysis in analyses)
    lsr_counts: Counter[str] = Counter()
    unavailable_examples: dict[str, str] = {}
    precursor_sites: defaultdict[str, set[str]] = defaultdict(set)
    meaningful = 0
    for row, analysis in zip(rows, analyses):
        mapping = analysis.get("lsr_mapping") or {}
        for rule_id in mapping.get("assigned_rule_ids", []):
            lsr_counts[rule_id] += 1
        for rule_id in mapping.get("unavailable_rule_ids", []):
            unavailable_examples.setdefault(rule_id, row["report_id"])
        for precursor in analysis.get("precursors", []):
            if precursor != "no strong precursor pattern":
                precursor_sites[precursor].add(row["site"])
        engine = analyze_text(row["narrative"])
        if engine.get("hazards") != ["not classified"] or engine.get("precursors") != ["no strong precursor pattern"] or engine.get("barrier_failures") or engine.get("barrier_candidates"):
            meaningful += 1
    for item, analysis in zip(qa, analyses):
        item["observed_risk"] = analysis["risk"]
        item["observed_sif_decision"] = (analysis.get("screening") or {}).get("decision")
        item["observed_assigned_lsr_ids"] = (analysis.get("lsr_mapping") or {}).get("assigned_rule_ids", [])
        item["observed_unavailable_rule_ids"] = (analysis.get("lsr_mapping") or {}).get("unavailable_rule_ids", [])
        item["meaningful_hazard_extraction"] = bool(item["observed_assigned_lsr_ids"] or item["observed_unavailable_rule_ids"] or item["scenario_family"] == "Routine work" or item["observed_risk"] in {"High", "Medium"})
    metadata = classifier_metadata()
    domain_metadata = get_domain_model().metadata()
    trend_rows = [{"report_date": row["report_date"], "risk": analysis["risk"], "review_status": "Pending" if analysis["review_required"] else "Not required"} for row, analysis in zip(rows, analyses)]
    trend_points = trends(trend_rows)
    cohort_counts = Counter(item["cohort_id"] for item in qa)
    major_scenarios = {name: sum(1 for item in qa if item["scenario_family"] == name) for name in SCENARIO_COUNTS}
    clusters = [{"name": name, "report_count": sum(1 for item, analysis in zip(rows, analyses) if name in analysis.get("precursors", [])), "site_count": len(sites)} for name, sites in precursor_sites.items() if len(sites) >= 3]
    observed = {
        "risk_distribution": {key: risks.get(key, 0) for key in ("High", "Medium", "Low")},
        "risk_percentages": {key: round(100 * risks.get(key, 0) / len(rows), 1) for key in ("High", "Medium", "Low")},
        "supported_lsr_assignments": dict(sorted(lsr_counts.items())),
        "unavailable_lsr_rule_ids": domain_metadata.get("unavailable_rule_ids", []),
        "unavailable_lsr_examples": unavailable_examples,
        "recurring_precursor_clusters": sorted(clusters, key=lambda x: x["report_count"], reverse=True),
        "related_nonduplicate_cohorts": {name: min(cohort_counts.get(f"{name.casefold().replace(' ', '_')}-cohort-{n}", 0) for n in range(1, 3)) for name in SCENARIO_COUNTS},
        "scenario_counts": major_scenarios,
        "meaningful_hazard_extraction_count": meaningful,
        "meaningful_hazard_extraction_percentage": round(100 * meaningful / len(rows), 1),
        "normalized_narrative_site_duplicates": len(rows) - len({(item["normalized_narrative"], row["site"].casefold()) for row, item in zip(rows, qa)}),
        "trend_points": trend_points,
    }
    targets = {
        "high_percentage": [25, 45],
        "medium_percentage": [10, 25],
        "low_percentage": [35, 55],
        "minimum_supported_lsr_examples": 10,
        "minimum_recurring_clusters_spanning_three_sites": 3,
        "minimum_related_reports_per_major_scenario": 8,
        "minimum_meaningful_hazard_extraction_percentage": 90,
        "maximum_normalized_narrative_site_duplicates": 0,
        "maximum_profile_seconds": 30,
    }
    observed["profile_seconds"] = round(elapsed, 3)
    checks = {
        "risk_distribution": targets["high_percentage"][0] <= observed["risk_percentages"]["High"] <= targets["high_percentage"][1] and targets["medium_percentage"][0] <= observed["risk_percentages"]["Medium"] <= targets["medium_percentage"][1] and targets["low_percentage"][0] <= observed["risk_percentages"]["Low"] <= targets["low_percentage"][1],
        "supported_lsr_coverage": all(observed["supported_lsr_assignments"].get(rule_id, 0) >= targets["minimum_supported_lsr_examples"] for rule_id in domain_metadata.get("supported_rule_ids", [])),
        "unavailable_lsr_examples": all(rule_id in unavailable_examples for rule_id in domain_metadata.get("unavailable_rule_ids", [])),
        "recurring_clusters": len(observed["recurring_precursor_clusters"]) >= targets["minimum_recurring_clusters_spanning_three_sites"],
        "related_scenario_cohorts": all(value >= targets["minimum_related_reports_per_major_scenario"] for value in observed["related_nonduplicate_cohorts"].values()),
        "meaningful_hazard_extraction": observed["meaningful_hazard_extraction_percentage"] >= targets["minimum_meaningful_hazard_extraction_percentage"],
        "duplicate_check": observed["normalized_narrative_site_duplicates"] == 0,
        "profile_runtime": elapsed <= targets["maximum_profile_seconds"],
        "trend_coverage": all(point["high"] + point["reviews"] > 0 for point in trend_points),
    }
    profile = {
        "profile_version": "judge_demo_runtime_profile_v0.1",
        "corpus": CORPUS_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "row_count": len(rows),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "targets": targets,
        "observed": observed,
        "checks": checks,
        "active_artifacts": {"sif": metadata, "lsr": domain_metadata},
        "notes": ["Observed runtime categories are screening outputs used to exercise UI states, not ground-truth labels.", "Unavailable LSR rules are explicit coverage gaps and are not treated as negatives.", "Historical similarity is intentionally deferred to report-detail reads after the corpus is stored."],
    }
    return profile, qa


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_card(profile: dict[str, Any], rows: list[dict[str, str]]) -> None:
    observed = profile["observed"]
    dates = sorted(row["report_date"] for row in rows)
    text = f"""# Judge demo corpus v0.1

Status: synthetic presentation corpus (`{CORPUS_VERSION}`). This dataset is not a validation dataset and must not be used as accuracy, calibration, or external-validation evidence.

## Boundary

All 500 records are deterministic fictional demonstrations generated with seed `{SEED}` by `{GENERATOR_VERSION}`. They contain no real people, Oil India events, confidential records, or copied blind-test narratives. The frozen human-validation releases under `03-training/ml/sif_v0_1/data/blind_test_v0_2` and `blind_test_v0_3` are outside this directory and are not modified by the generator.

The upload files contain only `report_id`, `report_date`, `site`, `activity`, `report_type`, `narrative`, and `source`. They contain no precomputed predictions, AI labels, model scores, retrieval results, explanations, or reviewer fields. The QA matrix is a sidecar and must not be uploaded.

## Design quotas

- Reports: 500. Report IDs are stable from `DEMO500-0001` through `DEMO500-0500`.
- Report types: Near Miss 180, Unsafe Condition 130, Incident 100, Unsafe Act 90.
- Sites: Aurora Basin 100, Blue Mesa Yard 90, Cedar Ridge Station 85, Delta Point Facility 80, Echo Valley Works 75, Frostline Depot 70.
- Activities: Valve Maintenance 90, Mechanical Lifting 75, Drilling 65, Pressure Testing 60, Driving 60, Hot Work 55, Inspection 50, Electrical Maintenance 45.
- Weekly groups from `{dates[0]}` through `{dates[-1]}`: 50, 55, 55, 60, 65, 70, 70, 75.
- Primary scenario families include energy isolation 65, line of fire 60, mechanical lifting 55, driving 50, hot work 50, working at height 45, confined space 35, work authorization 35, bypassed safety controls 25, and routine work 80.
- Narrative length is designed for 70–140 words and normally seven or eight sentences. Every narrative names a fictional work area, task stage, equipment or energy source, observation, exposure position, expected barrier, barrier state, outcome or credible potential, and response.

## Runtime coverage

The generator profiles the finished narratives through the active deployed SIF classifier, active LSR mapper, and structured extraction path. The observed screening distribution is High {observed['risk_percentages']['High']}%, Medium/review {observed['risk_percentages']['Medium']}%, and Low {observed['risk_percentages']['Low']}%. These are presentation-coverage observations, not prevalence claims or labels.

The profile records supported-rule examples, explicit unavailable-rule examples, recurring precursor cohorts, related nonduplicate cohorts, extraction coverage, trend coverage, active artifact hashes, and timing. Similar-report retrieval is intentionally exercised after persistence on detail reads; the batch path does not scan the incomplete corpus once per row. Alerts remain empty unless a genuine data-derived alert policy is enabled.

The corpus was selected to exercise dashboard, six-week trend, site, activity, report-type, intelligence, multi-rule evidence, historical similarity, review queue, and model/evidence UI states. It is not representative of field prevalence.

## Rebuild and use

Run `python 04-data/demo-datasets/judge_demo_v0_1/generate_judge_demo.py`, then `node 04-data/demo-datasets/judge_demo_v0_1/build_judge_demo_xlsx.mjs`, and finally `python 04-data/demo-datasets/judge_demo_v0_1/finalize_judge_demo_manifest.py` to refresh the versioned artifacts. Verify `/ready`, use a clean demo workspace, and upload `judge_demo_500.xlsx`. The expected demonstration summary is 500 processed and 0 skipped on the first upload. A retry with the same stable IDs is expected to report duplicates rather than add another 500 records.
"""
    (OUT_DIR / "DATASET_CARD.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, qa = _make_rows()
    if len(rows) != 500:
        raise AssertionError(len(rows))
    profile, qa = _profile(rows, qa)
    _write_csv(OUT_DIR / "judge_demo_500.csv", rows, UPLOAD_COLUMNS)
    _write_csv(OUT_DIR / "judge_demo_smoke_25.csv", rows[:25], UPLOAD_COLUMNS)
    _write_csv(OUT_DIR / "judge_demo_qa_matrix.csv", qa, ["report_id", "scenario_family", "primary_lsr_design", "secondary_scenario_design", "cohort_id", "control_state_design", "site_trend_design", "word_count", "normalized_narrative", "observed_risk", "observed_sif_decision", "observed_assigned_lsr_ids", "observed_unavailable_rule_ids", "meaningful_hazard_extraction"])
    (OUT_DIR / "judge_demo_runtime_profile.json").write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_card(profile, rows)
    if profile["status"] != "PASS":
        raise SystemExit(f"Runtime coverage targets failed: {json.dumps(profile['checks'], sort_keys=True)}")
    print(json.dumps({"rows": len(rows), "profile_status": profile["status"], "risk_distribution": profile["observed"]["risk_distribution"], "profile_seconds": profile["observed"]["profile_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
