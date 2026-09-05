# Netlify deployment

The Next.js frontend is configured for Netlify with the repository-root `netlify.toml`.

## Netlify settings

- Base directory: `frontend`
- Build command: `npm run build`
- Publish directory: `.next`
- Node.js: 22

Netlify's current automatic OpenNext adapter should detect the Next.js application; do not add or pin the legacy `@netlify/plugin-nextjs` package.

## Required environment

Set `BACKEND_URL` in Netlify to the public HTTPS origin of the deployed FastAPI backend, without a trailing slash. The browser will continue to call the same-origin `/api` path, and Next.js will proxy requests to that backend.

Configure the backend with `SIF_AUTH_TOKENS` as a server-only mapping of opaque bearer tokens to reviewer names, for example `random-token=Reviewer One,another-token=Reviewer Two`. The backend derives reviewer identity from the bearer token; a client-supplied reviewer name is not trusted. Do not put tokens in `NEXT_PUBLIC_*` variables or the proxy configuration. The backend must not set `SIF_LOCAL_DEMO` in deployment.

Example:

```text
BACKEND_URL=https://api.example.com
```

Alternatively, set `NEXT_PUBLIC_API_URL` to a public API URL, but this exposes the URL to browsers and requires the backend's CORS policy to allow the Netlify domains.

## Backend limitation

The FastAPI backend is not made deployable by this Netlify configuration. It currently uses a writable local SQLite database and must be hosted separately on infrastructure with persistent storage, or migrated to a managed database before production use. Do not point `BACKEND_URL` at `127.0.0.1` or `localhost` in Netlify.
