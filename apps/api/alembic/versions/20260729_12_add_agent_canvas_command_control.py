"""Add Agent Canvas command plans, receipts, variations, and layout revision.

Revision ID: 20260729_12
Revises: 20260728_11
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_12"
down_revision = "20260728_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_workflows") as batch:
        batch.add_column(
            sa.Column(
                "layout_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.create_check_constraint(
            "ck_agent_canvas_workflows_layout_revision",
            "layout_revision > 0",
        )

    op.create_table(
        "agent_canvas_command_plans",
        sa.Column("plan_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column(
            "source_turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column("base_workflow_revision", sa.Integer(), nullable=False),
        sa.Column("operations_json", sa.Text(), nullable=False),
        sa.Column("operation_fingerprint", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("confirmation_required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("continuation_requested", sa.Boolean(), nullable=False),
        sa.Column("target_summary", sa.Text(), nullable=False),
        sa.Column("supersedes_plan_id", sa.Text()),
        sa.Column("replacement_plan_id", sa.Text()),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('pending_confirmation','applying','applied','rejected','superseded','failed')",
            name="ck_agent_canvas_command_plans_status",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "idempotency_key",
            name="uq_agent_canvas_command_plan_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_canvas_command_plans_workflow_status",
        "agent_canvas_command_plans",
        ["workflow_id", "status", "created_at"],
    )
    op.create_table(
        "agent_canvas_command_operation_results",
        sa.Column(
            "plan_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_command_plans.plan_id"),
            primary_key=True,
        ),
        sa.Column("operation_id", sa.Text(), primary_key=True),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "agent_canvas_action_receipts",
        sa.Column("receipt_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_command_plans.plan_id"),
        ),
        sa.Column("action_id", sa.Text()),
        sa.Column("receipt_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "workflow_id",
            "plan_id",
            name="uq_agent_canvas_action_receipt_plan",
        ),
    )
    op.create_table(
        "agent_canvas_variation_drafts",
        sa.Column(
            "source_node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            primary_key=True,
        ),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("source_node_revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("generation_prompt", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text()),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("variation_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "variation_revision > 0",
            name="ck_agent_canvas_variation_revision",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_canvas_variation_drafts")
    op.drop_table("agent_canvas_action_receipts")
    op.drop_table("agent_canvas_command_operation_results")
    op.drop_index(
        "ix_agent_canvas_command_plans_workflow_status",
        table_name="agent_canvas_command_plans",
    )
    op.drop_table("agent_canvas_command_plans")
    with op.batch_alter_table("agent_canvas_workflows") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_workflows_layout_revision",
            type_="check",
        )
        batch.drop_column("layout_revision")
