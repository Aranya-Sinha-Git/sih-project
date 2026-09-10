# Bounded domain-adaptation iteration v0.3

## Status

This is one bounded post-diagnosis development iteration. The active SIF model
remains the frozen v0.1 TF-IDF classifier at binary threshold 0.40 and review
band 0.35–0.45. The active LSR artifact remains v0.2. Neither v0.3 artifact is
promoted. Scores are uncalibrated model scores, and AI-assisted references are
not HSE expert ground truth.

## Data and freeze boundaries

- Reused the existing duplicate-group-isolated 369-row training and 92-row
  development partitions. Model input remains the cleaned narrative only.
- Froze one 100-report real OSHA assessment with 50 SIF and 50 Non-SIF
  AI-assisted deterministic-policy labels before scoring. It is independent of
  train, development, the 90-report regression benchmark, and frozen human
  validation by incident ID, source ID, narrative hash, and duplicate group.
- The prior 90-report set remains a regression benchmark because it already
  informed diagnosis. No frozen v0.2/v0.3 reviewer packet or manifest changed.

## SIF models and development selection

The TF-IDF search was limited to nine combinations: C 0.5, 1.0, or 2.0 crossed
with no class weighting, balanced weighting, or Non-SIF weight 1.5. Thresholds
and review bands were selected only on development. The exact selected model
was fitted on training only and was not refitted after threshold selection.

| Candidate | Fit performed in this iteration | Threshold / review band | Development TP/FP/TN/FN | Recall | Precision | Specificity | Balanced accuracy | F2 | Review | Gate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| TF-IDF C=2, balanced | Yes | 0.75 / 0.70–0.80 | 41/0/18/33 | 0.554 | 1.000 | 1.000 | 0.777 | 0.608 | 25.0% | Fail: recall < 0.90 |
| Saved SetFit checkpoint | No; reused train-only checkpoint | 0.25 / 0.20–0.30 | 68/9/9/6 | 0.919 | 0.883 | 0.500 | 0.709 | 0.912 | 1.1% | Pass |
| All-SIF reference | No | n/a | 74/18/0/0 | 1.000 | 0.804 | 0.000 | 0.500 | 0.954 | n/a | Fail |

The declared objective was: pass every development gate, then maximize balanced
accuracy, followed by F2, recall, specificity, precision, and lower review
workload. SetFit was therefore frozen as the comparison candidate; this did not
authorize runtime promotion.

## Frozen assessment and regression results

Binary metrics and operational routing are separate. Review rows are not counted
as correct binary predictions.

### One-time 100-report frozen AI-assisted assessment

| Model | TP/FP/TN/FN | Recall | Precision | Specificity | Balanced accuracy | F2 | Review / automatic coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Active v0.1 baseline | 49/25/25/1 | 0.980 | 0.662 | 0.500 | 0.740 | 0.894 | 22.0% / 78.0% |
| Corrected train-only TF-IDF v0.3 | 27/1/49/23 | 0.540 | 0.964 | 0.980 | 0.760 | 0.592 | 18.0% / 82.0% |
| Saved SetFit checkpoint | 45/22/28/5 | 0.900 | 0.672 | 0.560 | 0.730 | 0.843 | 1.0% / 99.0% |
| All-SIF reference | 50/50/0/0 | 1.000 | 0.500 | 0.000 | 0.500 | 0.833 | n/a |
| All-Non-SIF reference | 0/0/50/50 | 0.000 | 0.000 | 1.000 | 0.500 | 0.000 | n/a |

The saved SetFit candidate failed both frozen-assessment metric promotion gates:
its F2 was below the baseline and recall was 0.08 lower. It is also unsupported
by the real backend classifier adapter. Runtime latency was therefore not
measured or guessed.

### Existing 90-report diagnostic regression benchmark

| Model | TP/FP/TN/FN | Recall | Precision | Specificity | Balanced accuracy | F2 | Review |
|---|---:|---:|---:|---:|---:|---:|---:|
| Active v0.1 baseline | 47/21/19/3 | 0.940 | 0.691 | 0.475 | 0.708 | 0.877 | 7.8% |
| Old v0.2 TF-IDF | 50/40/0/0 | 1.000 | 0.556 | 0.000 | 0.500 | 0.862 | 0.0% |
| Corrected train-only TF-IDF v0.3 | 23/2/38/27 | 0.460 | 0.920 | 0.950 | 0.705 | 0.511 | 23.3% |
| Saved SetFit checkpoint | 45/16/24/5 | 0.900 | 0.738 | 0.600 | 0.750 | 0.862 | 1.1% |

The score-scale collapse is fixed—the v0.3 TF-IDF no longer predicts every
record as SIF—but the supported operating point trades away too much recall.

## LSR review and experimental coverage

All 29 diagnosed LSR01 and 56 LSR02 pattern hits were read as narratives rather
than accepted as labels. The ledger records 27/2 positive/negative LSR01
judgments and 37/13/6 positive/negative/unknown LSR02 judgments. Protected rows
remain in the ledger but are excluded from fitting and evaluation. A broader
LSR08 definition/synonym review found two supported examples, below the existing
minimum of three. LSR08 remains unavailable.

| Rule | Experimental training P/N | Threshold | Evaluation P/N | Precision | Recall | F1 | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| LSR01 Bypassing Safety Controls | 18/209 | 0.35 | 5/1 | 1.000 | 1.000 | 1.000 | Trained; holdout is very small |
| LSR02 Confined Space | 25/215 | 0.40 | 6/2 | 0.750 | 1.000 | 0.857 | Trained; both holdout negatives were false positives |
| LSR03 Driving | 12/197 | 0.45 | 0/79 regression | n/a | n/a | n/a | Retrained after four supported annotation corrections; no positive evaluation support remains |
| LSR04 Energy Isolation | 19/190 | 0.35 | 4/75 historical | 1.000 | 0.250 | 0.400 | Unchanged v0.2 |
| LSR05 Hot Work | 13/196 | 0.25 | 1/78 historical | 0.500 | 1.000 | 0.667 | Unchanged v0.2 |
| LSR06 Line of Fire | 121/88 | 0.55 | 18/61 historical | 0.750 | 0.500 | 0.600 | Unchanged v0.2 |
| LSR07 Safe Mechanical Lifting | 16/193 | 0.50 | 6/73 historical | 0.500 | 0.333 | 0.400 | Unchanged v0.2 |
| LSR08 Work Authorisation | 0/209 base + 2 reviewed | n/a | n/a | n/a | n/a | n/a | Unavailable: support below minimum |
| LSR09 Working at Height | 33/176 | 0.45 | 26/54 historical | 0.839 | 1.000 | 0.912 | Unchanged v0.2 |

LSR03’s old zero F1 was not a model miss: the sole benchmark “positive” was a
guy-wire fall with no driving. Three other pattern collisions included “drive
belt,” a manually pushed cart, and a fall onto a truck. The corrected development
set has two positives and 50 negatives, but no corrected positive remains in the
regression benchmark.

The experimental LSR artifact covers eight rules, but is not promoted. LSR02’s
tiny holdout has zero specificity, generic text produced unsupported LSR01
assignments during runtime probing, and the artifact was trained with
scikit-learn 1.8 while the backend environment has 1.9. The active v0.2 mapper
therefore continues to disclose LSR01, LSR02, and LSR08 as unavailable. Missing
evidence and low scores are never presented as proof that a rule is irrelevant
or that no violation occurred.

## Runtime, cost, and rollback

Runtime code and active artifacts did not change, so the v0.2 benchmark is
reused: uncached full API median/p95 90.53/144.90 ms, cached duplicate API
45.45/64.32 ms, warm SIF 2.84/6.48 ms, and warm LSR 2.17/8.94 ms. Runtime
generative-LLM calls and token charges remain zero. No comparable authorised LLM
benchmark exists, so relative speed, cost, and quality remain unmeasured.

Run the frozen phases from the repository root:

```powershell
python 03-training/ml/sif_v0_1/src/run_bounded_iteration_v0_3.py prepare
python 03-training/ml/sif_v0_1/src/run_bounded_iteration_v0_3.py train
python 03-training/ml/sif_v0_1/src/run_bounded_iteration_v0_3.py evaluate
python 03-training/ml/sif_v0_1/src/run_bounded_iteration_v0_3.py finalize
```

No rollback action is required because nothing was promoted. `MODEL_PATH`
continues to resolve to `artifacts/supervised`, and the backend default LSR path
continues to resolve to `artifacts/domain_adapted_v0_2/lsr_model.joblib`.
