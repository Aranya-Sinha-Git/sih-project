"""Write concise truthful status and documentation from the generated v0.1 artifacts."""
from __future__ import annotations

import json

from preprocess import project_root

ROOT = project_root() / "03-training" / "ml" / "sif_v0_1"; REPORTS = ROOT / "reports"; WEAK_ARTIFACTS = ROOT / "artifacts" / "weak_demo"


def main() -> None:
    pool = json.loads((REPORTS / "candidate_pool_report.json").read_text(encoding="utf-8"))
    labels = json.loads((REPORTS / "label_audit.json").read_text(encoding="utf-8"))
    training_path = REPORTS / "supervised_training_status.json"
    training = json.loads(training_path.read_text(encoding="utf-8")) if training_path.exists() else {"trained": False, "reason": "Training not run"}
    status = "SUPERVISED_PROTOTYPE" if training.get("trained") else "WEAK_DEMO_UNVALIDATED"
    model_status = {"model_version": "sif_v0.1", "status": status, "external_validation_completed": False, "reviewed_labels_accepted": labels["reviewed_labels_accepted"], "locked_external_validation": "IOGP 2025 remains untouched"}
    (ROOT / "MODEL_STATUS.json").write_text(json.dumps(model_status, indent=2), encoding="utf-8")
    if status == "WEAK_DEMO_UNVALIDATED":
        WEAK_ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (WEAK_ARTIFACTS / "weak_demo_manifest.json").write_text(json.dumps({
            "model_status": status, "implementation": "src/weak_demo_engine.py", "output": "demo_risk_score",
            "not_a_probability": True, "review_required_for_every_output": True,
            "prohibited_uses": ["performance claims", "automated safety approval", "SIF ground-truth inference"],
        }, indent=2), encoding="utf-8")
    (ROOT / "TRAINING_REPORT.md").write_text(f"""# SIF NLP v0.1 Training Report

1. Candidate incidents found: {pool['candidate_pool_records']} real OSHA incident narratives; {pool['verified_naics_oil_gas']} have narrow verified oil/gas NAICS codes and {pool['ambiguous_existing_filter']} remain explicitly ambiguous.
2. Genuine reviewed labels found: {labels['reviewed_labels_accepted']}.
3. SIF / Non-SIF / uncertain: {labels['sif']} / {labels['non_sif']} / {labels['uncertain']}.
4. Sources used: OSHA Severe Injury Reports, used only to construct an unlabeled candidate pool.
5. Sources excluded: BSEE mixed incident/aggregate data; IOGP 2025 validation lock; BRSR/tenders/LSR reference material; inaccessible NIOSH records.
6. Models trained: none. {training.get('reason', '')}
7. Splitting method: not run; future supervised splits use duplicate groups and `StratifiedGroupKFold` with seed 26165.
8. Actual metrics: none; no valid supervised training occurred.
9. Best model: none.
10. Chosen threshold: none.
11. False negatives: none calculated; no genuine evaluation set exists.
12. External validation: not started. IOGP 2025 is locked and has no genuine SIF labels.
13. Remaining data requirement: collect at least about 200 manual/expert-reviewed labels, with at least 50 in each binary class, before training.
""", encoding="utf-8")
    (ROOT / "MODEL_CARD.md").write_text(f"""# Model Card — SIF NLP v0.1

## Intended task

Triage free-text industrial safety reports for possible SIF potential with mandatory human review. This is not an Oil India safety decision system and must not approve work or replace safety procedures.

## Current status

`{status}`. No supervised model has been trained because there are {labels['reviewed_labels_accepted']} accepted reviewed labels. The available CLI uses a transparent demonstration fallback with `demo_risk_score`, not a calibrated probability.

## Candidate sources and label provenance

The candidate pool contains real OSHA incident narratives. Only `manual_reviewed` and `expert_reviewed` labels would be accepted for supervised training; weak labels, rules output, outcomes, and unresolved labels are excluded. IOGP 2025 remains validation-locked and untouched.

## Exclusions

BSEE requires incident-grain reconciliation; Oil India BRSR, tenders, Baghjan documentation, and IOGP Life-Saving Rule documents are reference material; inaccessible NIOSH sources are not represented as incident data.

## Validation and limitations

No internal or external performance metrics exist. Key limitations are no Oil India internal UA/UC corpus, no expert SIF adjudication, source/domain mismatch, selection bias in OSHA filtering, and the continuing need for human review. A future supervised evaluation must use duplicate-safe internal splits and an independently reviewed external holdout; it must not tune against locked IOGP 2025.
""", encoding="utf-8")
    (ROOT / "WORK_STATE.md").write_text(f"""DATA FOUND: {pool['candidate_pool_records']} real OSHA candidate narratives; {pool['verified_naics_oil_gas']} narrow-NAICS oil/gas candidates; BSEE pending reconciliation.
LABEL STATUS: {labels['reviewed_labels_accepted']} accepted reviewed labels; weak/rules-derived labels rejected.
MODELS TRAINED: none.
BEST MODEL: none.
VALIDATION STATUS: IOGP 2025 locked and untouched; no genuine labelled evaluation set.
BLOCKERS: no sufficient `manual_reviewed` or `expert_reviewed` labels.
NEXT STEP: Have HSE reviewers adjudicate the 500-report queue, then export only adjudicated labels with accepted provenance.
""", encoding="utf-8")


if __name__ == "__main__": main()
