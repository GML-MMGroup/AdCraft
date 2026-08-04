"""Add Agent Canvas execution, lease, and provider task persistence.

Revision ID: 20260728_10
Revises: 20260728_09
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_10"
down_revision = "20260728_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_executions",
        sa.Column("execution_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('queued','running','waiting','completed','partial_completed',"
            "'failed','cancelled')",
            name="ck_agent_canvas_executions_status",
        ),
    )
    op.create_index(
        "ix_agent_canvas_executions_workflow_status",
        "agent_canvas_executions",
        ["workflow_id", "status", "created_at"],
    )
    op.create_table(
        "agent_canvas_execution_members",
        sa.Column("member_id", sa.Text(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_executions.execution_id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=False,
        ),
        sa.Column("member_order", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text()),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waiting_for_node_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("provider_task_id", sa.Text()),
        sa.Column("prompt_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_json", sa.Text()),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "execution_id",
            "node_id",
            name="uq_agent_canvas_execution_member",
        ),
        sa.CheckConstraint(
            "state IN ('queued','waiting','running','succeeded','failed','cancelled')",
            name="ck_agent_canvas_execution_members_state",
        ),
    )
    op.create_index(
        "ix_agent_canvas_execution_members_execution_state",
        "agent_canvas_execution_members",
        ["execution_id", "state"],
    )
    op.create_table(
        "agent_canvas_node_leases",
        sa.Column("lease_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column(
            "execution_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_executions.execution_id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("heartbeat_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("execution_id", "node_id", name="uq_agent_canvas_node_lease"),
        sa.CheckConstraint("generation > 0", name="ck_agent_canvas_node_leases_generation"),
    )
    op.create_table(
        "agent_canvas_provider_tasks",
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column(
            "execution_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_executions.execution_id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("remote_task_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("next_poll_at", sa.Text()),
        sa.Column("recovery_deadline", sa.Text(), nullable=False),
        sa.Column("result_descriptor_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('submitted','waiting','recovering','succeeded','failed','cancelled')",
            name="ck_agent_canvas_provider_tasks_status",
        ),
    )
    op.create_index(
        "ix_agent_canvas_provider_tasks_due",
        "agent_canvas_provider_tasks",
        ["status", "next_poll_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_provider_tasks_due",
        table_name="agent_canvas_provider_tasks",
    )
    op.drop_table("agent_canvas_provider_tasks")
    op.drop_table("agent_canvas_node_leases")
    op.drop_index(
        "ix_agent_canvas_execution_members_execution_state",
        table_name="agent_canvas_execution_members",
    )
    op.drop_table("agent_canvas_execution_members")
    op.drop_index(
        "ix_agent_canvas_executions_workflow_status",
        table_name="agent_canvas_executions",
    )
    op.drop_table("agent_canvas_executions")
