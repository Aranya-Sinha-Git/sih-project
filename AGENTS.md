# Repository Agent Requirements

- Treat `03-training/ml/sif_v0_1/data/blind_test_v0_2` as a frozen human-validation release. Do not alter its canonical packet or freeze manifest after release.
- Treat `03-training/ml/sif_v0_1/data/blind_test_v0_3` as the official release candidate. Its canonical blank packet and freeze manifest are immutable; only its fixed finalization and attestation artifacts may become official after review.
- Changes to the frozen human-validation workflow must preserve the v0.1 historical artifacts and must not add predictions, AI labels, model scores, retrieval results, or explanations to reviewer packets.
- Before concluding any repository change, run the relevant targeted tests, commit the completed work, and push the commit to the configured GitHub `origin` remote. Report the commit and push result.


# Agent Guardrails: Frozen Human Validation

These guardrails apply to work in `03-training/ml/sif_v0_1` involving blind-test construction, human review, evaluation, manifests, calibration, or metrics.

## Preserve the blind boundary

- Treat the canonical freeze manifest as the only authority for blind-test membership and identity.
- Never add, remove, rename, repackage, relabel, or regenerate blind-test records after the freeze without creating a new explicitly versioned blind test and invalidating the old result.
- Never expose predictions, scores, model names, AI labels, consensus labels, provenance, or threshold decisions to reviewers before adjudication is locked.
- Reject any packet whose exact test IDs, source IDs, or narrative hashes differ from the canonical manifest. The canonical blank packet hash protects the pre-review release; the separate finalization manifest protects completed-packet content.

## Keep evaluation read-only

- The human evaluator may load and score only the frozen model artifact and configuration named by the canonical manifest.
- It must never fit a model, fit a calibrator, choose a model, select a threshold, or modify artifacts, labels, packets, or manifests.
- Require two distinct reviewer identities, review dates, labels, confidence, and accountable adjudication metadata before a row contributes to metrics.
- Exclude incomplete rows only with a policy-approved reason, accountable exclusion/adjudicator provenance, and the predeclared retained-sample floor; report them separately.

## Prevent leakage

- Reject blind records that overlap training, development, calibration, unresolved, or duplicate-linked records by candidate/source ID and normalized narrative hash.
- Reject calibration populations that overlap the blind test by any of those identities. Blind data must not be used for calibration assessment or fitting.
- Missing required policy fields or manifest fields are hard failures, never defaults.
- The official evaluator uses only the fixed v0.3 artifact locations and requires the official attestation; generic packet evaluation is explicitly NON_OFFICIAL.

## Report consistently

- Compute binary metrics with the frozen binary threshold only.
- Report false-negative IDs and the count of human-positive cases routed automatically to the non-SIF band.
- Keep review-band workload separate from binary classification metrics.
- Do not report external-validation performance until all release gates in `decisions.md` are satisfied.
