"""Sessions that survive a refresh, password resets, linked sign-in providers.

Revision ID: 0009_sessions_resets
Revises: 0008_oauth_provider
Create Date: 2026-10-10 10:00:00.000000

- user_sessions: long-lived refresh sessions behind an httpOnly cookie. Only a
  SHA-256 hash of the cookie value is stored.
- password_resets: single-use, hashed, 1-hour tokens (emailed, or handed out
  by an admin like an invite link).
- user_identities: which providers (github/google) are connected to an account.
- users.email_verified_at: set when a provider or an emailed reset proves the
  address. Google/GitHub sign-in only enters accounts with a verified email.
- users.password_set: false for accounts created through Google/GitHub.
- users.tokens_valid_after: access tokens issued earlier are rejected (sign out
  everywhere, password change).
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_sessions_resets"
down_revision = "0008_oauth_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("password_set", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True))
    # Accounts made through a provider already have a verified email and no usable password.
    op.execute("UPDATE users SET email_verified_at = created_at, password_set = false WHERE oauth_provider IS NOT NULL")

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("via", sa.String(10), nullable=False),  # email | admin
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_identity_user_provider"),
    )


def downgrade() -> None:
    op.drop_table("user_identities")
    op.drop_table("password_resets")
    op.drop_table("user_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("tokens_valid_after")
        batch.drop_column("password_set")
        batch.drop_column("email_verified_at")
