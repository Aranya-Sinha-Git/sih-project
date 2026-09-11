# Domain-adaptation v0.4 experimental model card

## Status

Experimental only; neither v0.4 candidate is active. The backend remains on
the frozen v0.1 SIF screen and v0.2 LSR mapper. Runtime generative-LLM calls
remain disabled.

## Data and label provenance

- 750 unused, duplicate-isolated, real OSHA SIR reports were frozen before
  annotation: 450 training additions, 150 development additions, and 150
  fresh-final reports. The separately frozen fourth 250-row source batch was
  excluded at the user's direction and was not used by this iteration.
- Final references: 468 SIF potential, 213 Non-SIF potential, and 69 uncertain.
  Uncertain SIF targets were excluded from binary fitting; unknown LSR targets
  were masked per rule.
- Labels are GPT-5.6 Sol AI-assisted prototype references, not HSE expert
  ground truth. Of 392 second-pass/supplemental reviews, 267 were independent;
  135 target disagreements were retained as uncertain/unknown. One stalled
  125-row packet was explicitly retained as a non-independent first-pass
  recovery and excluded from agreement statistics.

## Models actually trained

- TF-IDF word 1–2 / character 3–5 Logistic Regression: C=2.0, Non-SIF class
  weight 1.5, threshold 0.55, review band 0.50–0.60. Fit on 778 binary
  training rows only; no train-plus-development refit occurred.
- SetFit `sentence-transformers/all-MiniLM-L6-v2`: one epoch, five iterations,
  train-only fit, head/tail handling for the one report above 250 tokens.
  Development threshold 0.35, review band 0.30–0.40. It was not selected:
  the declared tie preference chooses TF-IDF when balanced accuracy is within
  0.02.
- Separate nine-rule TF-IDF/Logistic Regression mapper. Its v0.4 artifact is
  experimental and is not loaded by the application.

## Results and decision

Development selection was fixed before final scoring. The selected TF-IDF
candidate passed prototype development gates: recall 0.943, precision 0.864,
specificity 0.544, balanced accuracy 0.743, F2 0.926, and 8.2% review rate.
The all-SIF development reference had balanced accuracy 0.500 and precision
0.754.

On the one-time frozen 132-row binary fresh assessment (84 SIF, 48 Non-SIF;
18 uncertain references excluded), the active baseline was TP/FP/TN/FN
84/36/12/0, recall 1.000, specificity 0.250, balanced accuracy 0.625, F2
0.921 and 9.8% review. The v0.4 TF-IDF candidate was 79/22/26/5, recall
0.940, specificity 0.542, balanced accuracy 0.741, F2 0.904 and 8.3% review.
It improves discrimination but misses five SIF references; it therefore fails
the recall and F2 promotion gates. The 90-report set remains a diagnostic
regression benchmark, not fresh validation; candidate F2 there was 0.909.

The frozen SetFit candidate was also evaluated post-hoc without reopening
selection: fresh-final TP/FP/TN/FN was 79/17/31/5, recall 0.940, precision
0.823, specificity 0.646, balanced accuracy 0.793, F2 0.914, and one review
row. Four reference SIF cases were auto-routed Non-SIF; the fifth was reviewed.
It still fails the active-baseline recall/F2 promotion gate. Its 90-report
diagnostic result was 45/7/33/5, F2 0.893 and 1.1% review. This post-hoc result
is descriptive only and did not alter threshold selection or promotion.

The experimental mapper covers all nine rules in training, but final support is
insufficient for LSR01 and LSR08 and only one LSR02 positive appears in the
fresh-final set. It is not promoted. The active mapper continues to report
LSR01, LSR02, and LSR08 as unavailable, so incomplete nine-rule coverage is
explicit in the UI.

## Reproducibility and rollback

The frozen manifests, annotations, train/dev/final splits, artifacts, seeds,
dependency versions, reports, and hashes are listed in
`artifacts/domain_adapted_v0_4/artifact_manifest_v0_4.json`. No runtime change
or rollback is required. The existing runtime benchmark remains applicable:
uncached API median/p95 90.53/144.90 ms, with zero runtime LLM token charges.
No comparable authorised LLM benchmark was run.

## Demo-readiness audit (2026-09-11)

The 18 `UNCERTAIN` rows in the frozen fresh-final packet were scored with the
existing artifacts only. They remain excluded from binary metrics. The saved
per-report scores and routes are in
`reports/domain_adaptation_v0_4/uncertain_routing_v0_4.json`.

| Artifact family | Annotator disagreement (8) | Insufficient information (10) | All uncertain rows (18) |
|---|---:|---:|---:|
| Active baseline v0.1 | 8 / 0 / 0 | 9 / 0 / 1 | 17 / 0 / 1 |
| TF-IDF v0.4 experimental | 7 / 1 / 0 | 4 / 2 / 4 | 11 / 3 / 4 |
| SetFit v0.4 experimental | 5 / 3 / 0 | 5 / 4 / 1 | 10 / 7 / 1 |

Cells are `automatic SIF / automatic Non-SIF / human review`. These are
descriptive routes, not correctness labels. On the full 150-row packet, the
review workload is 14/150 (9.3%) for the active baseline, 15/150 (10.0%) for
TF-IDF v0.4, and 2/150 (1.3%) for SetFit v0.4; these denominators include the
18 uncertain rows and must not be presented as validated accuracy.

All ten insufficient-information reasons are supported by the corresponding
narratives: the stated fall-height, fall-distance, mechanism, or environmental
severity detail is absent. The eight disagreement reasons are adjudication
provenance rather than narrative-derived missing-information explanations;
their mechanisms and injuries are described, but the label disagreement
remains unresolved. The active runtime does not generate a separate
missing-information rationale, so no such rationale is claimed.

## Confirmed runtime artifacts and rule coverage

The running backend resolves the active SIF screen to
`artifacts/supervised/tfidf_logreg.joblib` through `src/predict.py`, with
`sif-v0.1`, binary threshold 0.40, inclusive review band 0.35–0.45, and
uncalibrated raw scores. It resolves the active mapper to
`artifacts/domain_adapted_v0_2/lsr_model.joblib`, version `iogp-lsr-v0.2`,
reference `IOGP_REPORT_459_REVISED_2018`.

The active mapper has trained coverage for LSR03 Driving, LSR04 Energy
Isolation, LSR05 Hot Work, LSR06 Line of Fire, LSR07 Safe Mechanical Lifting,
and LSR09 Working at Height. LSR01 Bypassing Safety Controls, LSR02 Confined
Space, and LSR08 Work Authorisation are unavailable because their training
support is insufficient. Unavailable rules are not treated as negatives.
Assigned rules require both a model score at the rule threshold and a
criterion-aligned excerpt from the submitted narrative; the excerpt is
supporting evidence, not proof of a violation. This narrow runtime guard keeps
drive-belt and generic-maintenance collision cases from becoming confident Hot
Work mappings while retaining evidence-backed mappings. No v0.4 LSR rule or
SIF candidate was promoted.

## Illustrative demo cases (separate from assessment results)

These inputs are examples for demonstrating the product contract, not rows
from the fresh-final assessment and not validation evidence.

| Demo case | Illustrative input / expected behavior |
|---|---|
| SIF potential | “An employee contacted an energized 13,800 volt power line and suffered severe burns.” → active SIF potential; show raw score and review thresholds. |
| Non-SIF | “A worker walking across a muddy yard slipped and twisted an ankle.” → Non-SIF potential or review depending on the frozen score; never infer safety from zero rules. |
| Insufficient information | “An employee took measurements while standing on an earthen berm, lost balance, and fractured an ankle.” → human-review route when the score is in-band; missing detail is not filled in. |
| Multiple rules | “A hopper being lifted by a forklift fell on the employee and caused a back injury.” → multiple evidence-backed LSR06/LSR07 nominations with narrative excerpts. |
| Zero/incomplete mapping | “Routine housekeeping removed paper from an office floor.” → no confident mapping; `MAPPING_UNAVAILABLE` discloses incomplete LSR coverage, not a safe-condition claim. |
| Adjudication and retrieval | Submit a reviewed incident, record a reviewer outcome, then reopen it → Audit history preserves the human decision and Similar historical reports shows deterministic retrieval when matches exist. The seed demo database starts without review-history rows, so this case requires one review action during the demo. |

The UI and API label model scores as uncalibrated, separate relevant rules from
demonstrated violations, distinguish `NO_CONFIDENT_MAPPING` from
`MAPPING_UNAVAILABLE`, and keep human outcomes separate from classifier
screening. Offline AI-assisted references remain prototype evidence, not
real-world validation or HSE expert ground truth.
