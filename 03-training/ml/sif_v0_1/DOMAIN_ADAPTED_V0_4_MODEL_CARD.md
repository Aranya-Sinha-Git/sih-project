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
