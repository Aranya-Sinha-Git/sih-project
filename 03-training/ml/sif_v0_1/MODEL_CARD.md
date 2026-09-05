# Model Card — SIF NLP v0.1

## Status

`AI_ASSISTED_SUPERVISED_PROTOTYPE`. This is an internal AI-assisted supervised prototype, not an expert-validated or production-approved model.

## Intended use

Narrative-only triage of reports for possible SIF potential. It must not approve work, replace safety procedures, or replace human/HSE review.

## Training data

The training set has 449 accepted AI-assisted binary labels: 365 `SIF_POTENTIAL` and 84 `NON_SIF_POTENTIAL`. It was created through dual/three-pass AI labeling. The 51 unresolved records were excluded. Labels are not HSE expert ground truth and are from `OSHA_SIR`, so source/domain transfer limits apply.

## Models

- TF-IDF word 1–2 grams, with an evaluated character n-gram variant, followed by class-weighted Logistic Regression.
- Frozen `sentence-transformers/all-MiniLM-L6-v2` sentence embeddings with attention-mask mean pooling and class-weighted Logistic Regression. The encoder was not fine-tuned.

The selected prototype is `tfidf_word_12_char_35` at internal threshold 0.40. `sif_score` is an uncalibrated model score, not a validated probability. Scores in the 0.35–0.45 band require human review.

## Evaluation and limitations

Internal validation is a duplicate-safe grouped split with fixed seed 26165. Metrics measure agreement with AI-assisted consensus labels, not validated SIF outcomes. There is no external human/HSE validation and IOGP 2025 was not used or modified. Before operational use, obtain expert labels, validate externally, assess calibration and false-negative performance, and run shadow-mode HSE review.
