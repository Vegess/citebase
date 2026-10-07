"""Vectors in the database (pgvector), document lifecycle history, job queue.

Revision ID: 0005_vectors_lifecycle_jobs
Revises: 0004_roles_invites_audit
Create Date: 2026-10-08 00:00:00.000000

Existing documents: their vectors lived in ChromaDB on the host's temporary
disk and cannot be recovered, and the original files were never stored. They
are marked `reupload_required` so the UI says so honestly instead of showing
"ready" for a document no answer can ever cite.
"""
from alembic import op
import sqlalchemy as sa

from app.models.models import Embedding

revision = "0005_vectors_lifecycle_jobs"
down_revision = "0004_roles_invites_audit"
branch_labels = None
depends_on = None

REUPLOAD_MESSAGE = (
    "Search data for this file was lost when the old index was retired. "
    "Remove it and upload the file again."
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("char_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    documents = sa.table(
        "documents",
        sa.column("status", sa.String),
        sa.column("error", sa.Text),
        sa.column("num_chunks", sa.Integer),
    )
    op.execute(
        documents.update()
        .where(documents.c.status.in_(["ready", "processing"]))
        .values(status="reupload_required", error=REUPLOAD_MESSAGE, num_chunks=0)
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("doc_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Embedding(), nullable=False),
    )
    op.create_index("ix_document_chunks_doc_id", "document_chunks", ["doc_id"])
    op.create_index("ix_document_chunks_org_id", "document_chunks", ["org_id"])

    op.create_table(
        "document_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("doc_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_document_events_doc_id", "document_events", ["doc_id"])
    op.create_index("ix_document_events_org_id", "document_events", ["org_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_run_after", "jobs", ["run_after"])


def downgrade() -> None:
    op.drop_index("ix_jobs_run_after", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_document_events_org_id", table_name="document_events")
    op.drop_index("ix_document_events_doc_id", table_name="document_events")
    op.drop_table("document_events")
    op.drop_index("ix_document_chunks_org_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_doc_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    documents = sa.table("documents", sa.column("status", sa.String))
    op.execute(
        documents.update()
        .where(documents.c.status.in_(["reupload_required", "queued", "chunking", "embedding"]))
        .values(status="failed")
    )
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("truncated")
        batch.drop_column("char_count")
        batch.drop_column("error")
    # The pgvector extension is left installed; dropping it is not needed to roll back.
