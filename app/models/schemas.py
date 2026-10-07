"""Pydantic schemas — every endpoint input is validated (security concern #4)."""
from datetime import datetime

from typing import Literal

import json

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---- Auth ----
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    org_name: str = Field(min_length=2, max_length=120)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Documents ----
class DocumentOut(BaseModel):
    id: str
    filename: str
    uploaded_by: str
    num_chunks: int
    status: str
    error: str | None = None
    truncated: bool = False
    char_count: int | None = None
    summary: str | None = None
    suggested_questions: list[str] | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("suggested_questions", mode="before")
    @classmethod
    def _parse_questions(cls, value):
        return json.loads(value) if isinstance(value, str) else value

    class Config:
        from_attributes = True


class DocumentEventOut(BaseModel):
    id: int
    from_status: str | None
    to_status: str
    detail: str | None
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Chat ----
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


class Citation(BaseModel):
    filename: str
    chunk_index: int
    # The [n] marker the answer uses for this source. Absent on messages saved
    # before numbered citations existed.
    n: int | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    message_id: str | None = None
    answer_kind: str | None = None


class FeedbackRequest(BaseModel):
    value: Literal[1, -1, 0]  # 0 clears it


class Suggestion(BaseModel):
    question: str
    filename: str
    doc_id: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationMessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[Citation] | None = None
    answer_kind: str | None = None
    feedback: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageOut]

    class Config:
        from_attributes = True


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    org_id: str
    org_name: str | None = None
    role: str


# ---- Org: members, invites, audit ----
AssignableRole = Literal["ADMIN", "MEMBER", "VIEWER"]


class MemberOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RoleUpdate(BaseModel):
    role: AssignableRole


class InviteCreate(BaseModel):
    email: EmailStr
    role: AssignableRole = "MEMBER"


class InviteOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class InviteCreated(InviteOut):
    # Returned exactly once. Only its hash is stored, so it cannot be shown again.
    token: str


class InvitePreview(BaseModel):
    org_name: str
    email: EmailStr
    role: str


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class AuditEventOut(BaseModel):
    id: int
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: str | None
    created_at: datetime

    class Config:
        from_attributes = True
