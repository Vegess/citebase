# Citebase — answers from your company's documents, with sources

*(Formerly DocuMind; renamed in October 2026 because that name belongs to an existing product.)*

Upload your company's policies, handbooks and contracts (PDF, Word, Markdown or text), ask questions, and get answers where every claim links to the exact passage it came from.

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

## How answers are built

- **Questions** ("what is the notice period?") use the 6 most relevant passages across your workspace. Short follow-ups ("and for interns?") borrow the previous question's words for the search.
- **Document tasks** ("review and rate my resume", "summarise the travel policy", "compare …") get the document itself, in reading order: found by file name mentioned in the question, "the file I just uploaded", the only document, or the best match. Long files send the opening plus the most relevant passages, and the model is told it is seeing part of the file.
- Naming a file in a question ("in the travel policy, …") searches only that file.
- Sources are numbered; only sources the answer cites are shown, whatever bracket style the model uses (`[1]`, `【1】`, `[^1]`).

## Advanced retrieval and agents

- **Hybrid search.** Every query runs vector search (meaning) and keyword search (exact terms such as policy codes, amounts, roll numbers) and fuses the two rankings with reciprocal-rank fusion. Keyword search uses Postgres full-text search with a GIN index; SQLite falls back to BM25.
- **Heading-aware chunks.** Passages keep the heading they sit under ("4. Notice period"), and tiny neighbouring sections are merged, so retrieved text carries its context.
- **Research agent** (Deep research toggle, or automatic for "do these conflict / across all policies" questions). The model plans up to 4 steps — `search` (optionally inside one file), `read` a whole file, or `finish` — as JSON actions that work on every provider. Every step is shown live and saved with the answer. Only the caller's workspace is searchable; document text reaches the planner as `<source>` data, never as instructions; if the model fails or misbehaves the agent stops and the answer falls back to a normal search instead of answering from nothing.
- **Conflict checker.** After a new document is summarised, a background job compares its passages with the most similar passages in the workspace's other files and flags direct contradictions (different numbers, deadlines, approvers) on the Documents page. Replies naming files that don't exist are discarded.

## Automation and insights

- **On every upload**, once the document is indexed, a follow-up job writes a 2–3 sentence summary and three questions the document answers (only when an LLM key is set; a degraded fallback reply is never saved as a summary — the job retries). They show under the file name and as starter cards on the Ask page.
- **Every answer is classified** as answered / not in your documents / degraded, and can be rated 👍 / 👎.
- **Insights** (admins): questions per day, answer rate, most-asked questions, **knowledge gaps** (asked but not covered by any document — what to upload next), documents cited most, and answers marked unhelpful. Questions are shown without who asked them.
- **Quick ask**: a floating button on every page sends a question straight to a new conversation.

## Evaluation

`eval/demo_company/` is a fictional company (Northwind Freight: handbook, travel, IT security, code of conduct, benefits). `eval/questions.yaml` holds 24 scored questions written before measuring: 18 answerable, 3 that the documents cannot answer, and 3 whole-document tasks.

```bash
python -m eval.run_eval            # retrieval hit@6, MRR, routing — real embeddings, no LLM key needed
python -m eval.run_eval --answers  # also answer accuracy and "says I don't know" rate, using your LLM key
```

CI runs the same eval with a deterministic offline embedder as a gate (`tests/test_eval.py`), and the real-embedding numbers as an informational job summary. A demo workspace for showing the product: `python -m app.seed_demo --email demo@… --password …`.

## Security

| Concern | Implementation |
|---|---|
| **Authentication** | Email + password (bcrypt) or Google / GitHub sign-in (OAuth 2.0 authorization-code flow). The OAuth `state` is a signed, 10-minute JWT bound to an httpOnly nonce cookie, so a forged or replayed callback is rejected. Only provider-verified emails are accepted. Social sign-in never logs into a password account (sign-up doesn't verify email, so that would allow account pre-hijacking), and a new social sign-in always gets its own workspace (or the invite waiting for that email) — never someone else's by name |
| **Sessions** | 30-minute access tokens held in memory only. Staying signed in uses an httpOnly, SameSite=Lax cookie on the site's own origin (Vercel rewrites `/api/*` to the API), so page scripts can never read it; the database stores only its SHA-256. Cookie endpoints also require an `X-Requested-With` header. Sessions slide for 30 days (90-day hard limit). Sign out, password change, password reset and "sign out everywhere" revoke sessions and every access token already issued (`tokens_valid_after`, millisecond precision) |
| **Password reset** | Single-use, hashed, 1-hour tokens; claimed atomically. Self-serve by email when `RESEND_API_KEY` is set (same response whether or not the email exists), or an admin creates a link for someone they outrank (audited). An emailed reset verifies the address; an admin link does not |
| **Connected accounts** | Google/GitHub can be connected from Settings only to an account with the same email, which also verifies it. Social sign-in enters only accounts with a verified email |
| **Data deletion** | The workspace owner can delete the whole workspace (typed-name confirmation); members, documents, chunks, conversations, invites and audit entries go in one transaction |
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
- **Scanned PDFs:** files with no extractable text are rejected (no OCR yet). Word files are read from their text, headings and tables; images inside them are ignored
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

All 117 tests should pass.

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
