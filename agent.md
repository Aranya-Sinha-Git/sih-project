# Agent Guardrails: Frozen Human Validation

These guardrails apply to work in `03-training/ml/sif_v0_1` involving blind-test construction, human review, evaluation, manifests, calibration, or metrics.

## Preserve the blind boundary

- Treat the canonical freeze manifest as the only authority for blind-test membership and identity.
- Never add, remove, rename, repackage, relabel, or regenerate blind-test records after the freeze without creating a new explicitly versioned blind test and invalidating the old result.
- Never expose predictions, scores, model names, AI labels, consensus labels, provenance, or threshold decisions to reviewers before adjudication is locked.
- Reject any packet whose exact test IDs, source IDs, narrative hashes, or packet hash differ from the canonical manifest.

## Keep evaluation read-only

- The human evaluator may load and score only the frozen model artifact and configuration named by the canonical manifest.
- It must never fit a model, fit a calibrator, choose a model, select a threshold, or modify artifacts, labels, packets, or manifests.
- Require two distinct reviewer identities, review dates, labels, confidence, and accountable adjudication metadata before a row contributes to metrics.
- Exclude incomplete rows only when the canonical manifest records an explicit exclusion reason; report them separately.

## Prevent leakage

- Reject blind records that overlap training, development, calibration, unresolved, or duplicate-linked records by candidate/source ID and normalized narrative hash.
- Reject calibration populations that overlap the blind test by any of those identities. Blind data must not be used for calibration assessment or fitting.
- Missing required policy fields or manifest fields are hard failures, never defaults.

## Report consistently

- Compute binary metrics with the frozen binary threshold only.
- Report false-negative IDs and the count of human-positive cases routed automatically to the non-SIF band.
- Keep review-band workload separate from binary classification metrics.
- Do not report external-validation performance until all release gates in `decisions.md` are satisfied.

