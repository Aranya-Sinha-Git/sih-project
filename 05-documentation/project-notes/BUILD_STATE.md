# Build state

## Completed
- Product and OPERATE design context established, including a visual system-board reference.
- Backend API, transparent rules engine, data-derived analytics and review workflow implemented.
- Frontend routes and dashboard shell implemented; TypeScript and production build pass.
- Audit/clarify/harden pass: labels retain provenance, responsive table wrapping is handled, backend-offline and no-results states are explicit, long narratives are constrained in table cells, and TXT/PDF/CSV/XLSX upload pathways are present.
- One-click Windows scripts added under `01-app/`: `run-demo.cmd`, `stop-demo.cmd`, and `test-project.cmd`.
- Public-source test fixture saved at `01-app/backend/data/public_test_reports.csv`, with provenance notes in `05-documentation/docs/public_test_reports_sources.md`.
- Six copy-ready individual public test narratives saved in `01-app/backend/data/public_test_reports/`.
- Synthetic seed records and hard-coded operational claims removed.
- Live history populated with 100 real, provenance-preserved public records: 50 documented OSHA-fatality weak-label positives and 50 DOE documented no-injury/near-miss weak-label negatives. Original source files and a manifest are stored locally.
- Empty-state regression suite passes (8 backend tests); frontend production build passes after data removal.
- Windows launcher reuses an already healthy instance, skips dependency installs unless dependency files change (or `-Install` is specified), preserves the Next.js cache by default, rejects unknown port owners safely, tracks its own process trees, waits for both services, and reports startup failures through dedicated logs.

## Important paths
- `01-app/backend/app/main.py` API and persistence pipeline
- `01-app/backend/app/services/engine.py` transparent scoring/extraction
- `01-app/backend/data/public_verified_history_manifest.json` public-history provenance manifest
- `05-documentation/docs/public_history_sources.md` source/label caveats
- `05-documentation/project-notes/HANDOVER.md` operational handover, verification state and known limitations
- `01-app/frontend/app/page.tsx` dashboard; `01-app/frontend/components/workbench.tsx` UI

## Remaining
- None.

## Blockers
- None.
