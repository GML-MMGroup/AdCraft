"""Add immutable guided production receipts.

Revision ID: 20260815_03
Revises: 20260815_02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260815_03"
down_revision = "20260815_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_execution_members") as batch:
        batch.drop_constraint("ck_agent_canvas_execution_members_state", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_execution_members_state",
            "state IN ('queued','waiting','blocked','skipped_dependency','running',"
            "'succeeded','failed','cancelled')",
        )
    op.create_table(
        "agent_canvas_guided_production_receipts",
        sa.Column("receipt_id", sa.Text(), primary_key=True),
        sa.Column("receipt_type", sa.Text(), nullable=False),
        sa.Column("logical_identity", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "receipt_type IN ('storyboard_fanout','media_confirmation',"
            "'editing_preparation','final_completion')",
            name="ck_agent_canvas_guided_production_receipt_type",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.UniqueConstraint(
            "receipt_type",
            "logical_identity",
            name="uq_agent_canvas_guided_production_receipt_identity",
        ),
    )
    op.create_index(
        "ix_agent_canvas_guided_production_receipts_workflow_type",
        "agent_canvas_guided_production_receipts",
        ["workflow_id", "receipt_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_guided_production_receipts_workflow_type",
        table_name="agent_canvas_guided_production_receipts",
    )
    op.drop_table("agent_canvas_guided_production_receipts")
    with op.batch_alter_table("agent_canvas_execution_members") as batch:
        batch.drop_constraint("ck_agent_canvas_execution_members_state", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_execution_members_state",
            "state IN ('queued','waiting','blocked','running','succeeded','failed','cancelled')",
        )
