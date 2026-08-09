"""Add Agent Canvas media execution settings and automatic Run commands.

Revision ID: 20260806_04
Revises: 20260805_03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_04"
down_revision = "20260805_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_execution_settings",
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("media_execution_mode", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "media_execution_mode IN ('manual', 'automatic')",
            name="ck_agent_canvas_execution_settings_mode",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_agent_canvas_execution_settings_revision",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.PrimaryKeyConstraint("workflow_id"),
    )
    op.create_table(
        "agent_canvas_automatic_run_commands",
        sa.Column("command_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("source_action_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("command_kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_retryable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "command_kind = 'agent_auto_generate'",
            name="ck_agent_canvas_auto_run_command_kind",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'submitted', 'failed')",
            name="ck_agent_canvas_auto_run_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_agent_canvas_auto_run_attempts",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_agent_canvas_auto_run_lease_generation",
        ),
        sa.ForeignKeyConstraint(["node_id"], ["agent_canvas_nodes.node_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.PrimaryKeyConstraint("command_id"),
        sa.UniqueConstraint(
            "workflow_id",
            "source_action_id",
            "node_id",
            "command_kind",
            name="uq_agent_canvas_auto_run_identity",
        ),
    )
    op.create_index(
        "ix_agent_canvas_auto_run_due",
        "agent_canvas_automatic_run_commands",
        ["state", "next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_auto_run_due",
        table_name="agent_canvas_automatic_run_commands",
    )
    op.drop_table("agent_canvas_automatic_run_commands")
    op.drop_table("agent_canvas_execution_settings")
