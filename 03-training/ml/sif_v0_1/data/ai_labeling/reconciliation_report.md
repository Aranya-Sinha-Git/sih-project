# SIF dual-pass reconciliation report

AI-assisted reconciliation of Pass A and Pass B joined strictly by candidate_id.
No records were relabeled and no model was trained.

## Overall metrics

- Total records: 500
- Exact label agreement: 90.6000%
- Binary agreement (both passes non-UNCERTAIN): 95.7494% (447 comparable)
- Cohen's kappa (three labels): 0.78876
- Cohen's kappa (binary-comparable cases): 0.876553
- SIF/SIF agreements: 339
- Non-SIF/Non-SIF agreements: 89
- Uncertain-containing cases: 53
- Opposite-label disagreements: 19
- High-confidence consensus: 356
- Lower-confidence consensus: 72
- Adjudication queue size: 144
- Training candidates: 356

## Reconciliation statuses

| Status | Count |
|---|---:|
| CONSENSUS_HIGH | 356 |
| CONSENSUS_LOWER_CONFIDENCE | 72 |
| DISAGREEMENT | 19 |
| UNCERTAIN | 53 |

## Agreement by source

| Source | Records | Exact agreement | Binary agreement | Kappa (3-label) |
|---|---:|---:|---:|---:|
| OSHA_SIR | 500 | 90.6000% | 95.7494% | 0.78876 |

All outputs remain AI-assisted; no human-review provenance is assigned.
