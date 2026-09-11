# Demo readiness v0.4

The demo uses the active v0.1 SIF screen and v0.2 LSR mapper. The v0.4 TF-IDF,
SetFit, and nine-rule LSR artifacts remain offline experimental comparisons and
are not loaded by the live service.

## Readiness checklist

- Active SIF: `sif-v0.1`, `tfidf_word_12_char_35`, raw uncalibrated score,
  binary threshold 0.40, review band 0.35–0.45.
- Active LSR: `iogp-lsr-v0.2`, IOGP Report 459 revised 2018 reference.
  Available: LSR03 Driving, LSR04 Energy Isolation, LSR05 Hot Work, LSR06 Line
  of Fire, LSR07 Safe Mechanical Lifting, LSR09 Working at Height.
  Unavailable: LSR01 Bypassing Safety Controls, LSR02 Confined Space, and LSR08
  Work Authorisation. Unavailable is not a negative.
- Rule display: a confident mapping requires a model threshold plus a
  criterion-aligned narrative excerpt; a mapping is not proof of a violation.
- Retrieval: public reference evidence and similar stored incidents are
  deterministic TF-IDF retrieval with provenance; no runtime generative LLM is
  configured or called.
- Human review: reviewer outcome and audit history are persisted separately
  from the model screening result.

## Uncertain-row inspection

The exact scores and routes are saved in
`uncertain_routing_v0_4.json`. They are descriptive only; the 18 rows have no
binary correctness target.

| Artifact family | Auto SIF | Auto Non-SIF | Human review |
|---|---:|---:|---:|
| Active baseline v0.1 | 17/18 | 0/18 | 1/18 |
| TF-IDF v0.4 experimental | 11/18 | 3/18 | 4/18 |
| SetFit v0.4 experimental | 10/18 | 7/18 | 1/18 |

Across all 150 fresh-final rows, descriptive review workload is 14/150 for the
active baseline, 15/150 for TF-IDF v0.4, and 2/150 for SetFit v0.4. The active
baseline's 17/18 automatic SIF routes show that uncertainty handling is not a
measured strength of the deployed screen. The ten insufficient-information
reasons are supported by their narratives; the eight disagreement reasons are
metadata about unresolved annotator disagreement, not missing-information
explanations.

## Illustrative inputs

Use these examples, not any fresh-final assessment record:

| Demo case | Expected active behaviour |
|---|---|
| SIF potential | Energized 13,800-volt power-line contact with severe burns → SIF potential and evidence-backed Energy Isolation where stated. |
| Non-SIF | Muddy-yard ankle twist → Non-SIF potential or review depending score; never infer safety from zero rules. |
| Insufficient information | Fall from an earthen berm with no height → human review when in-band; missing detail is not invented. |
| Multiple relevant rules | Hopper lifted by forklift falls on a worker → multiple LSR06/LSR07 nominations with excerpts. |
| Zero or incomplete mapping | Routine office housekeeping → no confident mapping; `MAPPING_UNAVAILABLE` discloses incomplete coverage. |
| Persisted adjudication and retrieval | Review a stored incident, then reopen it → Audit history shows the human outcome and Similar historical reports shows deterministic matches when present. |

The active mapper's former contextual collision cases were checked. Drive-belt
and generic-maintenance text no longer becomes a confident Hot Work mapping
without supporting evidence; an evidence-backed driving example remains
available. This is a post-processing evidence guard, not an LSR artifact
promotion.

Focused backend regression tests passed: 47 tests. Runtime inference was
changed only in the evidence-gating step, so the existing measured v0.2
uncached API median/p95 remains 90.53/144.90 ms at concurrency one. Runtime
generative-LLM calls and token charges remain zero. No comparative LLM latency,
cost, or quality claim is made.
