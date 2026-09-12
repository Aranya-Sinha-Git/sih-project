"""Build a standalone 100-report synthetic demonstration corpus.

The upload dataset contains report fields only. Design intent and observed
runtime behavior stay in sidecars so model output is never presented as a
human label or validation result.
"""
from __future__ import annotations

import csv
import importlib.util
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

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
BASE_PATH = OUT_DIR.parent / "judge_demo_v0_1" / "generate_judge_demo.py"
os.environ["DATABASE_URL"] = f"sqlite:///{OUT_DIR / '.profile_only.db'}"

spec = importlib.util.spec_from_file_location("judge_demo_500_generator", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load shared scenario generator: {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

GENERATOR_VERSION = "judge_demo_100_generator_v0.1"
CORPUS_VERSION = "synthetic_judge_demo_100_v0_1"
SEED = 27165
START_WEEK = date(2026, 7, 20)
UPLOAD_COLUMNS = ["report_id", "report_date", "site", "activity", "report_type", "narrative", "source"]

REPORT_TYPE_COUNTS = {"Near Miss": 36, "Unsafe Condition": 26, "Incident": 20, "Unsafe Act": 18}
ACTIVITY_COUNTS = {
    "Valve Maintenance": 18,
    "Mechanical Lifting": 15,
    "Drilling": 13,
    "Pressure Testing": 12,
    "Driving": 12,
    "Hot Work": 11,
    "Inspection": 10,
    "Electrical Maintenance": 9,
}
SCENARIO_COUNTS = {
    "Energy isolation": 13,
    "Line of fire": 12,
    "Mechanical lifting": 11,
    "Driving": 10,
    "Hot work": 10,
    "Working at height": 9,
    "Confined space": 7,
    "Work authorization": 7,
    "Bypassed safety controls": 5,
    "Routine work": 16,
}
SITE_WEEK_MATRIX = {
    "Granite Field Plant": [1, 1, 1, 2, 2, 4, 4, 5],
    "Harbor Ridge Terminal": [1, 1, 1, 2, 2, 3, 4, 4],
    "Juniper Well Pad": [2, 2, 2, 2, 3, 2, 2, 2],
    "Kestrel Compression Hub": [2, 2, 2, 2, 2, 2, 2, 2],
    "Lumen Maintenance Yard": [2, 2, 2, 2, 2, 2, 1, 2],
    "Nimbus Logistics Depot": [2, 3, 3, 2, 2, 1, 1, 0],
}
SITE_TRENDS = {
    "Granite Field Plant": "rising",
    "Harbor Ridge Terminal": "rising",
    "Juniper Well Pad": "stable",
    "Kestrel Compression Hub": "stable",
    "Lumen Maintenance Yard": "declining",
    "Nimbus Logistics Depot": "declining",
}
RISK_TARGETS = {"High": 32, "Medium": 24, "Low": 44}
SCENARIO_ACTIVITY_OPTIONS = {
    "Energy isolation": ["Valve Maintenance", "Pressure Testing", "Electrical Maintenance"],
    "Line of fire": ["Mechanical Lifting", "Drilling"],
    "Mechanical lifting": ["Mechanical Lifting"],
    "Driving": ["Driving"],
    "Hot work": ["Hot Work"],
    "Working at height": ["Inspection", "Valve Maintenance"],
    "Confined space": ["Inspection"],
    "Work authorization": ["Valve Maintenance", "Drilling"],
    "Bypassed safety controls": ["Electrical Maintenance"],
    "Routine work": ["Inspection"],
}


def _pool(counts: dict[str, int], rng: random.Random) -> list[str]:
    values = [name for name, count in counts.items() for _ in range(count)]
    rng.shuffle(values)
    return values


def _site_dates(rng: random.Random) -> list[tuple[str, date]]:
    values = [
        (site, START_WEEK + timedelta(days=7 * week + ((week + slot) % 5)))
        for site, weekly in SITE_WEEK_MATRIX.items()
        for week, count in enumerate(weekly)
        for slot in range(count)
    ]
    rng.shuffle(values)
    return values


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _make_rows() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rng = random.Random(SEED)
    source_rows = list(csv.DictReader((BASE_PATH.parent / "judge_demo_500.csv").open(encoding="utf-8")))
    source_qa = {row["report_id"]: row for row in csv.DictReader((BASE_PATH.parent / "judge_demo_qa_matrix.csv").open(encoding="utf-8"))}
    candidates = [{"row": row, "qa": source_qa[row["report_id"]]} for row in source_rows]
    rng.shuffle(candidates)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["row"]["report_id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["row"]["report_id"])

    supported = base.get_domain_model().metadata().get("supported_rule_ids", [])
    for rule_id in supported:
        matches = [
            item for item in candidates
            if item["qa"]["observed_risk"] == "High"
            and rule_id in item["qa"]["observed_assigned_lsr_ids"]
            and item["row"]["report_id"] not in selected_ids
        ]
        for item in matches[:5]:
            add(item)

    for scenario in base.SCENARIO_COUNTS:
        while sum(item["qa"]["scenario_family"] == scenario for item in selected) < 5:
            risk_counts = Counter(item["qa"]["observed_risk"] for item in selected)
            matches = [
                item for item in candidates
                if item["qa"]["scenario_family"] == scenario
                and item["row"]["report_id"] not in selected_ids
                and risk_counts[item["qa"]["observed_risk"]] < RISK_TARGETS[item["qa"]["observed_risk"]]
            ]
            if not matches:
                raise AssertionError(f"No candidate remaining for scenario {scenario}")
            matches.sort(key=lambda item: {"Low": 0, "Medium": 1, "High": 2}[item["qa"]["observed_risk"]])
            add(matches[0])

    for risk, target in RISK_TARGETS.items():
        current = sum(item["qa"]["observed_risk"] == risk for item in selected)
        matches = [
            item for item in candidates
            if item["qa"]["observed_risk"] == risk and item["row"]["report_id"] not in selected_ids
        ]
        for item in matches[: target - current]:
            add(item)

    if len(selected) != 100 or Counter(item["qa"]["observed_risk"] for item in selected) != Counter(RISK_TARGETS):
        raise AssertionError("Could not construct the requested stratified 100-report selection")

    selected.sort(key=lambda item: (item["row"]["report_date"], item["row"]["report_id"]))
    occurrence: Counter[str] = Counter()
    report_type_pools = {
        "High": ["Incident"] * 16 + ["Near Miss"] * 16,
        "Medium": ["Near Miss"] * 12 + ["Unsafe Condition"] * 12,
        "Low": ["Unsafe Condition"] * 18 + ["Unsafe Act"] * 18 + ["Near Miss"] * 8,
    }
    for values in report_type_pools.values():
        rng.shuffle(values)
    rows: list[dict[str, str]] = []
    qa: list[dict[str, Any]] = []

    for index, item in enumerate(selected, start=1):
        source = item["row"]
        source_design = item["qa"]
        scenario = source_design["scenario_family"]
        occurrence[scenario] += 1
        activity_options = SCENARIO_ACTIVITY_OPTIONS[scenario]
        activity = activity_options[(occurrence[scenario] - 1) % len(activity_options)]
        narrative = re.sub(r"Demo sequence \d{4}", f"Standalone sequence {index:04d}", source["narrative"])
        narrative = re.sub(r"prepared [a-z ]+ during", f"prepared {activity.lower()} during", narrative, count=1, flags=re.I)
        observed_risk = source_design["observed_risk"]
        report_type = report_type_pools[observed_risk].pop()
        report_id = f"DEMO100-{index:04d}"
        rows.append(
            {
                "report_id": report_id,
                "report_date": source["report_date"],
                "site": source["site"],
                "activity": activity,
                "report_type": report_type,
                "narrative": narrative,
                "source": CORPUS_VERSION,
            }
        )
        qa.append(
            {
                "report_id": report_id,
                "scenario_family": scenario,
                "primary_lsr_design": source_design["primary_lsr_design"],
                "secondary_scenario_design": source_design["secondary_scenario_design"],
                "cohort_id": f"{scenario.casefold().replace(' ', '_')}-cohort-{(occurrence[scenario] - 1) % 2 + 1}",
                "control_state_design": source_design["control_state_design"],
                "site_trend_design": source_design["site_trend_design"],
                "word_count": len(re.findall(r"\b\w+[\w/-]*\b", narrative)),
                "normalized_narrative": " ".join(narrative.casefold().split()),
            }
        )
    return rows, qa


def _profile(rows: list[dict[str, str]], qa: list[dict[str, Any]]) -> dict[str, Any]:
    reports = [base.AnalyzeInput.model_validate(row) for row in rows]
    started = time.perf_counter()
    analyses = base.analyzed_results(reports)
    elapsed = time.perf_counter() - started
    risks = Counter(analysis["risk"] for analysis in analyses)
    assignments: Counter[str] = Counter()
    unavailable_examples: dict[str, str] = {}
    precursor_sites: defaultdict[str, set[str]] = defaultdict(set)
    meaningful = 0

    for row, item, analysis in zip(rows, qa, analyses):
        mapping = analysis.get("lsr_mapping") or {}
        for rule_id in mapping.get("assigned_rule_ids", []):
            assignments[rule_id] += 1
        for rule_id in mapping.get("unavailable_rule_ids", []):
            unavailable_examples.setdefault(rule_id, row["report_id"])
        for precursor in analysis.get("precursors", []):
            if precursor != "no strong precursor pattern":
                precursor_sites[precursor].add(row["site"])
        engine = base.analyze_text(row["narrative"])
        extracted = (
            engine.get("hazards") != ["not classified"]
            or engine.get("precursors") != ["no strong precursor pattern"]
            or bool(engine.get("barrier_failures"))
            or bool(engine.get("barrier_candidates"))
        )
        meaningful += int(extracted)
        item.update(
            {
                "observed_risk": analysis["risk"],
                "observed_sif_decision": (analysis.get("screening") or {}).get("decision"),
                "observed_assigned_lsr_ids": "|".join(mapping.get("assigned_rule_ids", [])),
                "observed_unavailable_rule_ids": "|".join(mapping.get("unavailable_rule_ids", [])),
                "meaningful_hazard_extraction": extracted,
            }
        )

    trend_rows = [
        {
            "report_date": row["report_date"],
            "risk": analysis["risk"],
            "review_status": "Pending" if analysis["review_required"] else "Not required",
        }
        for row, analysis in zip(rows, analyses)
    ]
    trend_points = base.trends(trend_rows)
    domain = base.get_domain_model().metadata()
    word_counts = [item["word_count"] for item in qa]
    clusters = [
        {"name": name, "site_count": len(sites)}
        for name, sites in sorted(precursor_sites.items())
        if len(sites) >= 3
    ]
    duplicate_count = len(rows) - len(
        {(item["normalized_narrative"], row["site"].casefold()) for row, item in zip(rows, qa)}
    )
    checks = {
        "row_count": len(rows) == 100,
        "risk_distribution": RISK_TARGETS == {key: risks[key] for key in ("High", "Medium", "Low")},
        "supported_lsr_coverage": all(assignments[rule_id] >= 5 for rule_id in domain.get("supported_rule_ids", [])),
        "unavailable_lsr_examples": all(rule_id in unavailable_examples for rule_id in domain.get("unavailable_rule_ids", [])),
        "precursor_clusters": len(clusters) >= 3,
        "meaningful_extraction": meaningful >= 90,
        "word_count": min(word_counts) >= 70 and max(word_counts) <= 140,
        "duplicates": duplicate_count == 0,
        "trend_coverage": all(point["high"] + point["reviews"] > 0 for point in trend_points),
        "profile_runtime": elapsed <= 30,
    }
    return {
        "profile_version": "judge_demo_100_runtime_profile_v0.1",
        "corpus": CORPUS_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "row_count": len(rows),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "observed": {
            "risk_distribution": {key: risks[key] for key in ("High", "Medium", "Low")},
            "supported_lsr_assignments": dict(sorted(assignments.items())),
            "unavailable_lsr_examples": unavailable_examples,
            "precursor_clusters": clusters,
            "meaningful_hazard_extraction_count": meaningful,
            "word_count": {"minimum": min(word_counts), "maximum": max(word_counts)},
            "duplicate_normalized_narrative_site_pairs": duplicate_count,
            "trend_points": trend_points,
            "profile_seconds": round(elapsed, 3),
        },
        "active_artifacts": {
            "sif": base.classifier_metadata(),
            "lsr": domain,
        },
        "notes": [
            "Observed runtime categories are screening outputs for presentation coverage, not ground-truth labels.",
            "This synthetic corpus is not accuracy, calibration, or external-validation evidence.",
        ],
    }


def _write_card(profile: dict[str, Any], rows: list[dict[str, str]]) -> None:
    risk = profile["observed"]["risk_distribution"]
    dates = sorted(row["report_date"] for row in rows)
    text = f"""# Standalone 100-report judge demo corpus

Status: synthetic presentation corpus (`{CORPUS_VERSION}`). It is not a validation dataset and must not be used as accuracy, calibration, or external-validation evidence.

The dataset contains a deterministic stratified selection of 100 fictional industrial-safety reports from the synthetic 500-report judge-demo corpus, with separate IDs and provenance. All sites and events are fictional. It contains no real people, Oil India events, confidential records, or blind-test records. Use it as an alternative standalone upload; do not combine it with the 500-report version in the same workspace.

Upload `judge_demo_100.csv` or `outputs/judge_demo_100_20260912/judge_demo_100.xlsx` through Analyze report. The seven upload fields are `report_id`, `report_date`, `site`, `activity`, `report_type`, `narrative`, and `source`. Dates cover {dates[0]} through {dates[-1]}. Narratives contain 70–140 words.

Observed current-runtime coverage is High {risk['High']}, Medium/review {risk['Medium']}, and Low {risk['Low']}. These are uncalibrated screening outputs included only to verify that the application can display all routing states. No predictions, scores, retrieval results, explanations, or reviewer labels are present in the upload files.

The corpus is independent from the frozen human-validation releases under `03-training/ml/sif_v0_1/data/blind_test_v0_2` and `blind_test_v0_3`. Those releases are neither read nor modified by this generator.
"""
    (OUT_DIR / "DATASET_CARD.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, qa = _make_rows()
    profile = _profile(rows, qa)
    _write_csv(OUT_DIR / "judge_demo_100.csv", rows, UPLOAD_COLUMNS)
    _write_csv(
        OUT_DIR / "judge_demo_100_qa_matrix.csv",
        qa,
        [
            "report_id", "scenario_family", "primary_lsr_design", "secondary_scenario_design",
            "cohort_id", "control_state_design", "site_trend_design", "word_count",
            "normalized_narrative", "observed_risk", "observed_sif_decision",
            "observed_assigned_lsr_ids", "observed_unavailable_rule_ids",
            "meaningful_hazard_extraction",
        ],
    )
    (OUT_DIR / "judge_demo_100_runtime_profile.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_card(profile, rows)
    if profile["status"] != "PASS":
        raise SystemExit(f"Runtime coverage failed: {json.dumps(profile['checks'], sort_keys=True)}")
    print(json.dumps({"rows": len(rows), "status": profile["status"], "risk": profile["observed"]["risk_distribution"]}, indent=2))


if __name__ == "__main__":
    main()
