"""Database models. Every tenant-owned table carries org_id — this is the
backbone of multi-tenant isolation (security concern #3)."""
import uuid
from datetime import date, datetime, timezone

import json

from sqlalchemy import Boolean, Date, Index, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.types import TypeDecorator, UserDefinedType
from sqlalchemy.sql.expression import false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Display name only. NOT unique and never used to look an org up: matching
    # orgs by name at signup let anyone join any org by typing its name.
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    users: Mapped[list["User"]] = relationship(back_populates="org")
    documents: Mapped[list["Document"]] = relationship(back_populates="org")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="org")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="MEMBER", server_default="MEMBER")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Set when the account was created through a provider that verified the
    # email (Google/GitHub). Only such accounts can be signed into that way.
    oauth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Proven by a provider sign-in or an emailed reset link. Google/GitHub
    # sign-in only enters accounts whose email is verified.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    # Access tokens issued before this moment are rejected.
    tokens_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped[Org] = relationship(back_populates="users")


EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class _PgVector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return f"vector({EMBEDDING_DIM})"


class Embedding(TypeDecorator):
    """pgvector `vector(384)` on Postgres; JSON text everywhere else (tests, local SQLite).

    Values cross the boundary as pgvector's text form "[0.1,0.2,...]", which is
    also valid JSON, so one encoder serves both databases.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return "[" + ",".join(f"{float(x):.7g}" for x in value) + "]"

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value) if isinstance(value, str) else list(value)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    num_chunks: Mapped[int] = mapped_column(Integer, default=0)
    # Lifecycle: see app/services/lifecycle.py for the allowed transitions.
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # Written by the summarize_document job when an LLM key is configured.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_questions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of strings
    # Written by the check_conflicts job: JSON list of {other_filename, topic, this_says, other_says}.
    conflicts: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflicts_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conflicts_state: Mapped[str | None] = mapped_column(String(12), nullable=True)  # None=open | resolved | ignored
    # NULL = "General", visible to everyone in the workspace.
    collection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    previous_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    org: Mapped[Org] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["DocumentEvent"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="DocumentEvent.id"
    )


class DocumentChunk(Base):
    """One searchable passage. Lives in the same database as its document, so
    deleting a document removes its chunks in the same transaction."""
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Embedding, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")


class DocumentEvent(Base):
    """Append-only history of every document status change."""
    __tablename__ = "document_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Job(Base):
    """Durable background work. Claimed with SELECT ... FOR UPDATE SKIP LOCKED,
    so several workers can share the table without taking the same job."""
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    org: Mapped[Org] = relationship(back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Assistant rows only. answer_kind: answered | abstained | no_sources | fallback.
    answer_kind: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    answer_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # question | document
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 helpful, -1 not helpful
    agent_trace: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON steps of the research agent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class QuestionUsage(Base):
    __tablename__ = "question_usage"
    __table_args__ = (UniqueConstraint("usage_date", "scope", name="uq_question_usage_date_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OrgInvite(Base):
    """Single-use invitation into an org. Only the SHA-256 of the token is stored."""
    __tablename__ = "org_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Append-only record of security-relevant actions inside an org."""
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class UserSession(Base):
    """A refresh session behind the httpOnly cookie. Only the hash is stored."""
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    via: Mapped[str] = mapped_column(String(10), nullable=False)  # email | admin
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserIdentity(Base):
    """A sign-in provider connected to an account."""
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_identity_user_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Collection(Base):
    """A folder of documents. Restricted ones are visible only to members (and admins)."""
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_collection_org_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CollectionMember(Base):
    __tablename__ = "collection_members"

    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VerifiedAnswer(Base):
    """An answer an admin approved; the same question gets it instantly."""
    __tablename__ = "verified_answers"
    __table_args__ = (UniqueConstraint("org_id", "question_key", name="uq_verified_org_question"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_key: Mapped[str] = mapped_column(String(300), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AccessRequest(Base):
    """A request to join the invite-only beta. Approval issues a single-use
    sign-up token (only its SHA-256 is stored; cleared once used)."""
    __tablename__ = "access_requests"
    __table_args__ = (
        # One pending request per email; a rejected person may ask again later.
        Index("uq_access_request_pending_email", "email", unique=True,
              postgresql_where=text("status = 'pending'"), sqlite_where=text("status = 'pending'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # lower-cased
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    company: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending", server_default="pending")
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
