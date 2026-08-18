# Backend additions for the frontend

Three small changes. Nothing existing is modified except `main.py` (CORS + one router).

---

## 1. New file: `app/routes/users.py`

Copy it in as-is from this folder.

---

## 2. `app/models/schemas.py` — append two schemas

```python
# ---- Current user ----
class MeResponse(BaseModel):
    id: str
    email: EmailStr
    org_id: str
    org_name: str | None = None


# ---- Chat history ----
class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True
```

> If your `schemas.py` was migrated to Pydantic v2 style, use
> `model_config = ConfigDict(from_attributes=True)` instead of the inner
> `class Config`.

---

## 3. `app/routes/chat.py` — add the history endpoint

Add these imports at the top if they aren't already there:

```python
from sqlalchemy import select
from app.models.schemas import ChatMessageOut
```

Then append this route to the same router:

```python
@router.get("/history", response_model=list[ChatMessageOut])
def history(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Most recent messages for this user, oldest-first for rendering."""
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(min(limit, 200))
    ).all()
    return list(reversed(rows))
```

---

## 4. `app/main.py` — register the router and fix CORS for production

```python
from app.routes import auth, chat, documents, users   # add users

app.include_router(users.router)                      # add this line
```

Replace the hardcoded CORS origins with an env-driven list, so the deployed
frontend domain works without a code change:

```python
import os

# Comma-separated list, e.g. "http://localhost:3000,https://documind.vercel.app"
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 5. Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
uvicorn app.main:app --reload
```

`GET /me` and `GET /chat/history` should now appear in `/docs`.

---

## One thing to check yourself: the SSE format

`frontend/src/lib/api.js` parses `POST /chat/ask/stream`. It handles both a
plain-text token stream and JSON events shaped like:

```
data: {"text": "..."}          # or "delta" / "content"
data: {"citations": [...]}
data: [DONE]
```

Open your `app/routes/chat.py` streaming handler and confirm what it actually
emits. If it differs, adjust `handleLine` in `api.js` to match — that function
is the only place the format is assumed. The chat page falls back to the
non-streaming `/chat/ask` endpoint if streaming fails, so a mismatch degrades
rather than breaks.
