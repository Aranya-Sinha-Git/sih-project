# Data schema

`incidents`: `id`, `report_date`, `site`, `activity`, `report_type` (`Unsafe Act`, `Unsafe Condition`, `Near Miss`, `Incident`, or `Unspecified`), `narrative`, `source`, `import_batch_id`, `sif_probability`, `risk`, `high_potential`, `sif_potential`, `sif_label_status`, `analysis`, review fields and timestamp.

`sif_label_status` is `expert_reviewed`, `manual_reviewed`, `weak_label`, `synthetic`, or `unresolved`. If only high potential is known: `high_potential=1`, `sif_potential=null`, `sif_label_status=unresolved`.

Rules-classified reports store an explicit classification in `analysis.classification`: `SIF Potential`, `Non-SIF Potential`, or `Needs Review`. The score is a transparent prototype signal, not a calibrated probability.
