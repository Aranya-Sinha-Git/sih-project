# Five-minute domain v0.2 demo

These illustrative narratives are not drawn from a locked evaluation set.

1. Start the backend and frontend, then open **Analyze report**.
2. Clear SIF and multi-rule mapping: “A hopper being lifted by a forklift fell
   on a worker standing beside the load.” Show the SIF score, human-review
   routing, LSR06/LSR07 mappings, exact excerpt and model/reference versions.
3. Single mapping with an explicit control failure: “The technician contacted
   an energized wire after lockout was not applied.” Show LSR04 and the separate
   violation status.
4. Zero/partial coverage: “Routine housekeeping removed paper from an office
   floor with no equipment exposure.” Show `MAPPING_UNAVAILABLE`, the unsupported
   LSR01/LSR02/LSR08 classifiers and the warning that zero mappings do not imply
   Non-SIF or safety.
5. Missing information and negation: compare “Short unclear report about work”
   with “There were no dropped objects and isolation was verified before work
   began.” Show that neither creates fabricated evidence or a violation.
6. Open the review queue, save **Escalate / Unsure**, then resolve it and reload
   the report to demonstrate persisted adjudication history.
7. Analyze a related second report and show similar-incident retrieval. Finish
   on **Model & evidence** and quote the measured uncached median/p95 API latency
   (90.12/149.46 ms), 12.18 reports/s batch throughput, and zero runtime LLM calls.
