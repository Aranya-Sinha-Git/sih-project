# SIH26165 SIF Sentinel application audit

**Audit date:** 2026-09-11

**Audited revision:** `d7c942dbb528c82a897b97867ba2717239e9b9ea` (`main`, equal to `origin/main`)

**Scope:** current application flows, model/runtime behavior, LSR evidence, evaluation/data integrity, persistence/review semantics, reliability/security, browser demo, tests/build.

**Change policy:** audit only. No application code, model artifact, frozen packet, or freeze manifest was changed.

## Executive verdict

The repository contains a coherent working prototype with a real Next.js/FastAPI/Supabase architecture, deterministic retrieval/evidence, review persistence, and strong automated coverage. It is **not ready to present as a fully reliable safety-decision system or as a verified live demo in the current environment**.

The principal blockers are:

1. The browser demo cannot authenticate without a configured and seeded Supabase project; `test / test123` failed in the audited environment.
2. `/health` reports `status: ok` even when the active classifier artifact is missing; the deployment health check can therefore pass while analysis has degraded to null-score human review.
3. The active text classifier routed deliberately safe/negated or generic narratives to SIF Potential in direct regression probes. These are not formal accuracy estimates, but they are unacceptable unqualified demo behavior for safety language.
4. LSR mapping is deterministic and evidence-gated, but its active coverage is incomplete and its mapping channel can disagree with the separate reference-evidence channel shown in the UI.

The official blind-validation boundary remains intact. The v0.2 and v0.3 packets are still blank, hash-valid, and `frozen_unscored`; no human-validation or external-validation claim is supported by this audit.

## Feature/status matrix

| Area | Status | Evidence and limitation |
|---|---|---|
| Authentication and protected workspace | Implemented; live browser flow unverified | Supabase session gates the Next.js workspace; backend rejects unauthenticated requests. The configured browser environment had placeholder Supabase values and could not sign in. |
| Single-report analysis | Working in isolated API run | Validates narrative length/type, screens with the frozen active model, persists an incident, returns retrieval and LSR state. Scores are raw and uncalibrated. |
| TXT/CSV/XLSX batch intake | Working with bounded request count | Browser parses files and posts at most the API’s 500-report batch limit. Duplicate rows are reported and skipped. There is no row-level partial-failure report, file-size cap, or export flow. |
| SIF routing | Operational but unsafe for unqualified interpretation | Active `sif-v0.1` uses `<0.35` Non-SIF, `0.35–0.45` human review, `>0.45` SIF Potential. The score is not calibrated; direct probes exposed false-positive behavior. |
| LSR mapping and excerpts | Partially working | Six rules are available; LSR01, LSR02, and LSR08 are unavailable in the active artifact. Assigned rules require a deterministic score and extractable narrative evidence. |
| Reference evidence and retrieval | Working in isolated API run | Catalog evidence and historical similarity are deterministic and expose unavailable status. Relevance is lexical, not calibrated confidence; live Supabase corpus behavior was not exercised. |
| Review/escalation/history | Working in isolated API run; adjudication semantics incomplete | Review update and history are atomic and survive reload. The runtime endpoint accepts one reviewer and immediately updates the effective outcome; the official two-reviewer adjudication gate is not enforced in this UI path. |
| Dashboards, filters, sites, activities, alerts | Implemented in code and build | Backend routes and client views exist. Authenticated visual verification and populated live-Supabase behavior were not completed. |
| Model/methodology/provenance views | Implemented | The UI exposes model identity, hashes, score status, LSR reference, and deterministic explanation status. It must not be read as a calibrated probability or HSE-ground-truth decision. |

## Findings

### F-01 — High — live browser demo is blocked by missing Supabase setup (confirmed for this environment)

**Expected:** the documented clean demo path should reach the authenticated workspace after the documented Supabase setup and `test / test123` seed.

**Observed:** the login page rendered correctly, including the documented demo hint, but `test / test123` returned “Incorrect User ID or password.” The frontend falls back to placeholder Supabase URL/key values when public variables are absent (`01-app/frontend/lib/supabase.ts:4-6`); the repository requires a real project, migrations, server secrets, and seeded user (`01-app/README.md:7-22,33-45`).

**Impact:** a reviewer cannot currently execute the end-to-end browser flow, including dashboard, detail, review, refresh persistence, logout, and protected-route redirect. This is an environment/demo-readiness blocker, not proof that Supabase authentication is intrinsically broken.

**Smallest fix:** provide the configured Supabase project and seed the documented user, then run the manual acceptance list in `01-app/README.md:67`. Do not enable public signup for the demo.

### F-02 — High — readiness health is green when the active model is unusable (confirmed)

**Expected:** a deployment readiness check should fail or report degraded when the frozen active model is missing/invalid.

**Observed:** with `MODEL_PATH` pointed at a missing artifact directory, `GET /health` returned HTTP 200 and `{"status":"ok","model_status":"ARTIFACT_MISSING"}`. The handler hard-codes the status (`01-app/backend/app/main.py:263-266`), while the classifier intentionally falls back to a null score and human review (`01-app/backend/app/services/classifier.py:141-181`). Render uses `/health` as its health check (`01-app/render.yaml:4-8`).

**Impact:** infrastructure can declare the service healthy while every new analysis loses a usable classifier score and silently shifts to a degraded workflow.

**Smallest fix:** separate liveness from readiness, and make the readiness endpoint non-2xx or explicitly degraded unless the active classifier and required LSR/reference dependencies satisfy the deployment contract.

### F-03 — High — safe/negated narratives can be auto-routed to SIF Potential (confirmed regression behavior)

**Expected:** completed precautions, negated hazards, and clearly routine/low-consequence narratives should not be presented as an unqualified automatic SIF signal without an explicit uncertainty guardrail.

**Observed direct probes against the active artifact:**

- `There were no dropped objects and isolation was verified before work began.` → score `0.77779`, `SIF_POTENTIAL`.
- `Routine housekeeping cleared a cable from a walkway with no equipment exposure.` → score `0.73092`, `SIF_POTENTIAL`.
- `A worker walking across a muddy yard slipped and twisted an ankle.` → score `0.23761`, `NON_SIF_POTENTIAL`.
- `An employee took measurements while standing on an earthen berm, lost balance, and fractured an ankle.` → score `0.35162`, `HUMAN_REVIEW`.

The active classifier is a text-only TF-IDF model and the SIF screen is independent of the LSR evidence guard (`01-app/backend/app/services/classifier.py:141-181,221-249`). The LSR mapper correctly suppresses several negated/hypothetical excerpts, but that does not prevent the SIF screen from auto-routing the report.

**Impact:** the demo can display a safe or completed-control narrative as high-risk/SIF without making the distinction obvious enough for a safety audience. These examples are regression probes, not a claim about a statistically representative error rate.

**Smallest fix:** add protected regression cases for negation, hypothetical language, completed precautions, and generic safe text; add an explicit product guardrail or conservative review route; only retrain/reselect after a predeclared evaluation and approval. Do not change the frozen model during this audit.

### F-04 — Medium — LSR/reference evidence channels can disagree, and active rule coverage is incomplete (confirmed)

**Expected:** the primary LSR label, evidence excerpt, batch `top_lsr`, and UI explanation should derive from one clearly identified mapping decision, or explicitly explain why they differ.

**Observed:**

- For `A truck driver lost control and struck a pedestrian.`, the separate reference-evidence path identifies `Driving`, while the active LSR mapper assigns `LSR06 Line of Fire`; the API constructs these independently (`01-app/backend/app/main.py:267-282`). The UI renders active mappings and reference evidence in separate panels (`01-app/frontend/components/workbench.tsx:15-17,24`), and batch `top_lsr` is selected from `analysis.rules.primary` (`01-app/backend/app/main.py:299-331`).
- `The driver was speeding.` was nominated conceptually as Driving but remained below threshold with no extractable LSR03 evidence. The active evidence patterns (`01-app/backend/app/services/domain_model.py:26-71`) do not cover every Driving nomination pattern in `lsr_concepts.py`.
- A permit narrative can show reference evidence for Work Authorisation while active LSR08 is unavailable. The active artifact explicitly marks LSR01, LSR02, and LSR08 unavailable (`01-app/backend/app/services/domain_model.py:82-103,168-188`).

**Impact:** reviewers can see a credible reference concept but a different active rule assignment, or an unavailable active rule, without a single authoritative explanation. A valid driving example may also be suppressed by the score/evidence gate. The observed probes establish the behavior; they do not estimate population-level LSR recall.

**Smallest fix:** define one canonical mapping contract, align nomination and evidence vocabularies, and render `reference concept`, `active classifier coverage`, and `assigned LSR` as distinct states. Add paired regression tests for each available/unavailable rule and common negation/hypothetical forms.

### F-05 — Medium — runtime review completion is weaker than the frozen evaluation policy (confirmed code-path gap)

**Expected:** if a runtime “confirmed” outcome is later consumed as final adjudication or metrics, it should satisfy the project’s two-distinct-reviewer, date, confidence, and accountable-adjudication policy.

**Observed:** the UI has one review box and one reviewer input (`01-app/frontend/components/workbench.tsx:25`). The backend accepts one authenticated reviewer and immediately applies the outcome (`01-app/backend/app/main.py:393-413`); the atomic database operation records one incident update and one history row (`supabase/migrations/202609070002_atomic_review_operations.sql:17-45`). The separate blind evaluator policy is stricter, but that gate is not represented in this runtime state transition.

**Impact:** a single reviewer can cause dashboards and downstream “effective outcome” fields to display a final-looking confirmation. This is safe only if runtime outcomes are explicitly provisional and excluded from official metrics until the separate adjudication process is complete.

**Smallest fix:** model `provisional review` and `locked adjudication` separately, require two distinct identities and accountable metadata before an outcome becomes metric-eligible, and label the UI accordingly.

### F-06 — Medium — evaluation supports an internal prototype claim, not an operational accuracy claim (confirmed limitation)

The active baseline’s fresh v0.4 binary assessment contains 132 scored rows after excluding 18 uncertain rows: `TP=84`, `FP=36`, `TN=12`, `FN=0`, precision `0.700`, recall `1.000`, specificity `0.250`, balanced accuracy `0.625`, F2 `0.921`. The 18 uncertain rows are descriptive routing only; they are not binary scoring. Labels are AI-assisted and explicitly not HSE expert ground truth. Scores are uncalibrated, and the model card says external blind validation remains pending (`05-documentation/docs/ml_methodology.md:3-5`; `03-training/ml/sif_v0_1/DOMAIN_ADAPTED_V0_2_MODEL_CARD.md:5-24,42-64,115-119`).

This is a useful development baseline, but the high false-positive count/low specificity and absent human-validation result should block claims such as “accurately predicts SIF” or “validated for production.” The v0.4 candidates remain unpromoted as required by `decisions.md:134-149`.

### F-07 — Medium — model serialization/runtime version drift reduces reproducibility (confirmed warning)

The full backend suite passed but emitted repeated scikit-learn `InconsistentVersionWarning` messages: artifacts were serialized under scikit-learn `1.8.0` and loaded under runtime `1.9.0`. The model card documents the same mismatch (`DOMAIN_ADAPTED_V0_2_MODEL_CARD.md:115-119`), while `01-app/backend/requirements.txt:7` permits a broad `>=1.5,<2` range.

**Impact:** future dependency resolution can change inference behavior or make loading fail. **Smallest fix:** pin the measured runtime, or reserialize and remeasure the frozen active artifact under the pinned deployment version.

### F-08 — Low/Medium — input and batch resource limits are incomplete (confirmed code)

The API limits a batch to 500 reports, but `AnalyzeInput.narrative` has no maximum length and the browser parses CSV/XLSX fully in memory (`01-app/backend/app/main.py:36-58,299-303`; `01-app/frontend/components/workbench.tsx:22`). A malformed row fails the whole Pydantic request rather than returning row-level diagnostics.

**Impact:** oversized text/spreadsheets can consume memory/storage, and users cannot identify or retry individual failed rows. **Smallest fix:** enforce file, row, and narrative limits at both client and API boundaries and return per-row validation/error results while preserving atomic persistence semantics.

### F-09 — Low/Medium — authenticated workspace authorization is broad by design but not tenant-scoped (hardening finding)

The backend requires an authenticated Supabase profile for general routes, but only the review mutation explicitly restricts role to `reviewer`/`admin` (`01-app/backend/app/main.py:243-251,393-413`). Incident reads, analysis writes, analytics, and alert access use the server-only Supabase key. RLS correctly blocks direct browser access to operational tables and the review RPC is service-role-only (`supabase/migrations/202609060001_sif_sentinel.sql:71-80`; `202609070002_atomic_review_operations.sql:44-45`).

For a single shared demo workspace this may be intentional. For multi-tenant or least-privilege production use, any authenticated profile with the `demo` default role can reach workspace-wide operational data through FastAPI. **Smallest fix:** document the shared-workspace assumption or add route-level role/tenant authorization and row scoping before production deployment.

## Data integrity and blind-boundary audit

- Both `blind_test_v0_2` and `blind_test_v0_3` contain 75 unique narratives, have packet SHA-256 `f911b0a78b8c366c95a18d6c60f47dda596adae3ef9edfc0719a357c0b6d83b3`, match their canonical manifest hashes, and have zero completed reviewer rows. Both manifests remain `frozen_unscored`.
- The v0.2 and v0.3 canonical packets are byte-identical. This is not a packet mutation, but v0.3 is not an independent new sample; release documentation should make that reuse explicit before any result is generalized.
- A read-only comparison of train, development, protected, fresh-assessment, and frozen-packet identities plus normalized narratives found no cross-split overlap outside the intentional v0.2/v0.3 packet reuse.
- No predictions, scores, explanations, or retrieval outputs were added to either reviewer packet. No frozen packet or freeze manifest was edited.
- The official v0.3 candidate has no completed finalization/attestation, so it cannot support an official human-validation result. The project’s policy correctly requires fixed artifacts and attestation before official evaluation.

## Runtime/security positives

- No committed secret values were found in the repository scan; the server-only Supabase secret is not exposed through `NEXT_PUBLIC_*` variables.
- CORS is origin-controlled with credentials rather than wildcard credentials.
- SQLite writes use parameterized SQL; review update/history is transactional. Supabase review persistence uses a service-role-only atomic RPC.
- Duplicate retrieval excludes the current incident, normalized narrative duplicates, duplicate source IDs, and locked sources/flags.
- LSR assignment requires both a score threshold and an extractable evidence excerpt; negated/hypothetical text is filtered from assigned evidence. Runtime generative LLM calls are disabled; explanations are deterministic templates.

## Verification performed

| Check | Result |
|---|---|
| Backend tests | `93 passed, 56 warnings` using an isolated temp base directory. The ordinary first run was blocked by a Windows temp-directory permission error, then passed unchanged in the isolated directory. |
| Frontend build | `npm run build` passed with Next.js 15.5.24 and TypeScript/static generation. 15 authenticated workspace routes plus login and the internal not-found route were generated. |
| Isolated API E2E | Passed single analysis, duplicate-aware batch, SQLite persistence, review update/history reload, deterministic explanation, similar retrieval, validation rejection, and explicit unavailable-model fallback. |
| Failure-mode probe | Missing active model reproduced HTTP 200 `/health` plus null-score `HUMAN_REVIEW` analysis, establishing F-02. |
| Browser | Login surface visually rendered. Authenticated flows were not verified because Supabase was not configured/seeded in the audit environment. |
| Frozen artifacts | Packet hash/row/blank-review checks passed for v0.2 and v0.3. |

## Recommended release order

1. Configure and seed a real Supabase demo environment, then complete the documented browser acceptance flow.
2. Fix readiness semantics so missing/invalid active artifacts cannot report healthy.
3. Add safety-language regression gates for negation, hypothetical text, completed precautions, and generic safe narratives; keep the frozen active model unchanged until a governed re-evaluation.
4. Unify LSR/reference mapping semantics and make unavailable coverage explicit in every downstream view.
5. Separate provisional review from locked dual-reviewer adjudication before using runtime outcomes in metrics.
6. Pin/rebuild model dependencies, then add input-size and per-row batch failure handling.
7. Decide whether the shared workspace is an explicit demo-only authorization model; otherwise add role and tenant scoping.

**Audit conclusion:** suitable for a controlled prototype demonstration after environment setup and with the limitations above stated plainly; not suitable for unqualified operational safety decisions, calibrated-probability claims, or official blind-validation reporting at this revision.
