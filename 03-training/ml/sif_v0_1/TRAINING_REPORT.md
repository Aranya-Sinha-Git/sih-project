# SIF NLP v0.1 Training Report

## Data and safeguards

- Training rows: 449 accepted binary AI-assisted labels (365 SIF potential; 84 Non-SIF potential).
- Excluded: 51 unresolved records. No unresolved record was trained on.
- Label methodology: dual-pass consensus plus Pass C triple confirmation or 2-of-3 majority adjudication.
- Label status: `AI_ASSISTED_CONSENSUS`. These labels are not HSE expert ground truth.
- Model input: narrative only. IDs, source, source-record metadata, provenance, confidence, agreement pattern and labels were excluded from model features.
- Split: reproducible grouped stratified internal split, seed 26165; 359 train / 90 validation; event-group overlap 0.
- External validation: not performed. IOGP 2025 remained locked and untouched.

## Internal agreement-to-consensus validation

These values measure reproduction of AI-assisted consensus labels on the internal validation partition; they are not validated real-world SIF accuracy.

| Model | Selected threshold | Recall | Precision | F2 | FNR | PR-AUC | ROC-AUC | False negatives |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TF-IDF (`tfidf_word_12_char_35`) | 0.40 | 0.9863 | 0.8571 | 0.9574 | 0.0137 | 0.9787 | 0.9049 | 1 |
| Frozen embeddings (`sentence-transformers/all-MiniLM-L6-v2`) | 0.45 | 0.9178 | 0.9054 | 0.9153 | 0.0822 | 0.9760 | 0.8993 | 6 |

## Prototype selection

Selected model: `tfidf_word_12_char_35` at threshold 0.40 (recall 0.9863; precision 0.8571; F2 0.9574; false negatives 1). The decision rule prioritised SIF recall, false-negative rate, F2, precision and F1 in that order. Scores are not probability-calibrated. Scores within 0.35–0.45 are returned as `HUMAN_REVIEW`.

Human/HSE validation, calibration and external evaluation remain required before any operational use.
TF-IDF features are exported only as statistical associations, not causal explanations.
