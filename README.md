# SIF Sentinel workspace

This workspace is arranged by workstream so each part can be opened and worked on independently.

| Folder | Contains | Start here |
| --- | --- | --- |
| `01-app/` | The main SIF Sentinel product: FastAPI backend and Next.js frontend | `01-app/run-demo.cmd` |
| `02-labeling/` | Labeling tools: the local Streamlit launcher and standalone Supabase/Netlify review site | `02-labeling/run-labeling.cmd` or `02-labeling/web-review-app/README.md` |
| `03-training/` | Model-training scripts, model workspace, artifacts, reports, and local label store | `03-training/ml/sif_v0_1/README.md` |
| `04-data/` | Source, validation, processed, and reference datasets | `04-data/validation-datasets/README.md` |
| `05-documentation/` | Architecture, methodology, deployment, demo, and handover documentation | `05-documentation/docs/` |

## Main application

Double-click `01-app/run-demo.cmd` to start the backend and frontend, then open `http://localhost:3000/login`. Use `01-app/stop-demo.cmd` when finished. `01-app/test-project.cmd` runs backend tests and the frontend production build.

Manual start:

```powershell
cd 01-app/backend
$env:SIF_LOCAL_DEMO='1'  # loopback demo only; use SIF_AUTH_TOKENS for a deployed API
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```powershell
cd 01-app/frontend
npm install
npm run dev
```

The launcher sets `SIF_LOCAL_DEMO=1` automatically. For a non-demo deployment, set `SIF_AUTH_TOKENS=token=Reviewer Name` and leave local demo mode disabled. Optional grounded explanations use `SIF_LLM_URL`, `SIF_LLM_MODEL`, `SIF_LLM_TIMEOUT_SECONDS` (default `5`), and `SIF_LLM_MAX_CONTEXT_CHARS` (default `6000`).

## Data and model scope

The included local history contains 100 real public records: 50 OSHA documented-fatality weak labels and 50 DOE documented no-injury/near-miss weak labels. They are not Oil India data and are not expert SIF adjudications. Source provenance is documented in `05-documentation/docs/public_history_sources.md`. The active rules engine is decision support, not a replacement for approved safety procedures or qualified personnel.

To import incidents into the application:

```powershell
cd 01-app/backend
python scripts/import_incidents.py C:\path\to\incidents.csv
```

For model-training commands, use the guide in `03-training/ml/sif_v0_1/README.md`.
