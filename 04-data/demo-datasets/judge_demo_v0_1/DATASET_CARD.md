# Judge demo corpus v0.1

Status: synthetic presentation corpus (`synthetic_judge_demo_v0_1`). This dataset is not a validation dataset and must not be used as accuracy, calibration, or external-validation evidence.

## Boundary

All 500 records are deterministic fictional demonstrations generated with seed `26165` by `judge_demo_generator_v0.1`. They contain no real people, Oil India events, confidential records, or copied blind-test narratives. The frozen human-validation releases under `03-training/ml/sif_v0_1/data/blind_test_v0_2` and `blind_test_v0_3` are outside this directory and are not modified by the generator.

The upload files contain only `report_id`, `report_date`, `site`, `activity`, `report_type`, `narrative`, and `source`. They contain no precomputed predictions, AI labels, model scores, retrieval results, explanations, or reviewer fields. The QA matrix is a sidecar and must not be uploaded.

## Design quotas

- Reports: 500. Report IDs are stable from `DEMO500-0001` through `DEMO500-0500`.
- Report types: Near Miss 180, Unsafe Condition 130, Incident 100, Unsafe Act 90.
- Sites: Aurora Basin 100, Blue Mesa Yard 90, Cedar Ridge Station 85, Delta Point Facility 80, Echo Valley Works 75, Frostline Depot 70.
- Activities: Valve Maintenance 90, Mechanical Lifting 75, Drilling 65, Pressure Testing 60, Driving 60, Hot Work 55, Inspection 50, Electrical Maintenance 45.
- Weekly groups from `2026-07-20` through `2026-09-11`: 50, 55, 55, 60, 65, 70, 70, 75.
- Primary scenario families include energy isolation 65, line of fire 60, mechanical lifting 55, driving 50, hot work 50, working at height 45, confined space 35, work authorization 35, bypassed safety controls 25, and routine work 80.
- Narrative length is designed for 70–140 words and normally seven or eight sentences. Every narrative names a fictional work area, task stage, equipment or energy source, observation, exposure position, expected barrier, barrier state, outcome or credible potential, and response.

## Runtime coverage

The generator profiles the finished narratives through the active deployed SIF classifier, active LSR mapper, and structured extraction path. The observed screening distribution is High 32.0%, Medium/review 24.0%, and Low 44.0%. These are presentation-coverage observations, not prevalence claims or labels.

The profile records supported-rule examples, explicit unavailable-rule examples, recurring precursor cohorts, related nonduplicate cohorts, extraction coverage, trend coverage, active artifact hashes, and timing. Similar-report retrieval is intentionally exercised after persistence on detail reads; the batch path does not scan the incomplete corpus once per row. Alerts remain empty unless a genuine data-derived alert policy is enabled.

The corpus was selected to exercise dashboard, six-week trend, site, activity, report-type, intelligence, multi-rule evidence, historical similarity, review queue, and model/evidence UI states. It is not representative of field prevalence.

## Rebuild and use

Run `python 04-data/demo-datasets/judge_demo_v0_1/generate_judge_demo.py`, then `node 04-data/demo-datasets/judge_demo_v0_1/build_judge_demo_xlsx.mjs`, and finally `python 04-data/demo-datasets/judge_demo_v0_1/finalize_judge_demo_manifest.py` to refresh the versioned artifacts. Verify `/ready`, use a clean demo workspace, and upload `judge_demo_500.xlsx`. The expected demonstration summary is 500 processed and 0 skipped on the first upload. A retry with the same stable IDs is expected to report duplicates rather than add another 500 records.
