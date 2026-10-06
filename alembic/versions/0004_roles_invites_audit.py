"""Roles, single-use invites, audit log; org names no longer unique.

Revision ID: 0004_roles_invites_audit
Revises: 0003_question_usage
Create Date: 2026-10-07 00:00:00.000000

Why org names stop being unique: signup used to look an org up BY NAME and
add the new user to it, so anyone could join any org by typing its name.
Signup now always creates a new org, and the only way into an existing org
is an invite. Names become display labels, so two companies may share one.

Backfill: every existing user gets a role. The earliest user in each org
becomes OWNER, everyone else MEMBER. Admins should review their member list
after deploy — under the old bug, an outsider could have joined their org.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_roles_invites_audit"
down_revision = "0003_question_usage"
branch_labels = None
depends_on = None


def _drop_org_name_unique() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot drop an unnamed constraint; rebuild the table from an
        # explicit definition instead of reflecting the old unique flag.
        orgs = sa.Table(
            "orgs",
            sa.MetaData(),
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table("orgs", recreate="always", copy_from=orgs) as batch:
            batch.create_index("ix_orgs_name", ["name"])
        return

    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("orgs"):
        if constraint["column_names"] == ["name"]:
            op.drop_constraint(constraint["name"], "orgs", type_="unique")
    for index in inspector.get_indexes("orgs"):
        if index["column_names"] == ["name"] and index.get("unique"):
            op.drop_index(index["name"], table_name="orgs")
    op.create_index("ix_orgs_name", "orgs", ["name"])


def upgrade() -> None:
    _drop_org_name_unique()

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(20), nullable=False, server_default="MEMBER"))
        batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))

    # Earliest user per org becomes OWNER.
    op.execute(
        """
        UPDATE users SET role = 'OWNER'
        WHERE id IN (
            SELECT u.id FROM users u
            WHERE u.created_at = (
                SELECT MIN(u2.created_at) FROM users u2 WHERE u2.org_id = u.org_id
            )
        )
        """
    )

    op.create_table(
        "org_invites",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_org_invites_org_id", "org_invites", ["org_id"])
    op.create_index("ix_org_invites_email", "org_invites", ["email"])
    op.create_index("ix_org_invites_token_hash", "org_invites", ["token_hash"], unique=True)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_org_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_org_invites_token_hash", table_name="org_invites")
    op.drop_index("ix_org_invites_email", table_name="org_invites")
    op.drop_index("ix_org_invites_org_id", table_name="org_invites")
    op.drop_table("org_invites")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_active")
        batch.drop_column("role")
    # Org-name uniqueness is intentionally not restored: duplicate names may
    # now exist and re-adding the constraint would fail.
    op.drop_index("ix_orgs_name", table_name="orgs")
