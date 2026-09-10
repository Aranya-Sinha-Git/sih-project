# Project Decision Log

This is the canonical log for major decisions affecting the wider SIF Sentinel
project, repository/agent workflows, and validation. Keep implementation details
in the relevant README or design document; record the decision, rationale, and
scope here.

## How to record a decision

Add a dated entry with:

- **Status:** proposed, accepted, superseded, or rejected
- **Decision:** what was chosen
- **Rationale:** why it was chosen
- **Scope:** the systems, workstreams, or artifacts affected

## Project-wide decisions

### 2026-09-05 — Preserve the application architecture

- **Status:** accepted
- **Decision:** Keep the deployable application flow as `Next.js → FastAPI →
  frozen classifier / retrieval / analytics / review`.
- **Rationale:** The migration is intended to preserve the existing application
  architecture while changing persistence and deployment details.
- **Scope:** `01-app`, the deployed application, and its ML/review integration.

### 2026-09-05 — Use Supabase for persistence and authentication

- **Status:** accepted
- **Decision:** Use Supabase PostgreSQL and Auth for the application; retain
  FastAPI as the ML/runtime boundary rather than replacing it with Supabase.
- **Rationale:** This separates hosted persistence/authentication from the
  classifier, retrieval, analytics, and review runtime.
- **Scope:** `01-app`, Supabase migrations, deployment, and local migration
  tooling.

### 2026-09-05 — Keep workstreams separated

- **Status:** accepted
- **Decision:** Maintain separate workstreams for the application (`01-app`),
  labeling (`02-labeling`), training/evaluation (`03-training`), data
  (`04-data`), and documentation (`05-documentation`).
- **Rationale:** The separation preserves clear ownership and prevents changes
  in one workflow from silently changing another.
- **Scope:** Repository layout and cross-workstream changes.

## Agent and repository decisions

### 2026-09-05 — Treat frozen validation artifacts as immutable

- **Status:** accepted
- **Decision:** Preserve the historical v0.2 human-validation release and the
  v0.3 release-candidate packet and freeze manifest; official finalization must
  use the prescribed artifacts and attestation flow.
- **Rationale:** Blind-test identity, reviewer blinding, and evaluation
  integrity depend on immutable canonical artifacts.
- **Scope:** `03-training/ml/sif_v0_1`, especially blind-test packets, manifests,
  evaluation, calibration, and metrics.

### 2026-09-05 — Use the canonical manifest as blind-test authority

- **Status:** accepted
- **Decision:** Blind-test membership and identity come only from the canonical
  freeze manifest; mismatched IDs, source IDs, narrative hashes, packet hashes,
  artifacts, configuration, thresholds, or aliases must be rejected.
- **Rationale:** A caller-created or altered manifest could invalidate the blind
  boundary and contaminate reported results.
- **Scope:** Blind-test construction, human review, finalization, attestation,
  and official evaluation.

## Validation decisions

### 2026-09-10 — Retain v0.1 SIF screening and deploy offline v0.2 LSR mapping

- **Status:** accepted
- **Decision:** Keep the frozen v0.1 TF-IDF model and its 0.35–0.45 review band
  as the active SIF screen. Retain the trained v0.2 TF-IDF and SetFit candidates
  as comparison artifacts because the selected candidate failed the protected
  test quality gate. Add the v0.2 offline multilabel LSR mapper with explicit
  unknown, borderline and unavailable states; disable runtime generative LLM
  calls.
- **Rationale:** The candidate’s protected-test F2 (0.862) was below the
  baseline (0.877) and it classified all 40 Non-SIF references as SIF. The LSR
  model adds traceable relevance/evidence while preserving unsupported-rule
  uncertainty, low latency and zero token charges.
- **Scope:** SIF/LSR artifacts and runtime integration in `01-app` and
  `03-training/ml/sif_v0_1`. Frozen human-validation releases remain unchanged.

### 2026-09-10 — Reject F2-only SIF operating-point selection

- **Status:** accepted
- **Decision:** Keep v0.1 active; treat the existing 90-report prototype set as
  a regression benchmark, not fresh blind validation. Require a development
  candidate to meet explicit recall, specificity, balanced-accuracy,
  precision-over-all-SIF and review-workload gates. Fit the final candidate on
  the same training partition used to establish its score scale unless a
  separately leakage-free calibration procedure is frozen.
- **Rationale:** The v0.2 TF-IDF search selected the all-SIF development result
  because F2 alone rewarded the 80.4% positive prevalence. Refitting on train
  plus development then shifted scores while retaining the train-only
  threshold. Saved scores show useful ranking but a failed operating point;
  class encoding and probability-column mapping are correct. No saved TF-IDF
  operating point passes the corrected gates, and SetFit has no fresh final
  assessment supporting promotion.
- **Scope:** SIF candidate selection, thresholding, diagnostic reports and
  runtime candidate preprocessing. Frozen v0.2/v0.3 human-validation releases
  and active baseline artifacts are unchanged.

### 2026-09-10 — Retain active models after bounded v0.3 iteration

- **Status:** accepted
- **Decision:** Keep the v0.1 SIF screen and v0.2 LSR mapper active. Preserve
  the train-only v0.3 TF-IDF model, the reused SetFit checkpoint operating
  point, and the eight-rule v0.3 LSR artifact as experimental evidence only.
- **Rationale:** Corrected TF-IDF thresholding removed the all-SIF collapse but
  its best development tradeoff failed the 0.90 recall gate. SetFit passed the
  prototype development gates, then underperformed the active baseline on the
  one-time frozen 100-report AI-assisted assessment (F2 0.843 vs 0.894; recall
  0.900 vs 0.980) and is not supported by the real backend adapter. LSR01 and
  LSR02 gained evidence-supported training examples, but their holdouts are too
  small and LSR02 classified both holdout negatives as positive. Only two
  supported LSR08 examples were found, below the minimum of three.
- **Scope:** `domain_adaptation_v0_3` data, reports and experimental artifacts.
  The 90-report set remains diagnostic, frozen human-validation releases are
  unchanged, and runtime continues to make zero generative-LLM calls.

Date: 2026-09-05

## Blind-test status

The current `03-training/ml/sif_v0_1/data/blind_test` release is **not approved** for reporting an uncontaminated blind-test result. Its shipped packet and manifest do not satisfy the current human evaluator's required contract.

## Release gates

Do not score, calibrate against, rename, rebuild, or report this blind set until all of the following are complete:

1. Publish one immutable, canonical freeze manifest before human review. It must contain exact test IDs, source IDs, normalized-narrative hashes, packet hashes, model artifact hash, configuration hash, binary threshold, and review band.
2. Require the evaluator to verify that canonical manifest and packet hashes; do not accept a caller-created replacement manifest as the authority.
3. Regenerate or migrate the reviewer packet to include both reviewer identities, review dates, confidences, adjudication lock state, adjudicator identity/date, and an exclusion reason where applicable.
4. Make every configured validation-lock column mandatory. Missing lock columns must fail the builder rather than disable record-level locking.
5. Block calibration use by canonical test/source IDs, candidate IDs, and narrative hashes; calibration data must be independently frozen and disjoint.
6. Add an integration test that evaluates the actual released packet and manifest, including negative tests for altered IDs, narratives, hashes, artifact/configuration, thresholds, and aliases.

## Permitted use before remediation

The current files may be inspected for provenance and schema migration only. They must not be presented as external-validation results or used to select a model, threshold, calibration rule, or release claim.
