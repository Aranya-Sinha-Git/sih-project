# Demo readiness v0.3

The demo continues to use the active v0.1 SIF and v0.2 LSR artifacts. The
experimental v0.3 artifacts were not promoted.

| Case | Active SIF result | Active LSR result | Check |
|---|---|---|---|
| Clear SIF: energized 13.8 kV contact | SIF potential | Mapped; incomplete coverage disclosed | Pass |
| Clear Non-SIF: muddy-yard ankle twist | Non-SIF potential | No mapping shown because LSR01/02/08 are unavailable | Pass |
| Uncertain berm fall | Human review | Incomplete coverage disclosed | Pass |
| Single rule: energized wire without lockout | SIF potential | LSR04 with exact narrative evidence | Pass |
| Multiple rules: lifted hopper fell on worker | SIF potential | LSR06 and LSR07 with exact narrative evidence | Pass |
| Zero mapping: office housekeeping | No assigned rule | `MAPPING_UNAVAILABLE`; unsupported rules are not treated as negatives | Pass |
| Negated control/hazard | No extracted LSR06 evidence or violation | Low scores/absent evidence are not stated as proof of irrelevance | Pass |
| Missing LSR artifact | n/a | `MAPPING_UNAVAILABLE` for all nine rules | Pass |

Focused checks completed on 2026-09-10:

- 15 training/data/manifest/label-store tests passed.
- 38 backend/API tests passed, including saved review history and explicit
  dispositions, legacy analysis compatibility, retrieval grounding, and zero
  runtime generative-LLM calls.
- The Next.js 15.5.24 production build passed for all 17 routes.
- The experimental v0.3 LSR artifact loaded through the real service class, but
  runtime probes exposed unsupported LSR01 assignments on generic and negated
  text. Combined with the tiny LSR01/02 holdouts, LSR02 zero specificity, and a
  scikit-learn 1.8/1.9 persistence warning, this artifact is not demo-active.

Runtime code did not change. The existing uncached full-API benchmark remains
90.53 ms median and 144.90 ms p95 at concurrency one. Runtime LLM calls and
token charges remain zero. No comparable authorised LLM benchmark exists.
