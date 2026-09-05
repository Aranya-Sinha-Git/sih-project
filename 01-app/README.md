# Main application

This workstream contains the production-style SIF Sentinel application.

- `backend/` — FastAPI API, rules engine, local SQLite data, and tests.
- `frontend/` — Next.js user interface.
- `run-demo.cmd` — starts both services.
- `stop-demo.cmd` — stops services started by the launcher.
- `test-project.cmd` — runs backend tests and the frontend production build.
- `.env.example` — environment-variable template.

Run `run-demo.cmd` from this folder to open the application at `http://localhost:3000/login`.
