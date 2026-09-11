# SIF Sentinel final deployment acceptance check — 2026-09-11

## Verdict

**INCOMPLETE.** The deployed Vercel-to-Render application was exercised successfully for health, authentication, analysis, persistence, review escalation, queue/dashboard behavior, provenance, LSR/reference separation, and threshold display. The tested application source is `54b8f329926735f6260e21d1de8ce09dbd6b662c` (`54b8f32`). Vercel and Render deployment identities could not be established: both provider consoles redirected to login, and no deployment ID or commit reference was exposed by the public app responses. Per the acceptance rule, the deployments are therefore **UNVERIFIED**, not assumed correct from reachability.

This check did not retrain, recalibrate, change thresholds, promote candidates, or modify frozen validation artifacts. It created two clearly marked operational demo records in the shared workspace and retained them.

## Acceptance run and records

- Run ID: `ACCEPTANCE_20260911T061040Z`
- Acceptance start evidence: `2026-09-11T06:07:51.6276049Z`
- Acceptance finish evidence: `2026-09-11T06:19:22.1709222Z`
- Primary analysis record: `ANL-AE471CFB`
- Actionable-review fixture: `ANL-6BF36018`
- Marker location: site metadata `ACCEPTANCE_20260911T061040Z`; the primary narrative was kept marker-free. The fixture review comment also carries the marker.

The primary record returned `SIF Potential`, `83.5%` uncalibrated screening score, `High`, `Immediate attention`, `LSR04 · Energy Isolation`, and retrieved reference concepts `Line of Fire`, `Energy Isolation`, and `SIF`. The deployed UI explicitly labels retrieved concepts as evidence context rather than assigned LSRs and showed unavailable rule coverage `LSR01, LSR02, LSR08` without treating unavailable rules as negatives.

The fixture returned `Needs Review`, `35.2%` uncalibrated screening score, and `Pending`. It was escalated through the UI and persisted as `Escalated / Unsure` with reviewer `Demo Reviewer`, the authenticated account identity. After reload and a navigate-away/back cycle, the outcome and one audit-history row remained present. The UI states that this is operational human review only and is excluded from formal blind evaluation.

## Check summary

| Check | Environment | Status | Evidence |
|---|---|---:|---|
| DEP-001 repository identity and initial clean state | Static inspection | PASS | `raw_evidence.json` |
| DEP-002 Vercel deployment identity | Deployed browser | BLOCKED | `raw_evidence.json`; Vercel console redirected to login |
| DEP-003 Render deployment identity | Deployed browser | BLOCKED | `raw_evidence.json`; Render console redirected to login |
| DEP-004 `/live` | Deployed API | PASS | `raw_evidence.json` |
| DEP-005 `/ready` contract | Deployed API | PASS | `raw_evidence.json` |
| DEP-006 Render live health-check setting | Static inspection + provider console | BLOCKED | `raw_evidence.json`; repository says `/ready`, live console unavailable |
| DEP-007 frontend-origin CORS preflight | Deployed API | PASS | `raw_evidence.json` |
| AUTH-001 protected endpoint rejection | Deployed API | PASS | `raw_evidence.json` |
| AUTH-002 authenticated frontend/dashboard | Deployed browser | PASS | `raw_evidence.json`; inline CUA dashboard capture |
| LOCAL-001 isolated missing-artifact readiness/null-score behavior | Local integration | PASS | `raw_evidence.json` |
| LOCAL-002 backend regression suite | Local integration | PASS | `raw_evidence.json` |
| BUILD-001 frontend production build | Local integration | PASS | `raw_evidence.json` |
| FLOW-001 deployed analysis write and displayed result | Deployed browser | PASS | `raw_evidence.json`; inline CUA analysis capture |
| FLOW-002 displayed result and persisted detail coherence | Deployed browser | PASS | `raw_evidence.json` |
| REVIEW-001 actionable fixture and pre-transition queue | Deployed browser | PASS | `raw_evidence.json`; inline CUA queue capture |
| REVIEW-002 operational escalation through UI | Deployed browser | PASS | `raw_evidence.json` |
| REVIEW-003 reload/navigation persistence and history | Deployed browser | PASS | `raw_evidence.json`; inline CUA persisted-detail capture |
| REVIEW-004 queue/dashboard actionable-review consistency | Deployed browser + static inspection | PASS with capture limitation | `raw_evidence.json`; post-transition dashboard and pre/post queue membership |
| READ-001 partial record does not inherit current provenance | Deployed browser | PASS | `raw_evidence.json`; inline CUA partial-record capture |
| READ-002 explicit unavailable historical-evidence state | Deployed browser | BLOCKED | No deployed record exposed `retrieval_unavailable`; mutation of existing records was out of scope |
| READ-003 assigned LSR/reference distinction | Deployed browser | PASS | `raw_evidence.json`; inline CUA provenance/LSR capture |
| READ-004 unavailable LSR coverage visible | Deployed browser | PASS | `raw_evidence.json` |
| READ-005 missing scores are not rendered as zero | Local integration + deployed site | PASS | `raw_evidence.json` |
| INT-001 operational review excluded from formal evaluation | Deployed browser + local integration | PASS | `raw_evidence.json` |
| INT-002 model provenance and thresholds | Deployed browser + static integrity | PASS | `raw_evidence.json`; inline CUA model/settings captures |
| INT-003 browser console diagnostics | Deployed browser | PASS | `raw_evidence.json` |

## A. Deployment identity and configuration

Public endpoints were reachable at:

- Frontend: `https://sih-project-orpin-pi.vercel.app/`
- Backend: `https://sih-project-ng01.onrender.com`

The latest frontend probe returned HTTP 200 with Vercel request header `x-vercel-id: bom1::4jcqv-1789107498727-aee40b546c81` and Next build ID `4KaGV8LTHVtv9gDdOOvnR`. These are request/build identifiers, not verified Vercel deployment IDs or source commit references. The backend returned Cloudflare plus `x-render-origin-server: uvicorn`, with no deployment ID or commit reference.

`https://vercel.com/dashboard` redirected to `https://vercel.com/login?next=%2Fdashboard`; `https://dashboard.render.com/` redirected to `https://dashboard.render.com/login`. No provider login, token, cookie, password, or key was entered. No redeployment was triggered because the authorized provider integrations were not available in this session.

Static inspection of `01-app/render.yaml` at source commit `54b8f329…` confirms `healthCheckPath: /ready`. This is not evidence of the live Render setting, so DEP-006 remains BLOCKED.

## B. Endpoint evidence

Fresh sanitized probes at `2026-09-11T06:18:16Z–06:18:18Z` recorded:

- `GET /live` → `200`, `{"status":"alive"}`.
- `GET /ready` → `200`, status `ready`; classifier `READY`; LSR artifact `READY`; database `READY`; SIF model `sif-v0.1`; LSR model `iogp-lsr-v0.2`; supported rules `LSR03, LSR04, LSR05, LSR06, LSR07, LSR09`; unavailable rules `LSR01, LSR02, LSR08`; database `supabase-postgres`; generative runtime disabled.
- `GET /health` → `200` with the same readiness contract.
- Unauthenticated `GET /dashboard/summary` → `401`, `Authentication required`.
- Unauthenticated `GET /incidents/ANL-AE471CFB` → `401`, `Authentication required`.
- Correct frontend-origin preflight → `200`, exact `Access-Control-Allow-Origin: https://sih-project-orpin-pi.vercel.app`, `Access-Control-Allow-Credentials: true`.

An initial preflight using an origin value with a trailing slash returned `400 Disallowed CORS origin`; the retry with the browser-standard origin (no trailing slash) returned `200`. This was an evidence-probe input correction, not an application fix.

## C–D. Browser flows and persistence

The browser session was already authenticated when the task began. Navigating to `/login` immediately redirected to the protected dashboard, and the actual frontend loaded live dashboard data. The protected API calls made by the frontend succeeded, and the subsequent review response identified the authenticated reviewer as `Demo Reviewer`. A fresh credential re-entry was not repeated because the in-app browser session could not expose its hidden responsive sign-out control; no password was recorded or transmitted by this task.

The primary analysis was submitted through `/analyze` with site `ACCEPTANCE_20260911T061040Z`, activity `Maintenance / Energy Isolation`, report type `Near Miss`, and the narrative recorded in `raw_evidence.json`. The UI routed to `/analyze/ANL-AE471CFB` and displayed the persisted result. A subsequent direct frontend navigation to the incident detail reloaded the record from the protected API and showed the same score, classification, activity/site metadata, assigned LSR, retrieved concepts, model provenance, and thresholds.

The review fixture was submitted through the same UI with activity `Acceptance review fixture`. It appeared as the sole pre-transition queue row. The UI escalation action persisted `Escalated / Unsure`. A full reload, navigation to the queue, and navigation back to the detail page showed the outcome, authenticated reviewer, comment, and audit history. The fixture remained in the actionable queue after escalation, as required by the `Pending`/`Escalated` predicate.

Dashboard after the transition showed `Pending required reviews = 1`, `Unresolved / escalated = 1`, and `Reports analyzed = 4`; the queue showed exactly one record, `ANL-6BF36018`, both before and after the transition. The pre-transition queue screenshot was captured, and the post-transition dashboard and queue states were captured. The dashboard was not separately captured in the interval between fixture creation and escalation; the matching predicate is also confirmed by static inspection and the post-transition equality.

## E. Commands run during this task

- `git rev-parse HEAD; git status --short --branch; git remote -v` → clean `main`, HEAD and `origin/main` at `54b8f329…` before acceptance evidence files.
- Full backend first attempt: `.\\.venv\\Scripts\\python.exe -m pytest tests -q` → exit 1, `93 passed, 8 errors`; all errors were Windows `PermissionError` during pytest `tmp_path` setup under the existing temp root.
- Backend rerun: `.\\.venv\\Scripts\\python.exe -m pytest tests -q --basetemp=.codex-pytest-acceptance-20260911-0615` → exit 0, `101 passed, 57 warnings`.
- Targeted local safety checks: `.\\.venv\\Scripts\\python.exe -m pytest -q --basetemp=.codex-pytest-acceptance-local-20260911-0620 tests/test_api.py::test_readiness_fails_when_required_classifier_is_invalid tests/test_api.py::test_classifier_failure_and_null_score_analytics tests/test_api.py::test_site_average_score_excludes_null_scores tests/test_api.py::test_legacy_analysis_remains_readable tests/test_api.py::test_historical_provenance_never_falls_back_to_active_model` → exit 0, `5 passed, 3 warnings`.
- Frontend build: `npm run build` from `01-app/frontend` → exit 0, Next.js 15.5.24, all 17 routes generated.
- Endpoint probe: sanitized PowerShell `Invoke-WebRequest` GET/OPTIONS calls documented in `raw_evidence.json`; no authorization headers or cookies were printed.
- Artifact integrity: `git diff --quiet HEAD -- active artifacts and frozen v0.2/v0.3 paths` → exit 0.

## F. Artifact and threshold integrity

The deployed model page reported model identity `tfidf_word_12_char_35` and SIF model hash `f9f88650988e0abc92a74807480e9097e422ebfe252f95e69f45dd20c736473f`, matching the local frozen active artifact. The deployed settings page reported `< 0.35` Non-SIF, `0.35–0.45 inclusive` Review, and `> 0.45` SIF, matching `threshold.json` (`sif_threshold: 0.4`, `human_review_band: [0.35, 0.45]`). The local LSR artifact hash and frozen v0.2/v0.3 manifest/packet hashes are recorded in `acceptance_results.json`.

No active artifact, threshold, training data, blind-test packet, freeze manifest, experimental candidate, or official evaluation artifact was changed. The acceptance records are operational demo data and are not formal evaluation labels.

## G. Failed attempts, fixes, and reruns

1. Provider identity consoles were attempted and redirected to login. No credentials were entered; no redeploy was attempted. This remains a blocker, not an application failure.
2. The first backend test command hit the known Windows pytest temp-permission blocker. The unchanged suite passed on the fresh isolated basetemp. No test assertion was weakened.
3. An initial CORS probe used a trailing slash in the `Origin` header and returned 400. The corrected browser-standard origin passed with exact CORS headers. No code change was made.
4. Immediately after review submission, the review widget showed the saved escalation while the parent detail summary briefly still showed its pre-save values. The required reload/navigation persistence flow showed the correct outcome and history; no application change was made because the persisted acceptance requirement passed and the transient rendering window was not part of the required assertion.

## H. Limitations and residual changes

- Vercel and Render deployment IDs and live source commits remain unknown. Reachability, response headers, matching UI contracts, and matching artifact hashes do not prove deployment identity.
- The live Render health-check setting could not be verified in the provider console; only the checked-in `render.yaml` was inspected.
- No deployed record with explicit `retrieval_unavailable` historical evidence was available. The partial record check showed unavailable current LSR assignment provenance and no supported reference evidence, but it did not prove the explicit unavailable-history state.
- Screenshots were captured and displayed inline by the CUA browser during the task. The available browser surface did not materialize screenshot bytes to repository files; `screenshot_evidence.md` records the captures and their associated page states. The DOM and API evidence in `raw_evidence.json` are the persistence proof; screenshots are corroborating visual evidence only.
- Temporary pytest basetemp directories created during test execution remain local untracked workspace residue if the environment’s deletion guard prevents cleanup; they are not part of the evidence commit.
- This acceptance check does not establish classifier accuracy, calibrated probabilities, production safety, or readiness for official blind-validation reporting.

## Commit and push distinction

The application revision tested by the deployed browser/API flows is `54b8f329926735f6260e21d1de8ce09dbd6b662c`. The acceptance report, JSON, raw evidence, and screenshot index are evidence-only changes made after that application revision. The final response records the evidence commit and push result separately.

Evidence files:

- `05-documentation/docs/sif_sentinel_acceptance_2026-09-11.md`
- `05-documentation/docs/sif_sentinel_acceptance_2026-09-11/acceptance_results.json`
- `05-documentation/docs/sif_sentinel_acceptance_2026-09-11/raw_evidence.json`
- `05-documentation/docs/sif_sentinel_acceptance_2026-09-11/screenshot_evidence.md`
