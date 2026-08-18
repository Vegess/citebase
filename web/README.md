# DocuMind — frontend

React + Vite + Tailwind v4. Talks to the FastAPI backend over JWT.

## Run it

```bash
cd frontend
npm install
cp .env.example .env        # Windows: copy .env.example .env
npm run dev                 # http://localhost:5173
```

The backend must be running on the URL in `.env` (default `http://127.0.0.1:8000`),
and its `CORS_ORIGINS` must include `http://localhost:5173` and `http://127.0.0.1:5173`.

## Structure

```
src/
├── lib/api.js              every network call, including the SSE stream parser
├── context/AuthContext.jsx JWT in React state (never localStorage)
├── components/
│   ├── ui.jsx              Button, Field, StatusBadge, EmptyState, toasts
│   └── Chrome.jsx          navbar, route guard, wordmark
└── pages/
    ├── Landing.jsx         public page — hero is a real cited answer
    ├── Auth.jsx            login + signup
    ├── Documents.jsx       drag-drop upload, status polling, delete
    └── Chat.jsx            streaming answers with source cards
```

## Two decisions worth being able to defend

**The token lives in memory, not localStorage.** Any injected script can read
localStorage, which is the usual way sessions get stolen. Holding it in React
state closes that path. The cost is being signed out on refresh; the production
fix for both is an httpOnly cookie set by the API.

**Ingestion status is polled, not assumed.** Upload returns immediately with
`status: processing` because the backend indexes in the background. The
documents page re-checks `GET /documents/{id}` every 2s until it settles, so a
large PDF never blocks the UI.

## Design notes

The palette comes from the document world — ink, paper, ruled margins. One
signal blue carries every action; a deep teal is reserved *only* for sources and
citations, so "where did this come from" never looks like "do something." Type
is Newsreader for display, IBM Plex Sans for interface, IBM Plex Mono for the
things documents actually have: filenames, chunk indices, statuses.

Assistant answers sit against a ruled left margin, the way an annotated document
does. That, and the source cards beneath each answer, are the signature.

## Deploying

Build output is static:

```bash
npm run build      # -> dist/
```

Deploy `dist/` to Vercel or Netlify. Set `VITE_API_URL` to the deployed API URL
in the platform's environment variables, then rebuild — Vite inlines env vars at
build time, so changing it later requires a redeploy.
