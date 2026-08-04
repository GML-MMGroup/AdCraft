"""Persist durable Agent Canvas guided actions.

Revision ID: 20260730_21
Revises: 20260730_20
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_21"
down_revision = "20260730_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_command_plans") as batch_op:
        batch_op.add_column(
            sa.Column(
                "context_snapshot_id",
                sa.Text(),
                nullable=False,
                server_default="legacy_command_context",
            )
        )
        batch_op.add_column(
            sa.Column(
                "expires_at",
                sa.Text(),
                nullable=False,
                server_default="9999-12-31T23:59:59+00:00",
            )
        )
    op.create_table(
        "agent_canvas_guided_actions",
        sa.Column("action_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "creating_turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("expected_semantic_revision", sa.Integer(), nullable=False),
        sa.Column("action_json", sa.Text(), nullable=False),
        sa.Column("apply_idempotency_key", sa.Text()),
        sa.Column(
            "apply_turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
        ),
        sa.Column("receipt_id", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','applying','applied','failed')",
            name="ck_agent_canvas_guided_actions_state",
        ),
    )
    op.create_index(
        "ix_agent_canvas_guided_actions_workflow_state",
        "agent_canvas_guided_actions",
        ["workflow_id", "state", "created_at"],
    )
    op.create_index(
        "uq_agent_canvas_guided_actions_apply_idempotency",
        "agent_canvas_guided_actions",
        ["workflow_id", "apply_idempotency_key"],
        unique=True,
        sqlite_where=sa.text("apply_idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_canvas_guided_actions_apply_idempotency",
        table_name="agent_canvas_guided_actions",
    )
    op.drop_index(
        "ix_agent_canvas_guided_actions_workflow_state",
        table_name="agent_canvas_guided_actions",
    )
    op.drop_table("agent_canvas_guided_actions")
    with op.batch_alter_table("agent_canvas_command_plans") as batch_op:
        batch_op.drop_column("expires_at")
        batch_op.drop_column("context_snapshot_id")
