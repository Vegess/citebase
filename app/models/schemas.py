"""Pydantic schemas — every endpoint input is validated (security concern #4)."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


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
    num_chunks: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Chat ----
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Citation(BaseModel):
    filename: str
    chunk_index: int


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
