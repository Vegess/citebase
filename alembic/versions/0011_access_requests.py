"""Access requests for the invite-only launch (SIGNUP_MODE=waitlist).

Revision ID: 0011_access_requests
Revises: 0010_collections
Create Date: 2026-10-18 12:00:00.000000

- access_requests: people asking to join. email is lower-cased and unique
  while the request is pending. Approval stores the SHA-256 of a single-use
  7-day sign-up token; the hash is cleared once the token is used.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_access_requests"
down_revision = "0010_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("company", sa.String(120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(36), nullable=True),
    )
    op.create_index(
        "uq_access_request_pending_email", "access_requests", ["email"], unique=True,
        postgresql_where=sa.text("status = 'pending'"), sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_access_request_pending_email", table_name="access_requests")
    op.drop_table("access_requests")
