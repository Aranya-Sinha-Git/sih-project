# Domain v0.2 diagnosis and demo-readiness report

> The 90-report prototype test is a diagnostic regression benchmark, not fresh blind validation. No labels were changed and no model was fitted by this diagnosis.

## SIF regression metrics

| Model | TP | FP | TN | FN | Recall | Precision | Specificity | Balanced accuracy | F2 | Pred Non-SIF | Pred SIF | Review rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Active baseline v0.1 | 47 | 21 | 19 | 3 | 0.940 | 0.691 | 0.475 | 0.708 | 0.877 | 22 | 68 | 7.8% |
| TF-IDF candidate v0.2 | 50 | 40 | 0 | 0 | 1.000 | 0.556 | 0.000 | 0.500 | 0.862 | 0 | 90 | 0.0% |
| SetFit candidate v0.2 | 45 | 16 | 24 | 5 | 0.900 | 0.738 | 0.600 | 0.750 | 0.862 | 29 | 61 | 1.1% |
| All-SIF reference | 50 | 40 | 0 | 0 | 1.000 | 0.556 | 0.000 | 0.500 | 0.862 | 0 | 90 | n/a |
| All-Non-SIF reference | 0 | 0 | 40 | 50 | 0.000 | 0.000 | 1.000 | 0.500 | 0.000 | 90 | 0 | n/a |

SetFit had no frozen operational review band; its review rate uses a diagnostic threshold ±0.05 band (0.20–0.30) and is not a deployed-routing claim.

## Diagnosis

- **F2-only development selection rewarded the trivial class:** Development prevalence is 0.804. The selected TF-IDF point predicts all 92 rows SIF, has specificity 0 and F2 0.954, exactly the all-SIF development F2.
- **Threshold/model score-scale mismatch after refit:** The threshold was chosen from a train-only model, then the saved TF-IDF vectorizer and classifier were re-fitted on train+development. The saved candidate intercept is 1.373 versus 0.630 for the baseline, and all 90 regression scores exceed 0.25.
- **Development/test prevalence and provenance differ:** Train/development are 80.8%/80.4% SIF, versus 55.6% in the deliberately balanced regression set. All are OSHA_SIR, but the test labels use a separate deterministic AI-assisted prototype process and reports are shorter.

## Active-model decision

Retain active baseline v0.1. The TF-IDF candidate fails the corrected development gates; SetFit remains a saved comparison candidate and is not promoted from the now-diagnostic 90-row benchmark. No replacement was selected, so no fresh final set was opened or manufactured.

## LSR coverage

| Rule | Status | Train P/N/U | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|
| LSR01 | unavailable | 0/209/160 | n/a | n/a | n/a |
| LSR02 | unavailable | 1/208/160 | n/a | n/a | n/a |
| LSR03 | trained | 14/195/160 | 0.000 | 0.000 | 0.000 |
| LSR04 | trained | 19/190/160 | 1.000 | 0.250 | 0.400 |
| LSR05 | trained | 13/196/160 | 0.500 | 1.000 | 0.667 |
| LSR06 | trained | 121/88/160 | 0.750 | 0.500 | 0.600 |
| LSR07 | trained | 16/193/160 | 0.500 | 0.333 | 0.400 |
| LSR08 | unavailable | 0/209/160 | n/a | n/a | n/a |
| LSR09 | trained | 33/176/160 | 0.839 | 1.000 | 0.912 |

Unavailable rules are omitted from aggregate metrics; they are never counted as confident negatives. Existing duplicate-isolated records contain possible LSR01/LSR02 evidence candidates, but no accepted annotations were manufactured and LSR01/02/08 remain unavailable.

## Demo readiness

Focused API/runtime cases passed. Remeasured runtime benchmark: uncached API median/p95 90.53/144.90 ms; batch throughput 12.26 reports/s. Runtime generative LLM calls: 0.

Remaining limitations: no fresh independent assessment supports promoting either candidate; labels are AI-assisted prototype references; three LSR rules are unavailable, so MAPPING_UNAVAILABLE takes precedence over an insufficient-information zero status; and no measured equivalent-output LLM comparison exists.
