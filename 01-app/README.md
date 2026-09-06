# SIF Sentinel application

The application is a migration, not a redesign:

`Next.js frontend → FastAPI API → frozen classifier, retrieval, analytics, and review logic`

Supabase provides PostgreSQL persistence and Auth. FastAPI remains the only application/business API; the browser does not read or write incident tables directly.

## Local setup

1. Create a Supabase project and run [`supabase/migrations/202609060001_sif_sentinel.sql`](../supabase/migrations/202609060001_sif_sentinel.sql) in the Supabase SQL editor.
2. Copy `.env.example` to `.env` and fill the server URL, publishable key, secret key, CORS origin, and the two frontend public variables. Never put `SUPABASE_SECRET_KEY` in a `NEXT_PUBLIC_*` variable.
3. From `01-app/backend`, create/install the Python environment with `pip install -r requirements.txt`.
4. Provision the idempotent demo user from `01-app/backend`:

   ```powershell
   python scripts/seed_demo_user.py
   ```

   It creates or reuses `test@users.sif-sentinel.invalid`, confirms the Auth email, and upserts profile `test` with reviewer role. It does not reset an existing password.

5. Optionally migrate the existing local database once:

   ```powershell
   python scripts/migrate_sqlite_to_supabase.py --sqlite data/sif_sentinel.db
   ```

   The importer preserves report IDs, timestamps, JSON analysis/intelligence, legacy records, review history, and provenance; reruns skip identical rows and fail differing rows without overwriting them.
6. Start the local app with `run-demo.cmd`, or run `uvicorn app.main:app --host 0.0.0.0 --port 8000` and `npm run dev` separately.

Login uses User ID `test` and Password `test123`. The compact hint appears only when `NEXT_PUBLIC_SHOW_DEMO_CREDENTIALS=true`.

## Deployment

For Render/Railway/Fly.io-style deployment, build from the repository root with [`backend/Dockerfile`](backend/Dockerfile); it includes the frozen artifact tree from `03-training` and binds to `0.0.0.0:$PORT`. [`render.yaml`](render.yaml) is an example service definition. Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `CORS_ORIGINS`, `FRONTEND_URL`, and `MODEL_PATH` in the backend service.

Deploy `01-app/frontend` to Vercel. Set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and `NEXT_PUBLIC_API_URL` to the public FastAPI URL (or set `BACKEND_URL` to use the `/api` rewrite). Add the deployed frontend origin to backend `CORS_ORIGINS`; do not use `*` with credentials.

## Component responsibilities

- Supabase: database and password authentication. RLS is enabled; only a user’s own profile is readable to browser-authenticated clients. Incident, alert, and review-history tables have no browser write/read policy; FastAPI uses the server-only key after authorization.
- FastAPI: Supabase session verification, username/profile resolution, classifier inference, retrieval, analytics, batch persistence, and review lifecycle.
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

After applying the SQL migration and seeding Supabase, manually verify login, dashboard load, analyze, detail/similarity, review, refresh persistence, logout, and protected-route redirect with `test / test123`.
