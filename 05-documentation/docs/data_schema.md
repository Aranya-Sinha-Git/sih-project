# Data schema

`incidents`: `id`, `report_date`, `site`, `activity`, `report_type` (`Unsafe Act`, `Unsafe Condition`, `Near Miss`, `Incident`, or `Unspecified`), `narrative`, `source`, `import_batch_id`, `sif_probability`, `risk`, `high_potential`, `sif_potential`, `sif_label_status`, `analysis`, review fields and timestamp.

CSV/XLSX batch uploads use the source-labelled columns `report_id`, `report_date`, `site`, `activity`, `report_type`, `narrative`, and `source`. `report_date` is optional and must be an ISO `YYYY-MM-DD` value that is not in the future. Spreadsheet readers also accept `ReportDate` or `date` as date-column aliases. The browser validates each row before sending it, and the API preserves the supplied date through single-report and batch persistence. The synthetic judge corpus in `04-data/demo-datasets/judge_demo_v0_1/` is a presentation-only demo dataset, not validation, calibration, or external-validation evidence.

`sif_label_status` is `expert_reviewed`, `manual_reviewed`, `weak_label`, `synthetic`, or `unresolved`. If only high potential is known: `high_potential=1`, `sif_potential=null`, `sif_label_status=unresolved`.

Rules-classified reports store an explicit classification in `analysis.classification`: `SIF Potential`, `Non-SIF Potential`, or `Needs Review`. The score is a transparent prototype signal, not a calibrated probability.
