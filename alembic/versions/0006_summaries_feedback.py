"""Document summaries + suggested questions; answer kind, mode and feedback on messages.

Revision ID: 0006_summaries_feedback
Revises: 0005_vectors_lifecycle_jobs
Create Date: 2026-10-08 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_summaries_feedback"
down_revision = "0005_vectors_lifecycle_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("suggested_questions", sa.Text(), nullable=True))
    with op.batch_alter_table("conversation_messages") as batch:
        batch.add_column(sa.Column("answer_kind", sa.String(20), nullable=True))
        batch.add_column(sa.Column("answer_mode", sa.String(20), nullable=True))
        batch.add_column(sa.Column("feedback", sa.Integer(), nullable=True))
    op.create_index("ix_conversation_messages_answer_kind", "conversation_messages", ["answer_kind"])


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_answer_kind", table_name="conversation_messages")
    with op.batch_alter_table("conversation_messages") as batch:
        batch.drop_column("feedback")
        batch.drop_column("answer_mode")
        batch.drop_column("answer_kind")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("suggested_questions")
        batch.drop_column("summary")
