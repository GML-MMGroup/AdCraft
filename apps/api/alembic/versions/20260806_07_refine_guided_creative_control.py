"""Refine Agent Canvas guided creative control.

Revision ID: 20260806_07
Revises: 20260806_06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_07"
down_revision = "20260806_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guidance_sessions") as batch_op:
        batch_op.add_column(sa.Column("creative_authority_json", sa.Text()))
        batch_op.add_column(sa.Column("current_checkpoint_json", sa.Text()))
        batch_op.add_column(sa.Column("narrative_direction", sa.Text()))
        batch_op.drop_constraint("ck_agent_canvas_guidance_session_mode", type_="check")
        batch_op.drop_column("guidance_mode")


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_guidance_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "guidance_mode",
                sa.Text(),
                nullable=False,
                server_default="collaborative",
            )
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_guidance_session_mode",
            "guidance_mode IN ('collaborative','delegated')",
        )
        batch_op.drop_column("narrative_direction")
        batch_op.drop_column("current_checkpoint_json")
        batch_op.drop_column("creative_authority_json")
