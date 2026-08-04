"""Add durable model-default selection modes.

Revision ID: 20260803_28
Revises: 20260803_27
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260803_28"
down_revision = "20260803_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_defaults") as batch_op:
        batch_op.add_column(
            sa.Column("selection_mode", sa.Text(), nullable=False, server_default="explicit")
        )
        batch_op.create_check_constraint(
            "ck_model_defaults_selection_mode",
            "selection_mode IN ('automatic', 'explicit')",
        )
    op.execute(
        sa.text(
            "UPDATE model_defaults SET selection_mode = 'automatic' WHERE default_key = 'audio'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("model_defaults") as batch_op:
        batch_op.drop_constraint("ck_model_defaults_selection_mode", type_="check")
        batch_op.drop_column("selection_mode")
