# SIF Sentinel application

The application is a migration, not a redesign:

`Next.js frontend → FastAPI API → frozen classifier, retrieval, analytics, and review logic`

Supabase provides PostgreSQL persistence and Auth. FastAPI remains the only application/business API; the browser does not read or write incident tables directly.

## Local setup

1. Create a Supabase project and run the SQL files in `supabase/migrations/` in filename order in the Supabase SQL editor. The first creates the tables and RLS policies; the later files add atomic review persistence and migration identity synchronization. Existing projects should run only the migration files they have not already applied.
2. Copy `.env.example` to `.env` and fill the server URL, publishable key, secret key, CORS origin, and the two frontend public variables. Never put `SUPABASE_SECRET_KEY` in a `NEXT_PUBLIC_*` variable. When running Next.js from `01-app/frontend`, provide the same public values in `frontend/.env.local` and set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`; `/api` is not a configured proxy.
3. From `01-app/backend`, create/install the Python environment with `pip install -r requirements.txt`.
4. Apply the member-role migration and start the services. The login page supports self-service account registration with a User ID, display name, and password. New accounts receive the least-privileged `member` role. Reviewer and admin roles are assigned only by the server-side administrative provisioning command:

   ```powershell
   python scripts/provision_user.py --user-id reviewer-one --display-name "Reviewer One" --password "Provide-an-explicit-strong-password" --role reviewer
   ```

   The command requires every credential explicitly, never supplies defaults, and does not reset an existing Auth password. It is also the supported path for promoting a member to reviewer or admin. Keep the deployment-edge registration rate limiter enabled before opening registration publicly.

5. Optionally migrate the existing local database once:

   ```powershell
   python scripts/migrate_sqlite_to_supabase.py --sqlite data/sif_sentinel.db
   ```

   The importer preserves report IDs, timestamps, JSON analysis/intelligence, legacy records, review history, and provenance; reruns skip identical rows and fail differing rows without overwriting them.
6. Start the local app with `run-demo.cmd`, or run `uvicorn app.main:app --host 0.0.0.0 --port 8000` and `npm run dev` separately.

Open the login page, choose “Create account,” and register with a strong password. Password recovery is not currently available through ordinary email links because User IDs use synthetic internal email addresses; use the administrator-assisted reset process until a dedicated reset flow is implemented.

## Deployment

For Render/Railway/Fly.io-style deployment, build from the repository root with [`backend/Dockerfile`](backend/Dockerfile); it includes the frozen artifact tree from `03-training` and binds to `0.0.0.0:$PORT`. [`render.yaml`](render.yaml) is an example service definition. Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `CORS_ORIGINS`, `FRONTEND_URL`, and `MODEL_PATH` in the backend service. Render checks `/ready` for readiness; `/live` is the liveness endpoint. Missing/invalid required artifacts or database connectivity make `/ready` return non-2xx. The three intentionally unsupported LSR classifiers are reported as unavailable coverage and do not make an otherwise loaded LSR artifact unready. `CORS_ORIGINS` and `FRONTEND_URL` accept comma-separated origins and normalize a root trailing slash; use the deployed frontend origin, for example `https://sih-project-orpin-pi.vercel.app`.

Deploy `01-app/frontend` to Vercel. Set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and `NEXT_PUBLIC_API_URL` to the public FastAPI URL, with no endpoint suffix such as `/dashboard/summary`. Add the deployed frontend origin to backend `CORS_ORIGINS`; do not use `*` with credentials. Vercel builds fail fast when required public variables are missing. Redeploy the backend after changing backend variables and redeploy the frontend after changing any `NEXT_PUBLIC_*` variable.

## Component responsibilities

- Supabase: database and password authentication. RLS is enabled; only a user’s own profile is readable to browser-authenticated clients. Incident, alert, and review-history tables have no browser write/read policy; FastAPI uses the server-only key after authorization.
- FastAPI: Supabase session verification, username/profile resolution, classifier inference, retrieval, analytics, batch persistence, and operational review lifecycle.
- Next.js: presentation, Supabase browser session, User ID login, and a centralized authenticated API client.

## Current-to-Supabase mapping

| Current component | Supabase replacement |
| --- | --- |
| SQLite `incidents` | PostgreSQL `public.incidents` with JSONB `analysis` |
| SQLite `review_history` | PostgreSQL `public.review_history` |
| SQLite `alerts` | PostgreSQL `public.alerts` |
| No application profile | `public.profiles` linked to `auth.users` |
| Static token login | Supabase password session using deterministic internal email mapping |
| FastAPI SQL queries | `app/services/database.py` repository boundary |

## Verification

```powershell
cd 01-app/backend
python -m pytest tests -q
cd ../frontend
npm run build
```

After applying the SQL migration, manually verify registration, immediate login, dashboard load, analyze, detail/similarity, operational review authorization, refresh persistence, logout, duplicate-registration handling, and protected-route redirect. Runtime review dispositions are not formal dual-reviewer adjudications and cannot be used as official blind-validation ground truth. Scores are screening signals rather than accident probabilities; automatic results require qualified human review, the application does not replace safety procedures, and some rule coverage is limited.
