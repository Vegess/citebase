# DocuMind — Company Docs RAG Assistant

Upload your company documents, ask questions, get cited answers powered by your chosen LLM provider.

**Live Demo:** https://documind-beta-lac.vercel.app

## Architecture

- **Backend:** FastAPI with org isolation at SQL and vector layers
- **Database:** PostgreSQL/Neon (production) or SQLite (local)
- **Vector Store:** pgvector inside the same Postgres database (exact cosine search, org-filtered in SQL); plain-Python fallback on SQLite for local dev
- **Background jobs:** Postgres-backed queue (`SELECT … FOR UPDATE SKIP LOCKED`) with retries and backoff; ingestion runs as a job through a strict document lifecycle
- **Embeddings:** fastembed (ONNX Runtime) — lightweight alternative to sentence-transformers
- **LLM:** Groq (default), Gemini, or Anthropic API
- **Frontend:** React + Vite + Tailwind CSS
- **Deployment:** Docker on Render (backend), Vercel (frontend)

## Security

| Concern | Implementation |
|---|---|
| **Authentication** | JWT tokens with bcrypt password hashing |
| **Multi-tenancy** | Org isolation enforced at both SQL (WHERE org_id = ?) and vector (ChromaDB metadata filter) layers. Signup always creates a new org; existing orgs are joined only by single-use invite |
| **Roles (RBAC)** | OWNER / ADMIN / MEMBER / VIEWER, read from the database on every request. Viewers ask only; members upload; admins manage people and any document |
| **Invites** | 32-byte random tokens, stored as SHA-256 hashes, expire after 7 days. Acceptance is atomic (`SELECT … FOR UPDATE` + conditional update), so an invite can create exactly one account even under concurrent requests |
| **Audit log** | Org creation, invites, role changes, removals, uploads and deletions are recorded in the same transaction as the change |
| **Rate Limiting** | 20 requests/min on `/chat/ask` via slowapi |
| **Quota Caps** | Daily caps per deployment, per org and per user, each enforced with a single conditional `UPDATE … WHERE count < cap`, so concurrent requests can't overshoot |
| **Observability** | JSON logs; token-protected `GET /metrics` and `GET /metrics/logs`. Every degraded fallback answer is counted (`fallback_total`, `fallback_rate_5m`) and logged at WARNING |
| **Prompt Injection** | Retrieved documents wrapped in tags, system prompt treats text as data not instructions |
| **Input Validation** | Pydantic schemas on all endpoints |

## Limitations

- **Cold starts:** Free-tier hosting has ~50-second cold starts after 15 minutes of inactivity
- **Scanned PDFs:** files with no extractable text are rejected (no OCR yet)
- **Long files:** text beyond `MAX_DOCUMENT_CHARS` (200k ≈ 60 pages) is not indexed; such documents are flagged `truncated`
- **Daily quota:** Subject to daily question limits per org and per user
- **Model availability:** Depends on chosen LLM provider's API availability

## Local Setup

### Prerequisites
- Python 3.10+
- Node.js 16+
- PostgreSQL 12+ (or use SQLite for local dev)

### Backend

```bash
cd documind

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # On Windows
# source .venv/bin/activate  # On Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your API keys (GROQ_API_KEY, etc.)

# Run migrations (if using PostgreSQL)
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

Server runs at http://localhost:8000. Interactive API docs at http://localhost:8000/docs (dev only).

### Frontend

```bash
cd web

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend runs at http://localhost:5173.

### Run Tests

```bash
pytest -q --basetemp=.pytest-tmp
```

All 59 tests should pass.

## Stack Pinned Versions (July 2026)

- FastAPI 0.115.12
- PostgreSQL 17 (production) / SQLite (local)
- SQLAlchemy 2.0.36
- Anthropic 0.115.1
- fastembed 0.8.0
- ChromaDB ≥ 1.0
- React 18
- Vite 5

## Docker Deployment

Build and run locally:

```bash
docker-compose up --build
```

Push to Render/Railway/similar: see [DEPLOY.md](DEPLOY.md) for instructions.

## License

MIT License — see [LICENSE](LICENSE) for details.


## Setup

```bash
# 1. Activate the existing virtualenv
.\.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and JWT_SECRET_KEY

# 4. Run locally
uvicorn app.main:app --reload
```

> This repo is currently configured to use SQLite for local development. The app also supports Docker-based deployment via `Dockerfile` and `docker-compose.yml`.

## Local endpoints

- `POST /auth/signup` — creates a new org with you as OWNER
- `POST /auth/login`
- `GET /auth/invites/{token}` — preview an invite
- `POST /auth/accept-invite` — join an org with an invite token
- `GET /org/members`, `PATCH /org/members/{id}`, `DELETE /org/members/{id}` — admin+
- `POST /org/invites`, `GET /org/invites`, `DELETE /org/invites/{id}` — admin+
- `GET /org/audit` — admin+
- `POST /documents` — upload PDF or plain text
- `GET /documents` — list documents
- `GET /documents/{id}` — poll document status (`queued → chunking → embedding → ready`, or `failed`)
- `GET /documents/{id}/events` — full status history
- `GET /metrics`, `GET /metrics/logs` — `Authorization: Bearer $METRICS_TOKEN` (404 when unset)
- `POST /chat/ask` — non-streaming answer
- `POST /chat/ask/stream` — SSE streaming answer
- `GET /health` — health check

## Quick flow

1. `POST /auth/signup` — `{"email": "you@test.com", "password": "password123", "org_name": "TestCorp"}`
2. `POST /auth/login` — `username` and `password` form fields
3. Authorize with the returned bearer token
4. `POST /documents` — upload a PDF or `.txt`
5. `GET /documents/{id}` — verify ingestion status
6. `POST /chat/ask` or `POST /chat/ask/stream` to ask questions

## Deployment files

- `Dockerfile` — Python 3.12 slim container
- `docker-compose.yml` — local app service with mounted Chroma data
- `.github/workflows/ci.yml` — runs `pytest` on push and PRs
- `alembic/` — migration environment and initial schema migration

## Notes

- Do not store secrets in version control.
- Keep `.env` out of Git.
- The repo supports three LLM providers:

- Groq (default): set LLM_PROVIDER=groq and provide GROQ_API_KEY
- Google Gemini: set LLM_PROVIDER=gemini and provide GOOGLE_API_KEY
- Anthropic Claude: set LLM_PROVIDER=anthropic and provide ANTHROPIC_API_KEY

Switch providers by updating the LLM_PROVIDER value in your .env file. The app will use the active provider automatically at startup and will fall back to the local answer builder when the active provider key is missing.
