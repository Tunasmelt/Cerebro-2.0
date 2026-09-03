# Cerebro 2.0 — web

Next.js 15 frontend (App Router, Turbopack). Part of the Cerebro 2.0
monorepo — see the [root README](../../README.md) for what this project
is, the full tech stack, and local setup for both this app and its
FastAPI backend (`services/api/`).

```bash
npm install
npm run dev       # reads .env.local — copy from .env.example first
```

Runs against `services/api` via the `API_BASE_URL` env var (thin proxy
routes under `src/app/api/`) — the backend needs to be running
separately for anything beyond the sign-in/marketing pages to work.

See [`../../architecture-and-security.md`](../../architecture-and-security.md)
for how the frontend fits into the rest of the system, and
[`../../api-documentation.md`](../../api-documentation.md) for the API
surface it talks to.
