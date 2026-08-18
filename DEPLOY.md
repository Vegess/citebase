# Deploying DocuMind

Two pieces: the API goes to **Railway** (it needs a persistent disk and ~1.5 GB
RAM for the embedding model), the frontend goes to **Vercel** (static files, free).

Do them in that order — the frontend needs the API's URL at build time.

---

## Before you start

- [ ] `pytest -q` passes locally
- [ ] Repo is on GitHub, and `git status` shows **no** `.env`, `*.db`,
      `chroma_data/`, `.venv/`, or `node_modules/`
- [ ] `.gitignore` covers all of the above

If the repo isn't pushed yet, that's the first task — deployment platforms build
from GitHub, so nothing below works until it is.

---

## Part 1 — API on Railway

### 1. Create the service

railway.app → **New Project** → **Deploy from GitHub repo** → pick your repo.
It will detect the `Dockerfile` automatically.

### 2. Add a volume

**New** → **Volume** → mount path `/data`.

This is the step people skip. Without it, every redeploy wipes the container's
filesystem — meaning all users, documents, and embeddings vanish. SQLite and
ChromaDB are both files on disk, so they must live on the volume.

### 3. Set environment variables

In the service's **Variables** tab:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your real key |
| `JWT_SECRET_KEY` | **a fresh one** — `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | `sqlite:////data/documind.db` — note the four slashes (absolute path) |
| `CHROMA_PERSIST_DIR` | `/data/chroma` |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` |
| `CORS_ORIGINS` | your Vercel URL once you have it (step 2 below) |

Never reuse your development `JWT_SECRET_KEY` in production. Anything that has
been on your screen, in a screenshot, or in a chat is burned.

### 4. Run migrations on boot

The container must apply migrations before serving. Set the start command to:

```
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`$PORT` matters — Railway assigns the port, so hardcoding 8000 fails.

If your `main.py` still calls `Base.metadata.create_all()`, remove it now that
Alembic owns the schema. Leaving both in place means the two disagree the first
time you change a model.

### 5. Deploy and verify

First build is slow (5–10 min — PyTorch is a large download). Then:

- `https://your-app.up.railway.app/health` → `{"status":"ok"}`
- `/docs` → sign up, upload a PDF, ask a question

If `/health` works but the app 500s on upload, check the volume is mounted at
`/data` and the two path variables point into it.

---

## Part 2 — Frontend on Vercel

1. vercel.com → **New Project** → import the same repo
2. **Root Directory:** `web`
3. Framework preset: Vite (auto-detected). Build `npm run build`, output `dist`
4. **Environment variable:** `VITE_API_URL` = your Railway URL (no trailing slash)
5. Deploy

For local development, the Vite frontend runs on `http://localhost:5173`.

Then go back to Railway and set `CORS_ORIGINS` to your Vercel URL, e.g.
`https://documind.vercel.app`. The API will reject the browser's requests until
you do.

Vite inlines env vars at build time, so if you change `VITE_API_URL` later you
must redeploy, not just restart.

---

## Part 3 — Harden it

- [ ] Disable or protect `/docs` in production — add a `DEBUG` env flag and pass
      `docs_url=None` to `FastAPI()` when it's false. Right now anyone can browse
      your full API surface.
- [ ] Confirm `CORS_ORIGINS` is your real domain, never `*`
- [ ] Spam `/chat/ask` and confirm you get a `429` — the rate limiter is what
      stands between a bored visitor and your Anthropic bill
- [ ] Enable Railway's database backups
- [ ] Sign up as two different orgs, upload a file to one, and confirm the other
      can't retrieve it. Your test proves this, but prove it in production too

---

## Costs

Railway Hobby is ~$5/month. Claude API is per-question — embeddings run locally
on the container and cost nothing. The rate limiter caps the worst case.

Free tiers won't work here: 512 MB RAM isn't enough to load sentence-transformers,
and ephemeral disks lose your data on every deploy.

---

## When SQLite stops being enough

It's a single-writer database. One container serving a handful of orgs is fine;
concurrent writes at scale are not. The upgrade path is already open because you
used SQLAlchemy and Alembic:

1. Add Railway's managed PostgreSQL
2. Change `DATABASE_URL` to the Postgres connection string
3. `alembic upgrade head` against the new database
4. Later, move vectors from ChromaDB to `pgvector` so everything sits in one
   backed-up database

Being able to explain *why* you'd migrate — and that the code was built to allow
it — is worth more in an interview than having done it prematurely.
