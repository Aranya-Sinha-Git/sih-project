# Demo readiness v0.4

The demo remains on the active v0.1 SIF and v0.2 LSR artifacts; v0.4 is an
experimental offline expansion and does not alter the live service.

Use illustrative inputs rather than any fresh-final assessment report:

| Demo case | Expected active behaviour |
|---|---|
| Energized high-voltage contact | SIF potential; evidence-supported LSR04 where stated |
| Minor muddy-yard ankle twist | Non-SIF potential or review, depending score; never infer safety from zero rules |
| Sparse fall narrative | Human review; missing details are stated only where a deterministic check supports it |
| Hoisted hopper striking a worker | SIF potential with multiple LSR06/LSR07 mappings and excerpts |
| Office housekeeping narrative | No confident mapping; `MAPPING_UNAVAILABLE` discloses incomplete rule coverage |
| Explicit guard/control present | Supporting excerpts are not presented as a violation solely from a hazard word |
| Missing LSR artifact | `MAPPING_UNAVAILABLE`, not a negative mapping |
| Persisted human adjudication | Existing review history and normal API/UI behaviour remain available |

Focused regression tests passed: 18 data/training tests. Runtime was unchanged,
so the existing measured v0.2 uncached API median/p95 remains 90.53/144.90 ms
at concurrency one; runtime generative-LLM calls and token charges are zero.
No comparative LLM latency, cost, or quality claim is made.
