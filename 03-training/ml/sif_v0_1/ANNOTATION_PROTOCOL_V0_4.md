# GPT-5.6 Sol annotation protocol v0.4

This protocol applies only to the versioned expansion under
`data/domain_adaptation_v0_4`. It does not change the original teammate data or
the frozen human-validation releases. These labels are AI-assisted prototype
references, not HSE expert ground truth.

## Inputs and independence

- Read the repository `SIF_LABELING_GUIDE.md` and
  `reference/iogp_life_saving_rules_v2018.json` before annotating.
- Read each complete narrative in the assigned immutable input batch.
- Do not use source-native outcome fields as targets. They are context only.
- Do not inspect model predictions, scores, prior annotations, or adjudications.
- The second pass receives narratives and identifiers only. It must not inspect
  first-pass labels or rationales.

## SIF judgment

Choose exactly one target:

- `SIF_POTENTIAL`: the narrative itself supports a credible fatal or
  life-altering/permanent serious-injury consequence, with actual or credible
  personnel exposure to the stated hazard.
- `NON_SIF_POTENTIAL`: the narrative provides enough detail to assess the event
  and does not support credible SIF potential.
- `UNCERTAIN`: required exposure, barrier, energy, or consequence detail is
  missing or the policy cannot resolve the case.

Do not invent height, voltage, pressure, speed, load, atmosphere, barrier
failure, exposure, or consequence. Do not label from hospitalization,
amputation, fatality, “near miss,” or another source-native outcome alone. The
mechanism and supported credible potential control the judgment.

Record an exact narrative substring in `sif_evidence_excerpt` for each binary
label. Keep the rationale concise and tied to that excerpt. Record each of
hazard/energy, personnel exposure, barrier failure, and credible consequence as
`SUPPORTED`, `NOT_SUPPORTED`, or `UNKNOWN`, with an exact evidence substring
when one exists. Use `uncertainty_reason` only when something material remains
unknown.

## IOGP Life-Saving Rules

For every rule, choose `POSITIVE`, `NEGATIVE`, or `UNKNOWN`:

- `POSITIVE` means the official rule is relevant to the activity or exposure.
- `NEGATIVE` means the narrative is sufficiently clear and the rule is not
  relevant.
- `UNKNOWN` means the narrative lacks the detail needed to assess relevance.

Positive relevance does not prove a violation. Record violation status
separately as `ESTABLISHED`, `NOT_ESTABLISHED`, or `UNKNOWN`. Use
`ESTABLISHED` only when the narrative explicitly supports the missing,
defeated, bypassed, or breached control. Every positive target requires an exact
evidence excerpt. Unknown targets require a brief reason; an empty annotation is
never interpreted as negative.

Apply the official definitions, including these collision safeguards:

- A drive belt is machinery, not LSR03 Driving.
- A guy wire does not establish driving.
- Being on or near a truck does not establish that anyone was driving.
- A tank, pit, or vessel is not automatically a confined space unless entry or
  work within the space is supported.
- A generic injury, repair, procedure, or authorisation word does not establish
  Work Authorisation.
- A crane or forklift mention does not establish Safe Mechanical Lifting unless
  a lifting/load-control activity is described.
- A hazard keyword alone never establishes a rule violation.

## Output schema

Write one CSV row per input record, in input order, with these columns:

`expansion_id`, `candidate_id`, `normalized_narrative_sha256`,
`annotation_pass`, `sif_label`, `sif_evidence_excerpt`, `sif_rationale`,
`hazard_energy_assessment`, `hazard_energy_evidence`,
`personnel_exposure_assessment`, `personnel_exposure_evidence`,
`barrier_failure_assessment`, `barrier_failure_evidence`,
`credible_consequence_assessment`, `credible_consequence_evidence`,
`uncertainty_reason`, then for each `LSR01` through `LSR09`:
`<rule>_target`, `<rule>_evidence`, `<rule>_violation_status`,
`<rule>_unknown_reason`, followed by `annotation_status`, `label_provenance`,
`annotation_version`, `annotator_model`, `annotator_id`, and
`annotated_at_utc`.

Use `annotation_status=completed` when all required targets are present, even if
some targets are explicitly unknown. Use `unresolved` when the SIF label is
`UNCERTAIN` or a material conflict remains. Use
`label_provenance=AI_ASSISTED_GPT_5_6_SOL_NOT_HSE_GROUND_TRUTH`,
`annotation_version=gpt-5.6-sol-ai-assisted-v0.4.0`, and
`annotator_model=gpt-5.6-sol`.

Validate before saving:

- IDs and narrative hashes exactly match the input.
- Every evidence excerpt is an exact substring of the narrative.
- Every positive rule has evidence.
- Every unknown rule has an unknown reason.
- No required target cell is blank.
