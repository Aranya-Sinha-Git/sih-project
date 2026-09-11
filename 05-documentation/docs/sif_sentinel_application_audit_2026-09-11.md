# SIH26165 SIF Sentinel application audit

**Audit date:** 2026-09-11

**Audited revision:** `1acc34559168109b32474054432a39c4eec49366` (`main`, equal to `origin/main`)

**Scope:** current application flows, model/runtime behavior, LSR evidence, evaluation/data integrity, persistence/review semantics, reliability/security, browser demo, tests/build.

**Change policy:** audit only. No application code, model artifact, frozen packet, or freeze manifest was changed.

## Executive verdict

The repository contains a coherent working prototype with a real Next.js/FastAPI/Supabase architecture, deterministic retrieval/evidence, review persistence, and strong automated coverage. The deployed Vercel-to-Render path is reachable and authenticated, but the application is **not ready to present as a fully reliable safety-decision system**.

The principal blockers are:

1. `/health` reports `status: ok` even when the active classifier artifact is missing; the deployment health check can therefore pass while analysis has degraded to null-score human review.
2. The active text classifier routed deliberately safe/negated or generic narratives to SIF Potential in direct regression probes. These are not formal accuracy estimates, but they are unacceptable unqualified demo behavior for safety language.
3. LSR mapping is deterministic and evidence-gated, but its active coverage is incomplete and its mapping channel can disagree with the separate reference-evidence channel shown in the UI.

The browser demo is environment-sensitive rather than intrinsically broken: after rebuilding with the repository’s real local Supabase variables and running the backend, `test / test123` authenticated successfully and the dashboard loaded live Supabase data. The deployed frontend at `https://sih-project-orpin-pi.vercel.app/` also authenticated with the same credentials and loaded the dashboard through Render at `https://sih-project-ng01.onrender.com`; the deployed read-only incident, review-queue, and model/evidence routes loaded without mutation.

Deployment connectivity is therefore not the main release blocker. Render `/health` returned `200` with `model_status: READY`, `lsr_model_status: READY`, and `database: supabase-postgres`; unauthenticated `/dashboard/summary` returned `401`; and a preflight from the Vercel origin returned `200` with an exact `Access-Control-Allow-Origin` match.

The official blind-validation boundary remains intact. The v0.2 and v0.3 packets are still blank, hash-valid, and `frozen_unscored`; no human-validation or external-validation claim is supported by this audit.

## Feature/status matrix

| Area | Status | Evidence and limitation |
|---|---|---|
| Authentication and protected workspace | Working with configured Supabase; configuration-sensitive | Supabase session gates the Next.js workspace; backend validates the Supabase token/profile. A correctly configured browser run authenticated with `test / test123` and loaded the dashboard. |
| Single-report analysis | Working in isolated API run | Validates narrative length/type, screens with the frozen active model, persists an incident, returns retrieval and LSR state. Scores are raw and uncalibrated. |
| TXT/CSV/XLSX batch intake | Working with bounded request count | Browser parses files and posts at most the API’s 500-report batch limit. Duplicate rows are reported and skipped. There is no row-level partial-failure report, file-size cap, or export flow. |
| SIF routing | Operational but unsafe for unqualified interpretation | Active `sif-v0.1` uses `<0.35` Non-SIF, `0.35–0.45` human review, `>0.45` SIF Potential. The score is not calibrated; direct probes exposed false-positive behavior. |
| LSR mapping and excerpts | Partially working | Six rules are available; LSR01, LSR02, and LSR08 are unavailable in the active artifact. Assigned rules require a deterministic score and extractable narrative evidence. |
| Reference evidence and retrieval | Working in isolated API run; live read path verified | Catalog evidence and historical similarity are deterministic and expose unavailable status. Relevance is lexical, not calibrated confidence; live Supabase write flows were not exercised. |
| Review/escalation/history | Working in isolated API run; adjudication semantics incomplete | Review update and history are atomic and survive reload. The runtime endpoint accepts one reviewer and immediately updates the effective outcome; the official two-reviewer adjudication gate is not enforced in this UI path. |
| Dashboards, filters, sites, activities, alerts | Implemented; dashboard visually verified | Backend routes and client views exist. The authenticated dashboard loaded live Supabase data; populated detail/review/write flows were not exercised. |
| Model/methodology/provenance views | Implemented | The UI exposes model identity, hashes, score status, LSR reference, and deterministic explanation status. It must not be read as a calibrated probability or HSE-ground-truth decision. |

## Findings

### F-01 — Medium — frontend authentication is build-time configuration-sensitive (confirmed implementation; initial audit failure was harness-induced)

**Expected:** a correctly configured build should authenticate with the documented `test / test123` credentials; a misconfigured build should identify missing/invalid Supabase configuration rather than presenting it as a bad password.

**Observed:** the repository’s ignored `01-app/.env` and `01-app/frontend/.env.local` contain real Supabase configuration. A direct password-grant check returned HTTP 200, and a corrected production build authenticated in the browser and loaded the dashboard. The initial audit attempt had explicitly compiled the frontend with placeholder public variables, which caused the generic “Incorrect User ID or password” message. The fallback is in `01-app/frontend/lib/supabase.ts:4-6`; the required setup and seed flow is documented in `01-app/README.md:7-22,33-45`.

**Impact:** an incorrectly built local/deployed frontend can look like a credential failure even when the Supabase account is healthy. This is configuration hardening, not an authentication regression in the current configured environment.

**Smallest fix:** fail fast for missing public Supabase variables outside explicitly local development, or add a non-secret configuration diagnostic before login. Keep the documented seed and disable public signup.

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

### F-10 — Medium — local frontend API target can break the configured login-to-dashboard flow (confirmed configuration mismatch; not observed in deployed target)

The checked-in example uses `NEXT_PUBLIC_API_URL=http://localhost:8000` (`01-app/.env.example`), but this workspace’s ignored `01-app/frontend/.env.local` uses `/api`. `01-app/frontend/next.config.ts` defines no `/api` rewrite or proxy. During the corrected live check, Supabase login succeeded, but the dashboard showed “Request could not be completed” until the frontend was rebuilt with the direct backend URL; the backend itself returned the dashboard successfully with the authenticated token.

**Impact:** valid credentials can appear to work while the authenticated workspace cannot load data. **Smallest fix:** align local/deployment configuration with the direct backend URL, or add and test a deliberate frontend proxy/rewrite. Keep the public Supabase variables build-time correct.

The deployed Vercel bundle was separately checked and contains the Render origin, so this finding describes the checked-in/local configuration mismatch and is not evidence that the supplied deployed target is currently miswired.

### F-11 — Medium — dashboard “awaiting human decision” and review queue disagree (confirmed live state)

The live dashboard displayed `Unreviewed model-positive: 1 · Awaiting human decision`, while `/reviews` displayed `0 records · No records have been added to this workspace`. The code counts any model-positive row without a human outcome as unreviewed (`01-app/backend/app/main.py:367-370`), but the review endpoint only returns rows whose `review_status` is in `ACTIONABLE_REVIEW_STATUSES` (`01-app/backend/app/main.py:393-395`). The observed first live record is `SIF Potential` with `review_status: Not required`, so it is counted by the dashboard but excluded from the queue.

**Impact:** a reviewer can be told that a decision is awaiting while the work queue contains nothing. **Smallest fix:** decide whether automatic SIF-positive rows require review; then use the same state predicate for dashboard counts, queue membership, and labels.

### F-12 — Medium — legacy/partial persisted records are displayed as current decisions without current evidence (confirmed live state)

The live incident detail for `ANL-B1BECD47` showed `SIF Potential` at `66.4%`, `Confirm SIF`, and active SIF model identity/hash, but also showed `LSR model / reference: Legacy · Not available`, no LSR mapping, no supported reference evidence, and a deterministic explanation stating that no supported evidence was retrieved. The engine evidence panel said “No strong SIF precursor language detected.” Its history contained two `Confirm SIF` entries by the same `Demo Reviewer` identity. This appears to be a legacy or partially migrated seeded record, not a new runtime analysis.

**Impact:** the workspace presents a current-looking high-risk/confirmed outcome whose evidence and LSR provenance are unavailable, while the page only partially signals the legacy state. This can mislead a demo reviewer and contaminate downstream interpretation if legacy rows are treated as current model evidence.

**Smallest fix:** explicitly version and badge legacy records, exclude them from current evidence/metrics, or migrate/recompute them through the current analysis schema before displaying current-model claims. Preserve their historical review history.

### F-13 — Low — site detail omits average model score while the UI renders zero (confirmed data-contract defect)

The live site detail for `Unspecified` showed `Average model score: 0`, although its two incident rows had scores `79.6%` and `66.4%`; the activity detail correctly showed `80%`. `site_stats()` calculates a score signal for its risk index but does not return `avg_model_score` (`01-app/backend/app/main.py:184-190`), while the shared entity view reads `s.avg_model_score` (`01-app/frontend/components/workbench.tsx:28`).

**Impact:** site-level reporting understates or misrepresents model-score context. **Smallest fix:** return the field consistently or omit the metric when the API does not provide it; do not substitute pending-review counts as a score.

### F-14 — Low — methodology copy does not match the seeded live workspace (confirmed copy mismatch)

The authenticated Methodology page says “No operational incident records are preloaded,” while the same workspace’s dashboard and incident register visibly contain two persisted operational records. This may be intentional demo seed data, but the statement is unqualified (`01-app/frontend/components/workbench.tsx:30`).

**Impact:** judges or reviewers cannot tell whether visible records are seeded demo fixtures, live user submissions, or an unexpected data residue. **Smallest fix:** label seeded fixtures explicitly or update the copy to describe the actual demo state.

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
| Live browser read paths | Configured local login, dashboard, incidents, reviewed detail, review queue, model, methodology, settings, sites, activities, intelligence, alerts, and analysis-intake surfaces loaded. The supplied Vercel deployment also loaded login, dashboard, incident register, review queue, and model/evidence routes. No live analyze/review writes were performed. |
| Deployed Vercel/Render boundary | Vercel bundle contained `https://sih-project-ng01.onrender.com`; Render `/health` returned 200 with the active model/LSR/database ready, unauthenticated `/dashboard/summary` returned 401, and the Vercel-origin CORS preflight returned 200 with an exact origin match. |
| Browser validation error | A short narrative was rejected without creating a record, but the UI collapsed the validation response to “Analysis could not run. Check the narrative and local backend.” |
| Frozen artifacts | Packet hash/row/blank-review checks passed for v0.2 and v0.3. |

## Recommended release order

1. Align the frontend API target/proxy and complete the documented browser acceptance flow with the configured Supabase environment.
2. Fix readiness semantics so missing/invalid active artifacts cannot report healthy.
3. Add safety-language regression gates for negation, hypothetical text, completed precautions, and generic safe narratives; keep the frozen active model unchanged until a governed re-evaluation.
4. Unify LSR/reference mapping semantics and make unavailable coverage explicit in every downstream view.
5. Reconcile dashboard queue predicates and explicitly separate legacy/partial records from current evidence.
6. Separate provisional review from locked dual-reviewer adjudication before using runtime outcomes in metrics.
7. Pin/rebuild model dependencies, then add input-size, per-row batch failure, and field-level validation handling.
8. Decide whether the shared workspace is an explicit demo-only authorization model; otherwise add role and tenant scoping.

**Audit conclusion:** suitable for a controlled prototype demonstration after environment setup and with the limitations above stated plainly; not suitable for unqualified operational safety decisions, calibrated-probability claims, or official blind-validation reporting at this revision.
