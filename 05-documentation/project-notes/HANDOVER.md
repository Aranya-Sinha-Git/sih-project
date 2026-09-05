# SIF Sentinel — Handover

## Purpose and current status

SIF Sentinel is a local SIH26165 safety-intelligence prototype. It ingests free-text Unsafe Act, Unsafe Condition, Near Miss, and Incident reports; classifies potential Serious Injury and Fatality (SIF) exposure; maps IOGP-style Life-Saving Rules; extracts precursor signals; retrieves similar reports; calculates recurring patterns and SIF-precursor density; and records qualified human review decisions.

The active analytic method is the transparent deterministic rules engine (`rules-v1.0`). It is **not** a trained, calibrated, externally validated, or production-approved ML model. The displayed percentage is a prototype rule score, not a calibrated probability.

## Run the demo

Double-click `01-app/run-demo.cmd` from the workspace root. It starts:

- Frontend: `http://localhost:3000/login`
- Backend API: `http://127.0.0.1:8000`

The launcher now performs a fresh Next.js production build and serves it with `next start`. This prevents the broken/unstyled HTML condition caused by development HTML referring to stale CSS/JavaScript assets.

- `01-app/stop-demo.cmd` stops processes recorded by the launcher.
- `01-app/test-project.cmd` runs backend tests and the frontend production build.
- `01-app/run-demo.cmd -Install` forces dependency installation.
- `01-app/run-demo.cmd -Clean` stops the tracked demo, clears the Next.js production cache, builds again, and starts fresh.

If an old browser tab shows unstyled content, close it, reopen `http://localhost:3000/login`, and use **Ctrl+Shift+R** once. If the launcher reports that another process owns ports 3000/8000, stop the stale local Node/Python processes before retrying.

## Architecture

```text
Browser → Next.js frontend (/api proxy) → FastAPI → rules engine + SQLite
```

- Frontend: `01-app/frontend/` — Next.js 15, TypeScript, custom CSS, Recharts, Lucide, XLSX import.
- Backend: `01-app/backend/app/main.py` — FastAPI API, persistence, analytics, density calculation, review workflow.
- Engine: `01-app/backend/app/services/engine.py` — deterministic classification, Life-Saving Rule mapping, extraction, and lexical similarity.
- Database: `01-app/backend/data/sif_sentinel.db` — local SQLite.
- Public-history manifest: `01-app/backend/data/public_verified_history_manifest.json`.
- API proxy: frontend calls `/api`; Next.js forwards requests to the local FastAPI service. This avoids direct browser/CORS restrictions on port 8000.

## Implemented SIH26165 functions

1. **Report ingestion** — manual narrative entry plus TXT, CSV, XLSX, and limited text-extractable PDF upload.
2. **Report types** — Unsafe Act, Unsafe Condition, Near Miss, and Incident are stored with new records/imports.
3. **SIF classification** — every newly analysed report is returned as `SIF Potential`, `Non-SIF Potential`, or `Needs Review`.
4. **Life-Saving Rules** — primary/secondary keyword-based mappings include Energy Isolation, Line of Fire, Working at Height, Safe Mechanical Lifting, Driving Safety, Confined Space, Hot Work, and Permit to Work.
5. **Extraction** — activity, basic location, hazards, precursor groups, and barrier/control-failure phrases are displayed.
6. **Recurring patterns** — precursor/rule groups are aggregated across stored reports.
7. **Density ranking** — sites and activities are ranked by `SIF classifications ÷ total reports`.
8. **Human review** — reviewer, outcome, comment, timestamp, and history are stored.

## Data scope and provenance

The live SQLite history contains exactly **100 real public-source records**:

- 50 positive weak labels: OSHA accident-detail records marked as fatalities.
- 50 negative weak labels: DOE Operating Experience Summary records documenting no-injury near misses or property-only events.

They are **not Oil India data** and are not expert SIF adjudications. Every record is `source=public_verified`, `sif_label_status=weak_label`, and retains publisher, source URL, source identifier, and label basis in `analysis.provenance`.

Source files:

- `01-app/backend/data/public_osha_fatality_reports/` — saved OSHA detail pages.
- `01-app/backend/data/public_doe_oes/` — saved DOE OES PDFs.
- `05-documentation/docs/public_history_sources.md` — provenance and label caveats.

The public corpus is suitable for demo/reference workflow only. It must not be used to claim OIL model performance. Keep public reference data separate from operational OIL data and review queues in any future deployment.

## Operational data import

Use the backend virtual environment:

```powershell
cd 01-app/backend
.\.venv\Scripts\python.exe scripts\import_incidents.py C:\path\to\incidents.csv
```

Required CSV columns: `report_id,date,site,activity,narrative`.

Optional columns: `report_type` (`Unsafe Act`, `Unsafe Condition`, `Near Miss`, `Incident`; `UA`/`UC` aliases work) and `source`.

The import preserves source report ID, report date, source, report type, import batch ID, and provenance. It does not infer SIF potential from High Potential alone.

## Validation

Last verified on 2026-08-27:

- Backend: `9 passed` via `01-app/backend\.venv\Scripts\python.exe -m pytest -q tests`.
- Frontend: `npm run build` passed.
- Launcher: local production frontend successfully returned the page and CSS asset with HTTP 200.
- Dashboard and site-detail Recharts graphics rendered as SVG without console errors.

Non-blocking test warnings remain for FastAPI's deprecated `@app.on_event` startup API and a restricted pytest cache directory.

## Important limitations and next work

### Prototype limitations

- The classifier is deterministic keyword/rule logic, not validated AI/ML.
- No external labelled OIL dataset has been used for training or evaluation.
- Public weak labels differ materially from expert SIF labels; the bundled corpus is not representative of OIL operations.
- Similarity is local lexical word overlap, not semantic embedding retrieval.
- Location and barrier extraction are basic phrase matching.
- The included historical data is mainly generic public-source site/activity metadata, so it is not meaningful operational site intelligence.
- Authentication, roles, enterprise audit protection, notifications, and true alert generation are not configured.
- The app is local-only SQLite and is not suitable for operational deployment.

### Before production

1. Obtain de-identified OIL reports and expert SIF/LSR labels.
2. Establish acceptance metrics focused on recall and false-negative rate; use time-based held-out evaluation.
3. Run in shadow mode with HSE reviewers and record overrides/errors.
4. Add SSO/RBAC, HTTPS, immutable audit logs, secure file handling, secrets management, and approved data-retention controls.
5. Replace SQLite with an enterprise database, add migrations/backups/monitoring, and deploy through approved infrastructure.
6. Build governed MLOps: versioned datasets/models, approval gates, drift monitoring, rollback, and periodic revalidation.
7. Keep human HSE review mandatory; the system must not autonomously approve work or replace safety procedures.

## Important files

- `01-app/backend/app/main.py` — API, storage, import persistence, trends, density analytics, review workflow.
- `01-app/backend/app/services/engine.py` — rules engine and extraction.
- `01-app/frontend/components/workbench.tsx` — dashboard and all primary UI views.
- `01-app/frontend/lib/api.ts` and `01-app/frontend/next.config.ts` — same-origin API proxy.
- `01-app/run-demo.ps1` — reliable production-build launcher.
- `01-app/test-project.ps1` — backend/frontend verification.
- `05-documentation/docs/sif_labeling_framework.md` — SIF labelling guidance.
- `05-documentation/docs/ml_methodology.md` — future evaluation approach.
- `05-documentation/docs/demo_script.md` — short SIH demo flow.
