# Standalone 100-report judge demo corpus

Status: synthetic presentation corpus (`synthetic_judge_demo_100_v0_1`). It is not a validation dataset and must not be used as accuracy, calibration, or external-validation evidence.

The dataset contains a deterministic stratified selection of 100 fictional industrial-safety reports from the synthetic 500-report judge-demo corpus, with separate IDs and provenance. All sites and events are fictional. It contains no real people, Oil India events, confidential records, or blind-test records. Use it as an alternative standalone upload; do not combine it with the 500-report version in the same workspace.

Upload `judge_demo_100.csv` or `outputs/judge_demo_100_20260912/judge_demo_100.xlsx` through Analyze report. The seven upload fields are `report_id`, `report_date`, `site`, `activity`, `report_type`, `narrative`, and `source`. Dates cover 2026-07-20 through 2026-09-11. Narratives contain 70–140 words.

Observed current-runtime coverage is High 32, Medium/review 24, and Low 44. These are uncalibrated screening outputs included only to verify that the application can display all routing states. No predictions, scores, retrieval results, explanations, or reviewer labels are present in the upload files.

The corpus is independent from the frozen human-validation releases under `03-training/ml/sif_v0_1/data/blind_test_v0_2` and `blind_test_v0_3`. Those releases are neither read nor modified by this generator.
