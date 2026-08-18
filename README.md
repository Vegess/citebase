# DocuMind — Company Docs RAG Assistant

Upload your company documents, ask questions, get cited answers powered by your chosen LLM provider.

**Stack:** FastAPI · SQLite / SQLAlchemy · ChromaDB · sentence-transformers · Groq / Gemini / Anthropic providers

## Current status

This repo is now upgraded through Phase 4 of the product-ready roadmap:

- Phase 1: full pytest + httpx coverage with temporary SQLite and Chroma fixtures
- Phase 2: sentence/paragraph-aware chunking and chat conversation memory
- Phase 3: background document ingestion, status polling, and streaming chat responses
- Phase 4: Alembic migrations, structured logging, GitHub Actions CI, Dockerfile, docker-compose

The complete test suite passes locally:

```bash
cd C:\Users\K.Anantha\Documents\DevLife\Mainstream_Projects\MajorProjects\documind
.\.venv\Scripts\python.exe -m pytest -q
```

## Architecture

```
React frontend (separate repo/folder)
        │ HTTPS + JWT
        ▼
FastAPI  ──►  Security layer (JWT auth, rate limit, Pydantic validation)
        │
        ├──►  SQLite / SQLAlchemy   (orgs, users, documents, chat history)
        │
        └──►  RAG pipeline
                ├── sentence-transformers — embeddings
                ├── ChromaDB              — org-filtered vector store
                ├── Claude API            — answer generation + streaming
                └── Background ingestion   — async document processing
```

## Security built in

| Concern | Where it lives |
|---|---|
| Auth (JWT + bcrypt) | `app/core/security.py` |
| Org isolation (multi-tenancy) | `app/services/rag.py` — every Chroma query filters `org_id`; `documents.py` — every SQL query scoped to the authenticated user's org |
| Prompt injection defense | `app/services/generation.py` — docs wrapped in tags, system prompt treats retrieved text as data |
| Input validation | `app/models/schemas.py` — Pydantic on every endpoint |
| SQL injection | SQLAlchemy ORM — parameterized queries everywhere |
| Rate limiting | `app/routes/chat.py` — 20 req/min via slowapi |
| Logging | structured `user_id`, `org_id`, `latency_ms`, `retrieved_chunks` in chat handlers |

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

- `POST /auth/signup`
- `POST /auth/login`
- `POST /documents` — upload PDF or plain text
- `GET /documents` — list documents
- `GET /documents/{id}` — poll document ingestion status
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
