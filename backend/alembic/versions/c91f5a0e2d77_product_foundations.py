"""add product identity, tokens, alerts, webhooks, and retention

Revision ID: c91f5a0e2d77
Revises: b7e2c18d4a91
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c91f5a0e2d77"
down_revision: Union[str, None] = "b7e2c18d4a91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(18)")
    op.drop_constraint("role_workspace", "users", type_="check")
    op.execute("DROP INDEX IF EXISTS uq_users_workspace_owner")
    op.create_check_constraint(
        "role_workspace",
        "users",
        "(role = 'platform_admin' AND workspace_id IS NULL) OR "
        "(role IN ('workspace_owner', 'workspace_operator', 'workspace_viewer') "
        "AND workspace_id IS NOT NULL)",
    )
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "workspace_limits",
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
    )

    op.create_table(
        "api_tokens",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_ip", sa.String(45)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_api_token_name"),
    )
    op.create_index("ix_api_tokens_workspace_id", "api_tokens", ["workspace_id"])
    op.create_index("ix_api_tokens_token_prefix", "api_tokens", ["token_prefix"])

    op.create_table(
        "alerts",
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("resource_type", sa.String(80)),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("acknowledged_by", sa.Uuid()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "severity", "status", "code"):
        op.create_index(f"ix_alerts_{column}", "alerts", [column])

    op.create_table(
        "webhooks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True)),
        sa.Column("last_delivery_status", sa.String(32)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_webhook_name"),
    )
    op.create_index("ix_webhooks_workspace_id", "webhooks", ["workspace_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("webhook_id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", sa.String(1000)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "webhook_id", "event", "status", "next_attempt_at"):
        op.create_index(f"ix_webhook_deliveries_{column}", "webhook_deliveries", [column])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhooks")
    op.drop_table("alerts")
    op.drop_table("api_tokens")
    op.drop_column("workspace_limits", "retention_days")
    op.drop_column("users", "must_change_password")
    op.drop_constraint("role_workspace", "users", type_="check")
    op.create_check_constraint(
        "role_workspace",
        "users",
        "(role = 'platform_admin' AND workspace_id IS NULL) OR "
        "(role = 'workspace_owner' AND workspace_id IS NOT NULL)",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_users_workspace_owner ON users (workspace_id) "
        "WHERE role = 'workspace_owner'"
    )
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(15)")
