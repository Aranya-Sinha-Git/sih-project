# SIF Sentinel workspace

The main online-deployable application is in [`01-app`](01-app/README.md).

The migration branch keeps the application architecture intact:

`Next.js → FastAPI → classifier / retrieval / analytics / review`

Supabase supplies PostgreSQL persistence and Auth; it does not replace the FastAPI/ML runtime. See [`01-app/README.md`](01-app/README.md) for Supabase creation, SQL migration, account registration, optional SQLite data migration, local startup, Render-style backend deployment, Vercel frontend deployment, CORS, and verification instructions.

The other workstreams remain unchanged: `02-labeling` contains labeling tools, `03-training` contains ML artifacts and evaluation methodology, `04-data` contains source/validation data, and `05-documentation` contains project documentation.
