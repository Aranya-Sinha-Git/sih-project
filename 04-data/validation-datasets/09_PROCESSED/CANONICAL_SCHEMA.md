# Canonical schema

`record_id`, `source`, `source_record_id`, `source_document`, `source_year`, `event_date`, `country`, `region`, `site`, `location`, `company_if_public`, `report_type`, `function`, `activity`, `equipment`, `narrative`, `what_went_wrong`, `cause`, `causal_factors`, `corrective_actions`, `hazards`, `precursors`, `barrier_failures`, `primary_life_saving_rule`, `secondary_life_saving_rules`, `fatality`, `injury`, `injury_severity`, `high_potential`, `sif_potential`, `sif_label_status`, `source_native_classification`, `source_native_outcome`, `real_or_synthetic`, `provenance_quality`.

Value provenance must be distinguished as SOURCE_NATIVE, NORMALIZED, DERIVED, or MODEL_LABEL in future source-specific views. Missing fields stay blank. High potential, fatality, severe injury, near miss, and no injury do not imply a generic SIF label.
