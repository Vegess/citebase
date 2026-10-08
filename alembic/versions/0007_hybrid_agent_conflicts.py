"""Keyword-search index, research-agent traces, document conflict reports.

Revision ID: 0007_hybrid_agent_conflicts
Revises: 0006_summaries_feedback
Create Date: 2026-10-08 18:00:00.000000

The GIN index makes keyword search (hybrid retrieval) use an index on
Postgres; SQLite has no equivalent and uses in-process BM25.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_hybrid_agent_conflicts"
down_revision = "0006_summaries_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_fts "
            "ON document_chunks USING gin (to_tsvector('english', text))"
        )
    with op.batch_alter_table("conversation_messages") as batch:
        batch.add_column(sa.Column("agent_trace", sa.Text(), nullable=True))
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("conflicts", sa.Text(), nullable=True))
        batch.add_column(sa.Column("conflicts_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("conflicts_checked_at")
        batch.drop_column("conflicts")
    with op.batch_alter_table("conversation_messages") as batch:
        batch.drop_column("agent_trace")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_fts")
