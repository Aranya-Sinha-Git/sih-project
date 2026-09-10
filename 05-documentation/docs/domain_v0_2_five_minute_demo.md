# Five-minute domain v0.2 demo

These illustrative narratives are not drawn from a locked evaluation set.

1. Start the backend and frontend, then open **Analyze report**.
2. Clear SIF and multi-rule mapping: “A hopper being lifted by a forklift fell
   on a worker standing beside the load.” Show the SIF score, human-review
   routing, LSR06/LSR07 mappings, exact excerpt and model/reference versions.
3. Single mapping with an explicit control failure: “The technician contacted
   an energized wire after lockout was not applied.” Show LSR04 and the separate
   violation status.
4. Non-SIF and zero/partial coverage: “A worker walking across a muddy yard
   slipped and twisted an ankle.” Show the Non-SIF route, `MAPPING_UNAVAILABLE`,
   the unsupported LSR01/LSR02/LSR08 classifiers and the warning that zero
   mappings do not imply Non-SIF or safety.
5. Human review and negation: compare “An employee took measurements while
   standing on an earthen berm, lost balance, and fractured an ankle” with
   “There were no dropped objects and isolation was verified before work began.”
   Show the review route and that negated text creates neither fabricated
   evidence nor an established violation.
6. Open the review queue, save **Escalate / Unsure**, then resolve it and reload
   the report to demonstrate persisted adjudication history.
7. Analyze a related second report and show similar-incident retrieval. Finish
   on **Model & evidence** and quote the measured uncached median/p95 API latency
   (90.53/144.90 ms), 12.26 reports/s batch throughput, and zero runtime LLM calls.

These examples are synthetic illustrations, not members of any protected or
locked evaluation release. The active v0.1 artifact emits an
`InconsistentVersionWarning` under the current scikit-learn runtime; the demo
loads successfully, but re-serialization under a pinned supported version is a
remaining maintenance item rather than evidence of model quality.
