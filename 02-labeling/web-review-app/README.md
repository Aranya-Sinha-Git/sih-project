# SIF Labeling Frontend

This folder is a standalone, static Netlify site. It does not depend on the wider SIF project or the FastAPI backend.

## One-time Supabase setup

1. In Supabase, open **Authentication -> Providers -> Anonymous Sign-Ins** and enable it.
2. Open **SQL Editor**, paste `supabase/setup.sql`, and run it once.
3. Open **Table Editor -> labeling_candidates -> Insert -> Import data from CSV** and upload `data/labeling_candidates.csv`.

If Supabase's CSV importer reports a compatibility error, open **SQL Editor**, paste `supabase/seed_candidates.sql`, and run it instead. The seed inserts all 500 candidates and is safe to rerun.

No email login is required. Supabase creates a private anonymous reviewer account in each browser. Row Level Security permits reviewers to read candidates and all submitted labels, while each reviewer can insert only a decision owned by their browser identity. Decisions are append-only from the public app. Supabase Realtime broadcasts new labels to connected reviewers.

Every imported candidate receives a sequential `queue_order`, and the app presents these as incident numbers 1 through the final record. Reviewers can jump directly to any number, move backward or forward, and see peer labels and evidence update live.

## Deploy to Netlify

### Drag-and-drop

Run `npm install` and `npm run build`, then upload the generated `out` folder to Netlify Drop.

### Git deployment

Choose this folder as Netlify's base directory. The included `netlify.toml` supplies the build command and output directory. Add these environment variables in Netlify when using a repository build:

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

Only use the publishable key in the browser. Never add a Supabase secret key to this site.

## Back up every decision to this laptop

After decisions have been collected, run:

```powershell
.\scripts\backup-labels.ps1
```

The script asks for the Supabase `sb_secret_...` key using hidden input, then saves a timestamped CSV and `labeling_decisions_latest.csv` under `backups`. The secret is never written to the project. Do not share it or add it to Netlify.

## Local development

```powershell
npm install
npm run dev
```

The local values live in `.env.local`, which is intentionally excluded from version control.
