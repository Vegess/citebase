"""Record which sign-in provider created an account.

Revision ID: 0008_oauth_provider
Revises: 0007_hybrid_agent_conflicts
Create Date: 2026-10-09 16:00:00.000000

Google/GitHub sign-in only logs into accounts it created, so a password
account registered by someone else under your email can't be claimed by
(and shared with) you.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_oauth_provider"
down_revision = "0007_hybrid_agent_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("oauth_provider", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("oauth_provider")
