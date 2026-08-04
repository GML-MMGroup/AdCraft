"""Allow Agent Canvas execution members to retain internal blocked state.

Revision ID: 20260729_14
Revises: 20260729_13
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op


revision = "20260729_14"
down_revision = "20260729_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_execution_members") as batch:
        batch.drop_constraint("ck_agent_canvas_execution_members_state", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_execution_members_state",
            "state IN ('queued','waiting','blocked','running','succeeded','failed','cancelled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_execution_members") as batch:
        batch.drop_constraint("ck_agent_canvas_execution_members_state", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_execution_members_state",
            "state IN ('queued','waiting','running','succeeded','failed','cancelled')",
        )
