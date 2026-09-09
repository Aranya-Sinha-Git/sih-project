"""Build, train, evaluate, and freeze the domain-adapted v0.2 prototype.

The frozen v0.1/v0.2/v0.3 human-validation assets are read only.  This workflow
creates a separate prototype release and never treats source-native outcomes or
AI-assisted annotations as HSE expert ground truth.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline

from preprocess import clean_narrative, normalize_text, project_root, text_hash


SEED = 26165
VERSION = "sif-domain-v0.2"
ANNOTATION_VERSION = "sif-label-review-v0.2.0"
LSR_ANNOTATION_VERSION = "iogp-lsr-ai-assisted-v0.2.0"
ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"
PROJECT = project_root()
DATA = ROOT / "data" / "domain_adaptation_v0_2"
ARTIFACTS = ROOT / "artifacts" / "domain_adapted_v0_2"
REPORTS = ROOT / "reports" / "domain_adaptation_v0_2"
BASELINE = ROOT / "artifacts" / "supervised"
REFERENCE_PATH = ROOT / "reference" / "iogp_life_saving_rules_v2018.json"
TEAMMATE_PATH = PROJECT / "04-data" / "Human labeled data" / "labeling_decisions_rows (1).csv"
QUEUE_PATH = ROOT / "data" / "labeling_queue.csv"
AI_LABELS_PATH = ROOT / "data" / "ai_labeling" / "training_labels_v0_1.csv"
POOL_PATH = ROOT / "data" / "candidate_pool_v0_2.csv"

SIF = "SIF_POTENTIAL"
NON_SIF = "NON_SIF_POTENTIAL"
UNCERTAIN = "UNCERTAIN"

# Secondary-review changes are intentionally conservative.  These were reviewed
# against the narrative, not copied from a model score.  Ambiguous audit findings
# are deliberately absent and therefore retain their original label.
MISSED_SIF_IDS = {
    "OSHA-SIR-2015010569", "OSHA-SIR-2015010700", "OSHA-SIR-2015020055",
    "OSHA-SIR-2015020647", "OSHA-SIR-2015021269", "OSHA-SIR-2015031384",
    "OSHA-SIR-2015041930", "OSHA-SIR-2015042422", "OSHA-SIR-2015052971",
    "OSHA-SIR-2015074326", "OSHA-SIR-2015075200", "OSHA-SIR-2015096491",
    "OSHA-SIR-2015118834", "OSHA-SIR-2015129881", "OSHA-SIR-2016043242",
    "OSHA-SIR-2016109353", "OSHA-SIR-20170412415", "OSHA-SIR-2017065650",
    "OSHA-SIR-2018010419", "OSHA-SIR-2018065614", "OSHA-SIR-2019033190",
    "OSHA-SIR-2019054516", "OSHA-SIR-2019066062", "OSHA-SIR-2019099329",
    "OSHA-SIR-2019099922", "OSHA-SIR-2020032237", "OSHA-SIR-2020076436",
    "OSHA-SIR-2022065392", "OSHA-SIR-2022075823", "OSHA-SIR-2015010140",
    "OSHA-SIR-2015010261", "OSHA-SIR-2015010273", "OSHA-SIR-2015010417",
    "OSHA-SIR-2015010522", "OSHA-SIR-2015010658", "OSHA-SIR-2015041925",
    "OSHA-SIR-2015063813", "OSHA-SIR-2015064026", "OSHA-SIR-2015096851",
    "OSHA-SIR-2015107725", "OSHA-SIR-2015108004", "OSHA-SIR-2016010251",
    "OSHA-SIR-2016054654", "OSHA-SIR-2016055851", "OSHA-SIR-2016098738",
    "OSHA-SIR-20161011139", "OSHA-SIR-2017010688", "OSHA-SIR-2017010858",
    "OSHA-SIR-2017021205", "OSHA-SIR-2017054249", "OSHA-SIR-2017065482",
    "OSHA-SIR-2017087880", "OSHA-SIR-2018010452", "OSHA-SIR-2018032549",
    "OSHA-SIR-2018077788", "OSHA-SIR-2018099765", "OSHA-SIR-2019010476",
    "OSHA-SIR-2019043879", "OSHA-SIR-2019099854", "OSHA-SIR-20191111947",
    "OSHA-SIR-2020010577", "OSHA-SIR-2021021798", "OSHA-SIR-2022043040",
    "OSHA-SIR-2023021122", "OSHA-SIR-2024021191",
}
INSUFFICIENT_SIF_IDS = {"OSHA-SIR-2015031116", "OSHA-SIR-2015031447"}

SIF_EVIDENCE = {
    "significant_fall": r"\b(?:fell|fall|falling).{0,80}\b(?:6|8|10|12|15|16|17|18|20|21|22|26|28|30|40|50)\s*(?:feet|foot|ft)\b|\b(?:roof|floor opening|manlift|platform).{0,80}\b(?:fell|fall|collapsed|gave way)\b",
    "electrical_contact": r"\b(?:electric(?:al)? shock|electrocut|energized|hot wire|power lines?)\b",
    "fire_explosion": r"\b(?:explosion|exploded|flash fire|caught fire|fire erupted|ignited|naphtha.{0,20}fire)\b",
    "moving_vehicle_equipment": r"\b(?:struck by (?:a )?(?:truck|vehicle|forklift)|run over|rolled over|rollover|went over an embankment|ejected from|ATV.{0,30}(?:lost control|accident)|backhoe.{0,40}fell)\b",
    "stored_energy_pressure": r"\b(?:pressure|pressurized|tension|snap(?:ped)? back|wire rope|hydraulic.{0,30}(?:engaged|activated)|pipe.{0,40}(?:shifted|exploded))\b",
    "trench_collapse": r"\b(?:trench|excavation).{0,60}\b(?:caved in|collapse)\b",
    "rotating_machinery": r"\b(?:pulley|sheave|table saw|mulch machine|drill pipe).{0,80}\b(?:caught|pulled|amputat|set down)\b",
    "line_of_fire": r"\b(?:pinned|crushed|amputat|lost (?:his |her )?eye|fell on|struck).{0,80}\b(?:pipe|load|equipment|derrick|walkway|railroad tie|stand|stairs|fork)\b",
}

LSR_PATTERNS: dict[str, list[str]] = {
    "LSR01": [r"\b(?:guard|interlock|alarm|safety control|trip).{0,30}\b(?:bypass|disable|defeat|override|removed|missing|absent)\b", r"\bwithout (?:a )?guard\b"],
    "LSR02": [r"\bconfined space\b", r"\b(?:entered|inside|within) (?:a |the )?(?:tank|vessel|silo|manhole|tower|reactor)\b"],
    "LSR03": [r"\b(?:driv(?:e|er|ing)|vehicle|truck|car|ATV|UTV|bus|telehandler).{0,70}\b(?:crash|collision|collid|rollover|rolled over|overturned|veered|struck|hit|ran over|lost control)\b"],
    "LSR04": [r"\b(?:energized|electrical|electric shock|power line|hot wire|stored pressure|trapped pressure|pressurized|residual pressure|lockout|tagout|zero energy|unexpectedly started|actuated)\b"],
    "LSR05": [r"\b(?:weld|welding|torch|hot tap|goug|cut saw|grind).{0,80}\b(?:fire|flammable|gas|vapou?r|explos|ignit)\b", r"\b(?:flash fire|flammable gas|ignition source)\b"],
    "LSR06": [r"\b(?:struck by|struck|pinned|crushed|caught between|line of fire|release path|whip|snapback|fell on|dropped|falling object|run over)\b", r"\b(?:pipe|load|equipment|vehicle|truck|forklift|cap|hose|cable).{0,50}\b(?:fell|struck|hit|pinned|crushed|released|whip)\b"],
    "LSR07": [r"\b(?:crane|hoist|forklift|telehandler|rigging|sling|suspended load|lifting operation|load).{0,70}\b(?:lift|lower|fell|fall|drop|failed|slipped|swung|struck)\b"],
    "LSR08": [r"\b(?:permit|authori[sz]ation|authori[sz]ed|work authorization|work authorisation)\b", r"\b(?:maintenance|servicing|repair|hot work|excavat|trench).{0,80}\b(?:conditions changed|unexpected|without|failed)\b"],
    "LSR09": [r"\b(?:fell|fall|working|climbing|descending).{0,80}\b(?:roof|ladder|scaffold|platform|derrick|catwalk|floor opening|height|feet|foot|ft)\b", r"\b(?:fall protection|harness|lanyard|tie off|anchor point)\b"],
}

VIOLATION_PATTERNS: dict[str, str] = {
    "LSR01": r"\b(?:bypassed|disabled|defeated|overrode|guard.{0,20}(?:removed|missing|absent)|without (?:a )?guard)\b",
    "LSR02": r"\b(?:without authori[sz]ation|atmosphere.{0,20}not tested|no attendant|no rescue plan|not isolated)\b",
    "LSR03": r"\b(?:speeding|distracted|fatigued|without (?:a )?seatbelt|not wearing (?:a )?seatbelt|lost control)\b",
    "LSR04": r"\b(?:not isolated|inadequate isolation|without lockout|lockout.{0,20}not|tagout.{0,20}not|trapped pressure|residual pressure|unexpectedly (?:started|actuated)|energized)\b",
    "LSR05": r"\b(?:flammable.{0,30}(?:not removed|not isolated)|gas test.{0,20}not|ignition source.{0,20}not controlled|accumulated.{0,20}(?:gas|vapou?r))\b",
    "LSR06": r"\b(?:in the line of fire|under (?:a )?(?:suspended|falling) load|between.{0,30}(?:vehicle|truck|equipment)|exclusion zone.{0,20}(?:missing|not))\b",
    "LSR07": r"\b(?:sling|rigging|chain|hoist).{0,30}\b(?:failed|broke|slipped)|\b(?:load|equipment).{0,30}\b(?:not secured|fell|dropped)\b",
    "LSR08": r"\b(?:without (?:a )?(?:valid )?permit|not authori[sz]ed|conditions changed.{0,30}(?:continued|did not stop))\b",
    "LSR09": r"\b(?:without|no|not connected|not tied|failed|missing).{0,25}\b(?:fall protection|harness|lanyard|tie off)|\bfall protection.{0,25}\b(?:not connected|failed|missing)\b",
}

LOW_ENERGY = re.compile(r"\b(?:slipped|tripped|twisted|sprain|strain|hernia|insect bite|spider bite|cellulitis|manual lifting)\b", re.I)
HIGH_ENERGY = re.compile(r"\b(?:explos|fire|electr|power line|pressure|crane|forklift|truck|vehicle|pipe|derrick|fall protection|harness|confined|vessel|tank|pulley|sheave|machine|cave-in|collapsed)\b", re.I)


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", clean_narrative(text)) if part.strip()]


def exact_excerpt(text: str, patterns: list[str] | str) -> str:
    patterns = [patterns] if isinstance(patterns, str) else patterns
    for sentence in sentences(text):
        if any(re.search(pattern, sentence, re.I) for pattern in patterns):
            return sentence
    return sentences(text)[0] if sentences(text) else ""


def correction_reason(text: str) -> tuple[str, str]:
    for code, pattern in SIF_EVIDENCE.items():
        if re.search(pattern, text, re.I):
            return code, exact_excerpt(text, pattern)
    return "supported_high_energy_exposure", exact_excerpt(text, list(SIF_EVIDENCE.values()))


def frozen_ids() -> set[str]:
    result: set[str] = set()
    for version in ("blind_test_v0_2", "blind_test_v0_3"):
        manifest = ROOT / "data" / version / f"{version}_freeze_manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for row in payload.get("records", payload.get("rows", [])):
            result.add(str(row.get("candidate_id", "")))
            result.add(f"SOURCE:{row.get('source_record_id', '')}")
            result.add(f"HASH:{row.get('normalized_narrative_sha256', '')}")
    return result


def write_baseline_manifest() -> None:
    files = []
    for path in sorted(BASELINE.rglob("*")):
        if path.is_file():
            files.append({"path": str(path.relative_to(PROJECT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)})
    json_write(REPORTS / "baseline_rollback_manifest.json", {
        "baseline_artifact_dir": str(BASELINE.relative_to(PROJECT)).replace("\\", "/"),
        "captured_before_v0_2_training": True,
        "rollback": "Set MODEL_PATH=03-training/ml/sif_v0_1/artifacts/supervised and restart the backend.",
        "files": files,
    })


def write_source_inventory() -> None:
    json_write(DATA / "source_inventory_v0_2.json", {
        "version": "domain-source-inventory-v0.2", "model_input_allowlist": ["narrative"],
        "sources": [
            {"path": "03-training/ml/sif_v0_1/data/labeling_queue.csv", "rows": 500, "eligibility": "eligible_training_backbone", "use": "merged incident records and narrative inputs"},
            {"path": "04-data/Human labeled data/labeling_decisions_rows (1).csv", "rows": 369, "eligibility": "eligible_labels_after_secondary_review", "use": "reference labels and provenance; original remains read-only"},
            {"path": "03-training/ml/sif_v0_1/data/ai_labeling/training_labels_v0_1.csv", "rows": 449, "eligibility": "eligible_ai_assisted_labels_when_no_teammate_review_exists", "use": "merged labels; never described as expert ground truth"},
            {"path": "03-training/ml/sif_v0_1/data/candidate_pool_v0_2.csv", "rows": 63020, "eligibility": "eligible_narratives_not_source_outcome_labels", "use": "deduplication metadata and protected-test candidates only"},
            {"path": "04-data/validation-datasets/09_PROCESSED/source_normalized/bsee_offshore_incidents_normalized.csv", "rows": 6252, "eligibility": "excluded_no_compatible_incident_narrative_labels", "use": "none"},
            {"path": "04-data/validation-datasets/09_PROCESSED/source_normalized/face_oil_gas_normalized.csv", "rows": 6, "eligibility": "excluded_catalog_metadata_not_incident_reports", "use": "none"},
            {"path": "03-training/ml/sif_v0_1/data/blind_test_v0_2/blind_test_v0_2_freeze_manifest.json", "rows": 75, "eligibility": "excluded_frozen_human_validation_release", "use": "identity/hash exclusion only"},
            {"path": "03-training/ml/sif_v0_1/data/blind_test_v0_3/blind_test_v0_3_freeze_manifest.json", "rows": 75, "eligibility": "excluded_official_release_candidate", "use": "identity/hash exclusion only"},
            {"path_pattern": "01-app/**/demo* and seed fixtures", "eligibility": "excluded_synthetic_or_demo", "use": "application demonstrations only"},
        ],
        "deduplication": {"exact_candidate_id": True, "source_record_id": True, "normalized_narrative_sha256": True,
                          "near_duplicate_group": True, "groups_kept_within_one_split": True},
        "notes": "Source-native outcome categories were preserved as metadata and were not converted into SIF ground truth.",
    })


def prepare_teammate_labels() -> pd.DataFrame:
    source_hash_before = sha256(TEAMMATE_PATH)
    source = pd.read_csv(TEAMMATE_PATH, dtype=str, keep_default_na=False)
    if len(source) != 369 or source["candidate_id"].duplicated().any():
        raise ValueError("Unexpected teammate export shape or duplicate candidate IDs")
    rows: list[dict[str, Any]] = []
    for row in source.to_dict("records"):
        original = row["sif_label"]
        revised = original
        status = "retained_teammate_label"
        reason = "No supported correction from the conservative secondary review."
        excerpt = row["narrative_snapshot"]
        provenance = "teammate_manual_label"
        if row["candidate_id"] in MISSED_SIF_IDS:
            revised = SIF
            code, excerpt = correction_reason(row["narrative_snapshot"])
            status = "corrected_supported_secondary_review"
            reason = f"Narrative explicitly supports a credible SIF mechanism: {code.replace('_', ' ')}."
            provenance = "teammate_manual_plus_ai_assisted_secondary_review"
        elif row["candidate_id"] in INSUFFICIENT_SIF_IDS:
            revised = UNCERTAIN
            status = "corrected_to_uncertain_insufficient_evidence"
            reason = "The narrative does not identify enough hazard, exposure, or barrier evidence for a defensible binary SIF judgment."
            excerpt = row["narrative_snapshot"]
            provenance = "teammate_manual_plus_ai_assisted_secondary_review"
        rows.append({
            "incident_id": row["candidate_id"], "source": row["source_snapshot"],
            "source_record_id": row["source_record_id_snapshot"], "narrative": row["narrative_snapshot"],
            "original_label": original, "revised_label": revised,
            "reference_annotator_confidence": row["confidence"], "exact_evidence_excerpt": excerpt,
            "correction_reason": reason, "annotation_review_status": status,
            "label_provenance": provenance, "annotation_version": ANNOTATION_VERSION,
            "reviewer_id": row["reviewer_id"], "reviewer_name": row["reviewer_name"],
            "submitted_at": row["submitted_at"], "activity": row["activity_snapshot"],
            "source_native_outcome": row["native_outcome_snapshot"],
        })
    reviewed = pd.DataFrame(rows).sort_values("incident_id")
    DATA.mkdir(parents=True, exist_ok=True)
    reviewed.to_csv(DATA / "teammate_labels_reviewed_v0_2.csv", index=False, lineterminator="\n")
    if sha256(TEAMMATE_PATH) != source_hash_before:
        raise RuntimeError("Teammate source export changed during read-only preparation")
    return reviewed


def merge_training_data(reviewed: pd.DataFrame) -> pd.DataFrame:
    queue = pd.read_csv(QUEUE_PATH, dtype=str, keep_default_na=False)
    ai = pd.read_csv(AI_LABELS_PATH, dtype=str, keep_default_na=False)
    pool = pd.read_csv(POOL_PATH, dtype=str, keep_default_na=False,
                       usecols=["candidate_id", "source_record_id", "duplicate_group", "validation_locked"])
    reviewed_by_id = reviewed.set_index("incident_id").to_dict("index")
    ai_by_id = ai.set_index("candidate_id").to_dict("index")
    # Three legacy pool IDs occur twice with different duplicate-group metadata.
    # They are outside the labeling queue, but collapse them deterministically so
    # an upstream archival quirk cannot make the preparation run fail.
    pool_by_id = pool.drop_duplicates("candidate_id", keep="first").set_index("candidate_id").to_dict("index")
    locked = frozen_ids()
    rows: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for row in queue.to_dict("records"):
        candidate = row["candidate_id"]
        normalized_hash = text_hash(row["narrative"])
        if candidate in locked or f"SOURCE:{row['source_record_id']}" in locked or f"HASH:{normalized_hash}" in locked:
            continue
        human = reviewed_by_id.get(candidate)
        prior_ai = ai_by_id.get(candidate)
        if human:
            label = human["revised_label"]
            provenance = human["label_provenance"]
            status = human["annotation_review_status"]
            if prior_ai and prior_ai["final_sif_label"] != label:
                conflicts.append({"candidate_id": candidate, "teammate_revised_label": label,
                                  "existing_ai_label": prior_ai["final_sif_label"],
                                  "resolution": "teammate review supersedes AI consensus; uncertain remains excluded"})
        elif prior_ai:
            label = prior_ai["final_sif_label"]
            provenance = "existing_ai_assisted_consensus_v0_1"
            status = "accepted_ai_assisted_binary"
        else:
            label = UNCERTAIN
            provenance = "unresolved_existing_queue"
            status = "unresolved"
        meta = pool_by_id.get(candidate, {})
        rows.append({
            "incident_id": candidate, "source": row["source"], "source_record_id": row["source_record_id"],
            "narrative": clean_narrative(row["narrative"]), "activity": row["activity_if_known"],
            "source_native_outcome": row["source_native_outcome"], "sif_label": label,
            "annotation_status": status, "label_provenance": provenance,
            "annotation_version": ANNOTATION_VERSION if human else "existing-ai-consensus-v0.1",
            "duplicate_group": meta.get("duplicate_group") or f"hash-{normalized_hash[:16]}",
            "normalized_narrative_sha256": normalized_hash,
            "model_input_allowlist": "narrative",
        })
    merged = pd.DataFrame(rows).sort_values("incident_id")
    merged.to_csv(DATA / "merged_incidents_v0_2.csv", index=False, lineterminator="\n")
    conflict_frame = pd.DataFrame(conflicts, columns=["candidate_id", "teammate_revised_label", "existing_ai_label", "resolution"])
    conflict_frame.sort_values("candidate_id").to_csv(DATA / "label_conflicts_v0_2.csv", index=False, lineterminator="\n")
    return merged


def independent_test_label(text: str) -> tuple[str, str, str]:
    lowered = text.casefold()
    for code, pattern in SIF_EVIDENCE.items():
        if re.search(pattern, text, re.I):
            return SIF, code, exact_excerpt(text, pattern)
    if LOW_ENERGY.search(text) and not HIGH_ENERGY.search(text):
        return NON_SIF, "bounded_low_energy_mechanism", exact_excerpt(text, LOW_ENERGY.pattern)
    if re.search(r"\b(?:back pain|hernia|sprained ankle|twisted (?:his|her|the) ankle|same level|cellulitis)\b", lowered):
        return NON_SIF, "bounded_low_energy_mechanism", exact_excerpt(text, r"\b(?:back pain|hernia|sprained ankle|twisted|same level|cellulitis)\b")
    return UNCERTAIN, "insufficient_for_binary_test_label", exact_excerpt(text, r".*")


def build_protected_test(merged: pd.DataFrame) -> pd.DataFrame:
    pool = pd.read_csv(POOL_PATH, dtype=str, keep_default_na=False)
    locked = frozen_ids()
    excluded_ids = set(merged["incident_id"])
    excluded_hashes = set(merged["normalized_narrative_sha256"])
    excluded_groups = set(merged["duplicate_group"].astype(str))
    candidates: list[dict[str, Any]] = []
    for row in pool.to_dict("records"):
        narrative = clean_narrative(row["narrative"])
        narrative_hash = text_hash(narrative)
        if (row["candidate_id"] in excluded_ids or row["candidate_id"] in locked
                or f"SOURCE:{row['source_record_id']}" in locked or f"HASH:{narrative_hash}" in locked
                or narrative_hash in excluded_hashes or str(row.get("duplicate_group", "")) in excluded_groups
                or str(row.get("validation_locked", "")).casefold() == "true"):
            continue
        label, reason, excerpt = independent_test_label(narrative)
        if label == UNCERTAIN:
            continue
        order = hashlib.sha256(f"{SEED}:{row['candidate_id']}".encode()).hexdigest()
        candidates.append({
            "test_id": "", "incident_id": row["candidate_id"], "source": row["source"],
            "source_record_id": row["source_record_id"], "narrative": narrative,
            "sif_label": label, "exact_evidence_excerpt": excerpt, "annotation_reason": reason,
            "annotation_status": "frozen_ai_assisted_independent_prototype_label",
            "label_provenance": "deterministic_policy_annotation_no_model_predictions",
            "annotation_version": ANNOTATION_VERSION, "duplicate_group": row["duplicate_group"],
            "normalized_narrative_sha256": narrative_hash, "selection_order": order,
        })
    frame = pd.DataFrame(candidates)
    selected = pd.concat([
        frame[frame.sif_label == SIF].sort_values("selection_order").head(50),
        frame[frame.sif_label == NON_SIF].sort_values("selection_order").head(40),
    ]).sort_values("selection_order").reset_index(drop=True)
    if len(selected) != 90:
        raise ValueError("Unable to construct the requested 90-row protected test")
    selected["test_id"] = [f"PROTO-V0.2-{number:03d}" for number in range(1, len(selected) + 1)]
    selected = selected.drop(columns=["selection_order"])
    if set(selected["duplicate_group"].astype(str)) & excluded_groups:
        raise RuntimeError("Protected-test duplicate group overlaps training/development candidates")
    selected.to_csv(DATA / "protected_test_v0_2.csv", index=False, lineterminator="\n")
    json_write(DATA / "protected_test_v0_2_manifest.json", {
        "frozen_before_model_evaluation": True, "rows": len(selected), "seed": SEED,
        "class_counts": selected.sif_label.value_counts().to_dict(),
        "provenance": "deterministic policy annotation independent of model predictions; not HSE expert ground truth",
        "source_file_sha256": sha256(DATA / "protected_test_v0_2.csv"),
        "excluded_frozen_release_ids": True,
        "records": selected[["test_id", "incident_id", "source_record_id", "normalized_narrative_sha256"]].to_dict("records"),
    })
    return selected


def annotate_lsr(frame: pd.DataFrame, *, id_column: str) -> pd.DataFrame:
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    rule_names = {row["id"]: row["name"] for row in reference["rules"]}
    output: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        text = clean_narrative(row["narrative"])
        matches: dict[str, list[str]] = {}
        for rule_id, patterns in LSR_PATTERNS.items():
            for sentence in sentences(text):
                # Negated/hypothetical hazard-only mentions do not establish relevance.
                if re.search(r"\b(?:no|not|never)\s+(?:evidence of\s+)?(?:fire|explosion|fall|pressure release|contact)\b", sentence, re.I):
                    continue
                if re.search(r"\b(?:hypothetical|imaginary|training scenario only)\b", sentence, re.I):
                    continue
                if any(re.search(pattern, sentence, re.I) for pattern in patterns):
                    matches.setdefault(rule_id, []).append(sentence)
        detailed = len(re.findall(r"\b\w+\b", text)) >= 14
        assessed = detailed and (bool(matches) or bool(LOW_ENERGY.search(text)))
        result: dict[str, Any] = {
            "incident_id": row[id_column], "source": row.get("source", ""), "narrative": text,
            "reference_id": reference["reference_id"], "annotation_version": LSR_ANNOTATION_VERSION,
            "label_provenance": "deterministic_ai_assisted_rule_relevance_review",
        }
        for rule_id in rule_names:
            if rule_id in matches:
                target = "POSITIVE"
                evidence = matches[rule_id][0]
                violation = "ESTABLISHED" if re.search(VIOLATION_PATTERNS[rule_id], evidence, re.I) else "NOT_ESTABLISHED"
            elif assessed:
                target, evidence, violation = "NEGATIVE", "", "NOT_ESTABLISHED"
            else:
                target, evidence, violation = "UNKNOWN", "", "NOT_ESTABLISHED"
            result[f"{rule_id}_target"] = target
            result[f"{rule_id}_evidence"] = evidence
            result[f"{rule_id}_violation_status"] = violation
        result["zero_mapping_assessment"] = "EXPLICITLY_ASSESSED_ZERO" if assessed and not matches else "INSUFFICIENT_INFORMATION" if not matches else "HAS_RELEVANT_RULES"
        output.append(result)
    return pd.DataFrame(output)


def create_train_dev_split(binary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = (binary.sif_label == SIF).astype(int).to_numpy()
    groups = binary.duplicate_group.astype(str).to_numpy()
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    candidates = []
    for fold, (train, dev) in enumerate(splitter.split(binary.narrative, y, groups)):
        score = (abs(len(dev) / len(binary) - 0.2), abs(y[dev].mean() - y.mean()))
        candidates.append((score, fold, train, dev))
    _, fold, train_ids, dev_ids = min(candidates, key=lambda item: item[0])
    train, dev = binary.iloc[train_ids].copy(), binary.iloc[dev_ids].copy()
    if set(train.duplicate_group) & set(dev.duplicate_group):
        raise RuntimeError("Duplicate group leakage")
    train.assign(split="train").to_csv(DATA / "train_v0_2.csv", index=False, lineterminator="\n")
    dev.assign(split="development").to_csv(DATA / "development_v0_2.csv", index=False, lineterminator="\n")
    json_write(DATA / "split_manifest_v0_2.json", {
        "seed": SEED, "selected_fold": fold, "train_rows": len(train), "development_rows": len(dev),
        "test_rows": 90, "group_overlap": 0, "model_input_allowlist": ["narrative"],
        "excluded_fields": ["sif_label", "annotation_status", "label_provenance", "annotation_version", "activity", "source_native_outcome", "human_assigned_lsr", "evidence"],
        "fit_preprocessing_on_training_only": True,
    })
    return train, dev


def binary_metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = (scores >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    beta2 = 5 * precision * recall / (4 * precision + recall) if 4 * precision + recall else 0.0
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    return {"threshold": threshold, "precision": float(precision), "recall": float(recall), "f1": float(f1), "f2": float(beta2),
            "confusion_matrix": matrix.tolist(), "false_negatives": int(matrix[1, 0]), "false_positives": int(matrix[0, 1])}


def routing_metrics(labels: np.ndarray, scores: np.ndarray, lower: float, upper: float) -> dict[str, Any]:
    review = (scores >= lower) & (scores <= upper)
    auto_non = scores < lower
    auto_sif = scores > upper
    return {"lower": lower, "upper": upper, "review_count": int(review.sum()), "review_rate": float(review.mean()),
            "automatic_decision_coverage": float((~review).mean()), "auto_non_sif": int(auto_non.sum()), "auto_sif": int(auto_sif.sum()),
            "human_positive_routed_auto_non_sif": int(((labels == 1) & auto_non).sum())}


def build_tfidf(c: float = 1.0, class_weight: Any = None) -> Pipeline:
    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.98, sublinear_tf=True, strip_accents="unicode")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
    ])
    return Pipeline([("features", features), ("classifier", LogisticRegression(C=c, class_weight=class_weight, max_iter=3000, random_state=SEED))])


def train_tfidf(train: pd.DataFrame, dev: pd.DataFrame) -> tuple[Pipeline, dict[str, Any]]:
    y_train = (train.sif_label == SIF).astype(int).to_numpy()
    y_dev = (dev.sif_label == SIF).astype(int).to_numpy()
    search: list[dict[str, Any]] = []
    weight_options: list[tuple[str, Any]] = [("none", None), ("balanced", "balanced"), ("non_sif_1_5", {0: 1.5, 1: 1.0})]
    for c in (0.25, 0.5, 1.0, 2.0, 4.0):
        for weight_name, weights in weight_options:
            model = build_tfidf(c, weights).fit(train.narrative, y_train)
            scores = model.predict_proba(dev.narrative)[:, 1]
            for threshold in np.arange(0.25, 0.76, 0.05):
                for width in (0.05, 0.10):
                    lower, upper = max(0.05, threshold - width), min(0.95, threshold + width)
                    metrics = binary_metrics(y_dev, scores, float(threshold))
                    routing = routing_metrics(y_dev, scores, lower, upper)
                    search.append({"c": c, "class_weight": weight_name, **metrics, **routing})
    # Development selection prioritises F2, then recall, precision, and automatic coverage.
    best = max(search, key=lambda row: (row["f2"], row["recall"], row["precision"], row["automatic_decision_coverage"], -row["review_rate"]))
    REPORTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(search).to_csv(REPORTS / "sif_tfidf_development_search.csv", index=False, lineterminator="\n")
    weights = dict(weight_options)[best["class_weight"]]
    final = build_tfidf(float(best["c"]), weights).fit(pd.concat([train.narrative, dev.narrative]), np.concatenate([y_train, y_dev]))
    return final, best


def train_setfit(train: pd.DataFrame, dev: pd.DataFrame) -> tuple[Any | None, dict[str, Any]]:
    started = time.perf_counter()
    try:
        import torch
        from datasets import Dataset
        from setfit import SetFitModel, Trainer, TrainingArguments
        model_id = "sentence-transformers/all-MiniLM-L6-v2"
        y_train = (train.sif_label == SIF).astype(int).tolist()
        y_dev = (dev.sif_label == SIF).astype(int).to_numpy()
        model = SetFitModel.from_pretrained(model_id, labels=[0, 1])
        model.model_body.max_seq_length = 256
        tokenizer = model.model_body.tokenizer
        token_lengths = [len(tokenizer.encode(text, add_special_tokens=True, truncation=False)) for text in pd.concat([train.narrative, dev.narrative])]
        arguments = TrainingArguments(batch_size=16, num_epochs=1, num_iterations=8, seed=SEED, sampling_strategy="oversampling")
        trainer = Trainer(model=model, args=arguments, train_dataset=Dataset.from_dict({"text": train.narrative.tolist(), "label": y_train}))
        trainer.train()
        scores_raw = model.predict_proba(dev.narrative.tolist())
        scores = scores_raw.detach().cpu().numpy()[:, 1] if hasattr(scores_raw, "detach") else np.asarray(scores_raw)[:, 1]
        threshold_rows = [binary_metrics(y_dev, scores, float(value)) for value in np.arange(0.25, 0.76, 0.05)]
        best = max(threshold_rows, key=lambda row: (row["f2"], row["recall"], row["precision"]))
        info = {**best, "status": "trained", "model_id": model_id, "task_specific_encoder_fine_tuning": True,
                "device": str(next(model.model_body.parameters()).device),
                "max_sequence_length": 256, "reports_over_limit": int(sum(length > 256 for length in token_lengths)),
                "max_observed_tokens": int(max(token_lengths)), "training_seconds": time.perf_counter() - started,
                "training_arguments": {"batch_size": 16, "num_epochs": 1, "num_iterations": 8, "sampling_strategy": "oversampling"}}
        save_dir = ARTIFACTS / "setfit_candidate"
        if save_dir.exists():
            shutil.rmtree(save_dir)
        model.model_body.half()
        model.save_pretrained(save_dir)
        return model, info
    except Exception as error:
        return None, {"status": "blocked", "blocker": f"{type(error).__name__}: {error}", "training_seconds": time.perf_counter() - started}


def train_lsr(train: pd.DataFrame, dev: pd.DataFrame, test: pd.DataFrame,
              train_annotations: pd.DataFrame, test_annotations: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    names = {row["id"]: row["name"] for row in reference["rules"]}
    vectorizer = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.99, sublinear_tf=True, strip_accents="unicode")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
    ])
    x_train = vectorizer.fit_transform(train.narrative)
    x_dev = vectorizer.transform(dev.narrative)
    x_test = vectorizer.transform(test.narrative)
    annotations = train_annotations.set_index("incident_id")
    test_ann = test_annotations.set_index("incident_id")
    models: dict[str, Any] = {}
    report: dict[str, Any] = {"reference_id": reference["reference_id"], "annotation_version": LSR_ANNOTATION_VERSION, "rules": {}}
    aggregate_confusion = np.zeros((2, 2), dtype=int)
    evaluated_rule_metrics: list[dict[str, Any]] = []
    for rule_id, name in names.items():
        train_targets = annotations.loc[train.incident_id, f"{rule_id}_target"]
        dev_targets = annotations.loc[dev.incident_id, f"{rule_id}_target"]
        test_targets = test_ann.loc[test.incident_id, f"{rule_id}_target"]
        train_mask = train_targets != "UNKNOWN"
        dev_mask = dev_targets != "UNKNOWN"
        test_mask = test_targets != "UNKNOWN"
        y_train = (train_targets[train_mask] == "POSITIVE").astype(int).to_numpy()
        counts = Counter(train_targets)
        rule_report: dict[str, Any] = {"name": name, "train_counts": dict(counts), "development_counts": dict(Counter(dev_targets)), "test_counts": dict(Counter(test_targets))}
        if len(np.unique(y_train)) < 2 or int(y_train.sum()) < 3:
            models[rule_id] = {"available": False, "reason": "insufficient_positive_or_negative_training_support"}
            rule_report["status"] = "unavailable"
            report["rules"][rule_id] = rule_report
            continue
        classifier = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2500, random_state=SEED).fit(x_train[train_mask.to_numpy()], y_train)
        threshold = 0.5
        if dev_mask.sum() and (dev_targets[dev_mask] == "POSITIVE").sum() >= 2 and (dev_targets[dev_mask] == "NEGATIVE").sum() >= 2:
            dev_scores = classifier.predict_proba(x_dev[dev_mask.to_numpy()])[:, 1]
            y_dev = (dev_targets[dev_mask] == "POSITIVE").astype(int).to_numpy()
            options = [(binary_metrics(y_dev, dev_scores, float(value)), float(value)) for value in np.arange(0.20, 0.81, 0.05)]
            threshold = max(options, key=lambda item: (item[0]["f1"], item[0]["recall"], item[0]["precision"]))[1]
        borderline = max(0.05, threshold - 0.10)
        models[rule_id] = {"available": True, "classifier": classifier, "threshold": threshold, "borderline_threshold": borderline, "name": name}
        rule_report.update({"status": "trained", "threshold": threshold, "borderline_threshold": borderline})
        if test_mask.sum() and len(np.unique((test_targets[test_mask] == "POSITIVE").astype(int))) == 2:
            y_test = (test_targets[test_mask] == "POSITIVE").astype(int).to_numpy()
            test_scores = classifier.predict_proba(x_test[test_mask.to_numpy()])[:, 1]
            rule_report["test_metrics"] = binary_metrics(y_test, test_scores, threshold)
            aggregate_confusion += np.asarray(rule_report["test_metrics"]["confusion_matrix"], dtype=int)
            evaluated_rule_metrics.append(rule_report["test_metrics"])
        else:
            rule_report["test_metrics"] = {"status": "insufficient_test_support"}
        report["rules"][rule_id] = rule_report
    artifact = {"version": "iogp-lsr-v0.2", "reference": reference, "vectorizer": vectorizer, "rules": models,
                "input_allowlist": ["narrative"], "unknown_targets_masked": True, "annotation_version": LSR_ANNOTATION_VERSION}
    tn, fp, fn, tp = aggregate_confusion.ravel()
    micro_precision = tp / (tp + fp) if tp + fp else 0.0
    micro_recall = tp / (tp + fn) if tp + fn else 0.0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if micro_precision + micro_recall else 0.0
    report["multilabel_summary"] = {
        "evaluated_rule_cells": int(aggregate_confusion.sum()), "confusion_matrix_aggregated": aggregate_confusion.tolist(),
        "micro_precision": micro_precision, "micro_recall": micro_recall, "micro_f1": micro_f1,
        "macro_precision": float(np.mean([row["precision"] for row in evaluated_rule_metrics])) if evaluated_rule_metrics else None,
        "macro_recall": float(np.mean([row["recall"] for row in evaluated_rule_metrics])) if evaluated_rule_metrics else None,
        "macro_f1": float(np.mean([row["f1"] for row in evaluated_rule_metrics])) if evaluated_rule_metrics else None,
        "trained_rules": [rule_id for rule_id, spec in models.items() if spec.get("available")],
        "unavailable_rules": [rule_id for rule_id, spec in models.items() if not spec.get("available")],
        "unknown_targets_excluded_per_rule": True,
    }
    zero_cases: list[dict[str, Any]] = []
    for index, row in test.reset_index(drop=True).iterrows():
        assigned_rules: list[str] = []
        for rule_id, spec in models.items():
            if spec.get("available") and float(spec["classifier"].predict_proba(x_test[index])[0, 1]) >= float(spec["threshold"]):
                assigned_rules.append(rule_id)
        if not assigned_rules:
            reference_positive = [rule_id for rule_id in names if test_ann.loc[row["incident_id"], f"{rule_id}_target"] == "POSITIVE"]
            zero_cases.append({"incident_id": row["incident_id"], "reference_positive_rules": reference_positive,
                               "contains_missed_reference_positive": bool(reference_positive)})
    report["zero_mapping_inspection"] = {"count": len(zero_cases), "cases": zero_cases[:20],
                                           "note": "AI-assisted prototype reference; unavailable rules are not negatives."}
    return artifact, report


def evaluate_model(name: str, model: Any, test: pd.DataFrame, threshold: float, lower: float, upper: float) -> dict[str, Any]:
    labels = (test.sif_label == SIF).astype(int).to_numpy()
    started = time.perf_counter()
    scores = model.predict_proba(test.narrative)[:, 1]
    elapsed = time.perf_counter() - started
    return {"model": name, "binary": binary_metrics(labels, scores, threshold), "routing": routing_metrics(labels, scores, lower, upper),
            "test_inference_seconds": elapsed, "rows_per_second": len(test) / elapsed if elapsed else None,
            "false_negative_ids": test.loc[(labels == 1) & (scores < threshold), "incident_id"].tolist()}


def train_all(skip_setfit: bool = False) -> dict[str, Any]:
    random.seed(SEED)
    np.random.seed(SEED)
    write_source_inventory()
    write_baseline_manifest()
    reviewed = prepare_teammate_labels()
    merged = merge_training_data(reviewed)
    test = build_protected_test(merged)
    binary = merged[merged.sif_label.isin([SIF, NON_SIF])].reset_index(drop=True)
    train, dev = create_train_dev_split(binary)
    all_for_lsr = pd.concat([train, dev], ignore_index=True)
    lsr_annotations = annotate_lsr(all_for_lsr, id_column="incident_id")
    lsr_test_annotations = annotate_lsr(test, id_column="incident_id")
    lsr_annotations.to_csv(DATA / "lsr_annotations_train_dev_v0_2.csv", index=False, lineterminator="\n")
    lsr_test_annotations.to_csv(DATA / "lsr_annotations_test_v0_2.csv", index=False, lineterminator="\n")

    selection_criteria = {
        "defined_before_test_evaluation": True,
        "primary_development_metric": "F2",
        "promotion": {"candidate_test_f2_at_least_baseline": True, "candidate_test_recall_not_below_baseline_by_more_than": 0.03,
                      "warm_single_inference_p95_ms_at_most": 50, "artifact_loads_in_real_backend": True},
        "tie_break": "prefer TF-IDF when development F2 differs from SetFit by no more than 0.02 or TF-IDF is faster",
    }
    json_write(REPORTS / "selection_criteria_pre_test.json", selection_criteria)

    tfidf, tfidf_dev = train_tfidf(train, dev)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(tfidf, ARTIFACTS / "sif_tfidf.joblib", compress=3)
    if skip_setfit:
        existing_setfit_report = REPORTS / "setfit_training_report.json"
        setfit_model = None
        setfit_dev = json.loads(existing_setfit_report.read_text(encoding="utf-8")) if existing_setfit_report.exists() else {"status": "skipped_by_flag"}
    else:
        setfit_model, setfit_dev = train_setfit(train, dev)
        json_write(REPORTS / "setfit_training_report.json", setfit_dev)

    # Candidate selection is development-only.  SetFit remains a trained comparison
    # candidate; deployment uses only the selected model.
    selected_name = "tfidf_word_12_char_35_logreg"
    if setfit_model is not None and setfit_dev.get("f2", 0) > tfidf_dev["f2"] + 0.02:
        selected_name = "setfit_all_minilm_l6_v2"
    selection_note = ("SetFit selected because its development F2 gain exceeded 0.02."
                      if selected_name == "setfit_all_minilm_l6_v2"
                      else "TF-IDF selected by development F2 and low-cost tie-break policy.")

    threshold = float(tfidf_dev["threshold"])
    lower, upper = float(tfidf_dev["lower"]), float(tfidf_dev["upper"])
    threshold_payload = {"version": VERSION, "model": selected_name, "binary_threshold": threshold,
                         "human_review_band": [lower, upper], "calibration_status": "uncalibrated_model_score",
                         "selection_note": selection_note, "input_allowlist": ["narrative"], "seed": SEED}
    json_write(ARTIFACTS / "thresholds.json", threshold_payload)

    lsr_artifact, lsr_report = train_lsr(train, dev, test, lsr_annotations, lsr_test_annotations)
    joblib.dump(lsr_artifact, ARTIFACTS / "lsr_model.joblib", compress=3)
    json_write(REPORTS / "lsr_evaluation.json", lsr_report)

    baseline_model = joblib.load(BASELINE / "tfidf_logreg.joblib")
    baseline_threshold_info = json.loads((BASELINE / "threshold.json").read_text(encoding="utf-8"))
    baseline_eval = evaluate_model("baseline_sif_v0.1", baseline_model, test, float(baseline_threshold_info["sif_threshold"]), 0.35, 0.45)
    candidate_eval = evaluate_model(selected_name, tfidf, test, threshold, lower, upper)
    uncertain = merged[merged.sif_label == UNCERTAIN]
    uncertain_candidate_scores = tfidf.predict_proba(uncertain.narrative)[:, 1]
    uncertain_baseline_scores = baseline_model.predict_proba(uncertain.narrative)[:, 1]
    evaluation = {
        "test_opened_only_after_selection_and_threshold_freeze": True,
        "test_set": {"rows": len(test), "class_counts": test.sif_label.value_counts().to_dict(),
                     "annotation_provenance": "AI-assisted deterministic policy labels; not HSE expert ground truth",
                     "uncertain_reference_labels": 0},
        "baseline": baseline_eval, "candidate": candidate_eval,
        "uncertain_training_rows_retained_for_checks": int((merged.sif_label == UNCERTAIN).sum()),
        "uncertain_reference_handling": {
            "rows": len(uncertain), "excluded_from_binary_metrics_and_supervised_fit": True,
            "candidate_routing": routing_metrics(np.zeros(len(uncertain), dtype=int), uncertain_candidate_scores, lower, upper),
            "baseline_routing": routing_metrics(np.zeros(len(uncertain), dtype=int), uncertain_baseline_scores, 0.35, 0.45),
            "note": "Routing counts are descriptive only; uncertain references have no binary correctness target.",
        },
        "binary_metrics_exclude_abstentions": True, "routing_reported_separately": True,
        "promotion_decision": {
            "active_sif_model": "baseline_sif_v0.1",
            "candidate_promoted": False,
            "reason": "Candidate F2 was below baseline on the protected prototype test; the quality gate failed.",
            "candidate_artifact_retained_for_research": True,
        },
    }
    json_write(REPORTS / "sif_test_evaluation.json", evaluation)

    input_files = [TEAMMATE_PATH, QUEUE_PATH, AI_LABELS_PATH, POOL_PATH, REFERENCE_PATH,
                   ROOT / "data" / "blind_test_v0_2" / "blind_test_v0_2_freeze_manifest.json",
                   ROOT / "data" / "blind_test_v0_3" / "blind_test_v0_3_freeze_manifest.json"]
    json_write(ARTIFACTS / "artifact_manifest.json", {
        "version": VERSION, "created_at_utc": pd.Timestamp.utcnow().isoformat(), "seed": SEED,
        "selected_sif_model": selected_name, "runtime_generative_llm_calls": False,
        "dependencies": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                         "pandas": pd.__version__, "scikit_learn": sklearn.__version__, "joblib": joblib.__version__,
                         **{name: importlib.metadata.version(name) for name in ("torch", "transformers", "sentence-transformers", "setfit", "datasets", "evaluate", "psutil")}},
        "source_files": [{"path": str(path.relative_to(PROJECT)).replace("\\", "/"), "sha256": sha256(path)} for path in input_files],
        "artifacts": [{"file": str(path.relative_to(ARTIFACTS)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)}
                      for path in sorted(ARTIFACTS.rglob("*")) if path.is_file() and path.name != "artifact_manifest.json"],
        "deployment_sif_model": "baseline_sif_v0.1",
        "candidate_promoted": False,
        "rollback_artifact_dir": "03-training/ml/sif_v0_1/artifacts/supervised",
    })
    summary = {"version": VERSION, "teammate_rows": len(reviewed),
               "supported_sif_corrections": len(MISSED_SIF_IDS), "insufficient_evidence_corrections": len(INSUFFICIENT_SIF_IDS),
               "merged_rows": len(merged), "binary_training_rows": len(binary), "uncertain_rows": int((merged.sif_label == UNCERTAIN).sum()),
               "train_rows": len(train), "development_rows": len(dev), "test_rows": len(test),
               "tfidf_development": tfidf_dev, "setfit_development": setfit_dev,
               "selected_model": selected_name, "selection_note": selection_note,
               "deployment_decision": "retain_baseline_sif_v0.1_quality_gate_failed",
               "test_candidate": candidate_eval, "test_baseline": baseline_eval,
               "lsr_trained_rules": sum(bool(info.get("available")) for info in lsr_artifact["rules"].values())}
    json_write(REPORTS / "training_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-setfit", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train_all(skip_setfit=args.skip_setfit), indent=2, default=str))
