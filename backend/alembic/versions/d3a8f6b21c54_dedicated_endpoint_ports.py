"""add dedicated endpoint ports, open access, and per-endpoint rotation

Revision ID: d3a8f6b21c54
Revises: c91f5a0e2d77
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3a8f6b21c54"
down_revision: Union[str, None] = "c91f5a0e2d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("endpoints", sa.Column("listen_port", sa.Integer()))
    op.add_column(
        "endpoints",
        sa.Column("require_auth", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("endpoints", sa.Column("strategy", sa.String(15)))
    op.create_unique_constraint("uq_endpoint_listen_port", "endpoints", ["listen_port"])


def downgrade() -> None:
    op.drop_constraint("uq_endpoint_listen_port", "endpoints", type_="unique")
    op.drop_column("endpoints", "strategy")
    op.drop_column("endpoints", "require_auth")
    op.drop_column("endpoints", "listen_port")
