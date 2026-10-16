"""Persist installation model-default thinking modes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260923_01"
down_revision = "20260920_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_defaults") as batch:
        batch.add_column(
            sa.Column("thinking_mode", sa.Text(), nullable=False, server_default="enabled")
        )
        batch.create_check_constraint(
            "ck_model_defaults_thinking_mode",
            "thinking_mode IN ('disabled', 'enabled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("model_defaults") as batch:
        batch.drop_constraint("ck_model_defaults_thinking_mode", type_="check")
        batch.drop_column("thinking_mode")
