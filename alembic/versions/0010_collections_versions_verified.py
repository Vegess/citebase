"""Collections with access control, document versions, verified answers,
conflict review.

Revision ID: 0010_collections
Revises: 0009_sessions_resets
Create Date: 2026-10-10 18:00:00.000000

- collections: folders of documents. A restricted collection is visible only
  to its members (and workspace admins); others are visible to everyone.
- documents.collection_id: NULL means "General" (everyone).
- documents.version / previous_version_id: uploading a new version keeps the
  old one until the new one is ready, then marks it "superseded".
- documents.conflicts_state: NULL (open) | resolved | ignored.
- verified_answers: admin-approved answers reused for the same question.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_collections"
down_revision = "0009_sessions_resets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "name", name="uq_collection_org_name"),
    )
    op.create_table(
        "collection_members",
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("collection_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("previous_version_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("conflicts_state", sa.String(12), nullable=True))
        batch.create_index("ix_documents_collection_id", ["collection_id"])
    op.create_table(
        "verified_answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_key", sa.String(300), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("source_message_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "question_key", name="uq_verified_org_question"),
    )


def downgrade() -> None:
    op.drop_table("verified_answers")
    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_collection_id")
        batch.drop_column("conflicts_state")
        batch.drop_column("previous_version_id")
        batch.drop_column("version")
        batch.drop_column("collection_id")
    op.drop_table("collection_members")
    op.drop_table("collections")
