"""Add Editing action reconciliation receipt authority.

Revision ID: 20260903_01
Revises: 20260831_01
"""

from __future__ import annotations

from alembic import op


revision = "20260903_01"
down_revision = "20260831_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guided_production_receipts") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_guided_production_receipt_type",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_guided_production_receipt_type",
            "receipt_type IN ('storyboard_fanout','media_confirmation',"
            "'editing_preparation','editing_action_reconciliation','final_completion')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_guided_production_receipts") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_guided_production_receipt_type",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_guided_production_receipt_type",
            "receipt_type IN ('storyboard_fanout','media_confirmation',"
            "'editing_preparation','final_completion')",
        )
