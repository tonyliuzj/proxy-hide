"""add revocable pool list links

Revision ID: e5b9c3d7a128
Revises: d3a8f6b21c54
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b9c3d7a128"
down_revision: Union[str, None] = "d3a8f6b21c54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pool_list_links",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("include_global", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "pool_id"],
            ["pools.workspace_id", "pools.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_pool_list_link_name"),
    )
    op.create_index("ix_pool_list_links_workspace_id", "pool_list_links", ["workspace_id"])
    op.create_index("ix_pool_list_links_pool_id", "pool_list_links", ["pool_id"])


def downgrade() -> None:
    op.drop_index("ix_pool_list_links_pool_id", table_name="pool_list_links")
    op.drop_index("ix_pool_list_links_workspace_id", table_name="pool_list_links")
    op.drop_table("pool_list_links")
