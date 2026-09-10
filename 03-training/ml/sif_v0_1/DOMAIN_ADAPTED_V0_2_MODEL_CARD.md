# Domain-adapted prototype v0.2

## Intended use and status

This is an AI-assisted development prototype for SIF-potential screening and
IOGP Life-Saving Rule relevance. It supports, but does not replace, qualified
human review. Scores are model scores, not calibrated probabilities. The
existing v0.1 TF-IDF SIF classifier remains active because the v0.2 SIF
candidate failed its predeclared protected-test promotion gate. The v0.2 LSR
mapper is active with explicit partial-coverage handling.

## Data and labels

- Original teammate export: 369 rows (213 SIF, 94 Non-SIF, 62 uncertain), read
  only; SHA-256 `9fba…30e3`.
- Conservative secondary review: 65 narrative-supported missed-SIF corrections
  and two SIF-to-uncertain corrections. Revised counts: 276 SIF, 65 Non-SIF,
  28 uncertain. These are AI-assisted labels, not HSE expert ground truth.
- Merged development population: 500 unique incident IDs; 461 binary rows and
  39 unresolved rows retained outside binary supervision.
- Group-safe split: 369 train, 92 development. The separate 90-row prototype
  set contains 50 SIF and 40 Non-SIF labels created by deterministic policy
  checks without model predictions. It has informed failure diagnosis and is
  now a regression benchmark—not fresh blind or external validation.
- Input allowlist: narrative text only. Labels, model scores, adjudications,
  explanations, source-native outcomes and human-assigned LSRs are excluded.
- Canonical blind-test v0.2/v0.3 IDs, source IDs and normalized narrative hashes
  are excluded and their releases were not changed.

## Models actually trained

- TF-IDF word 1–2 and character 3–5 n-grams with Logistic Regression. A bounded
  search covered `C`, class weighting, decision threshold and review-band width.
  Development precision/recall/F2: 0.804/1.000/0.954 at the selected recall-heavy
  threshold.
- SetFit with `sentence-transformers/all-MiniLM-L6-v2`: one real encoder
  fine-tuning epoch, 8 contrastive iterations, oversampling and batch size 16.
  Training took 87.7 s on CUDA. Development precision/recall/F2:
  0.883/0.919/0.912. One of 461 reports was 263 tokens and was explicitly
  truncated to the configured 256-token limit.
- Separate multilabel LSR TF-IDF/Logistic Regression models with unknown targets
  masked per rule. Six rules are trained; LSR01, LSR02 and LSR08 are unavailable
  because positive support was insufficient.

## Regression diagnosis and promotion

Binary classification and routing are reported separately; review cases are
not counted as correct classifications.

| SIF model | Precision | Recall | Specificity | Balanced accuracy | F2 | TP / FP / TN / FN | Review rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Active baseline v0.1 | 0.691 | 0.940 | 0.475 | 0.708 | 0.877 | 47 / 21 / 19 / 3 | 7.8% |
| v0.2 TF-IDF candidate | 0.556 | 1.000 | 0.000 | 0.500 | 0.862 | 50 / 40 / 0 / 0 | 0.0% |
| v0.2 SetFit candidate | 0.738 | 0.900 | 0.600 | 0.750 | 0.862 | 45 / 16 / 24 / 5 | 1.1% |
| All-SIF reference | 0.556 | 1.000 | 0.000 | 0.500 | 0.862 | 50 / 40 / 0 / 0 | n/a |
| All-Non-SIF reference | 0.000 | 0.000 | 1.000 | 0.500 | 0.000 | 0 / 0 / 40 / 50 | n/a |

The TF-IDF candidate ranks cases usefully (regression ROC AUC 0.912), but its
threshold is below every saved score. Development was 80.4% SIF, and F2-only
selection chose an all-SIF operating point whose F2 (0.954) exactly matched the
trivial all-SIF development reference. The threshold was then transferred to a
model refitted on train plus development, which changed the score scale. Class
encoding and probability-column selection were correct. The training code now
requires recall, specificity, balanced accuracy, precision-over-all-SIF and
review-workload gates, and it preserves the train-only fit used for threshold
selection. No saved TF-IDF search point passes those gates, so no retraining or
promotion was justified. SetFit remains a comparison artifact; its results on
the 90 rows are diagnostic only. The baseline remains active.

Full score distributions, ranking metrics, split/provenance checks and cached
row predictions are in `reports/domain_adaptation_v0_2/diagnosis_v0_2.json` and
`sif_regression_predictions_v0_2.csv`.

LSR test summary across 475 known rule cells: micro precision/recall/F1
0.780/0.696/0.736 and macro precision/recall/F1 0.598/0.514/0.496. Per-rule F1:
Driving 0.000, Energy Isolation 0.400, Hot Work 0.667, Line of Fire 0.600,
Safe Mechanical Lifting 0.400, Working at Height 0.912. Thirty-five zero-mapping
cases were inspected; unavailable rules never count as negatives.

## Runtime and explanations

SIF and LSR artifacts load once in one FastAPI process. LSR inference supports
batch transformation. Exact narrative sentences support deterministic
explanations, with negation/hypothetical checks and a separate violation status.
The zero-result precedence is `MAPPING_UNAVAILABLE` →
`INSUFFICIENT_INFORMATION` → `BORDERLINE_MAPPING` →
`NO_CONFIDENT_MAPPING`. The application makes zero runtime generative-LLM calls.

Measured on Windows 11, Ryzen 7 7840HS-class CPU (8 cores/16 threads), 16 GB RAM,
Python 3.13, concurrency 1: cold-start median/p95 4306/4405 ms; warm SIF
2.84/6.48 ms; warm LSR 2.17/8.94 ms; retrieval 1.08/9.01 ms; uncached full API
90.53/144.90 ms; cached duplicate API 45.45/64.32 ms; 50-row batch throughput
12.26 reports/s. Deployed SIF+LSR artifacts are 1,351,094 bytes; end-of-benchmark
RSS was 204,853,248 bytes. No equivalent authorized LLM benchmark existed, so
relative speed/cost is unmeasured. Runtime LLM token charges are zero; hosting,
offline annotation/training and maintenance costs remain.

## Run and rollback

From the repository root:

```powershell
& 'C:\Program Files\Python313\python.exe' 03-training/ml/sif_v0_1/src/train_domain_adapted_v0_2.py
cd 01-app/backend
python -m uvicorn app.main:app --reload
```

The active SIF default is already the v0.1 baseline. To state rollback
explicitly, set `MODEL_PATH=03-training/ml/sif_v0_1/artifacts/supervised` and
restart. To test (not promote) the v0.2 candidate, point `MODEL_PATH` at
`03-training/ml/sif_v0_1/artifacts/domain_adapted_v0_2`.

## Limitations

Labels and LSR targets are AI-assisted; three rule classifiers are unavailable;
several available rules have weak or sparse evaluation support; test labels are
not independent HSE adjudications; baseline serialization was produced with a
newer scikit-learn version than the measured runtime; scores are uncalibrated;
and external blind validation remains pending.
