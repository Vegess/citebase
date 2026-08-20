"""Add persistent daily question quota counters.

Revision ID: 0003_question_usage
Revises: 0002_conversations
Create Date: 2026-08-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_question_usage"
down_revision = "0002_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usage_date", "scope", name="uq_question_usage_date_scope"),
    )
    op.create_index("ix_question_usage_usage_date", "question_usage", ["usage_date"])
    op.create_index("ix_question_usage_scope", "question_usage", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_question_usage_scope", table_name="question_usage")
    op.drop_index("ix_question_usage_usage_date", table_name="question_usage")
    op.drop_table("question_usage")