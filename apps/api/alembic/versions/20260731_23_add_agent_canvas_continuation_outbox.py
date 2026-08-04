"""Add the durable Agent Canvas continuation outbox.

Revision ID: 20260731_23
Revises: 20260731_22
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_23"
down_revision = "20260731_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guided_actions") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_canvas_guided_actions_state",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_guided_actions_state",
            "state IN ('pending','applying','applied','superseded','failed')",
        )
    with op.batch_alter_table("workflow_events") as batch_op:
        batch_op.add_column(sa.Column("transition_key", sa.Text()))
        batch_op.create_unique_constraint(
            "uq_workflow_events_transition_key",
            ["transition_key"],
        )
    op.create_table(
        "agent_canvas_continuation_outbox",
        sa.Column("continuation_id", sa.Text(), primary_key=True),
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
        sa.Column("source_turn_id", sa.Text(), nullable=False),
        sa.Column(
            "continuation_turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Text(), nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','leased','retry_wait','completed','failed')",
            name="ck_agent_canvas_continuation_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_agent_canvas_continuation_attempts",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_agent_canvas_continuation_lease_generation",
        ),
        sa.UniqueConstraint(
            "continuation_turn_id",
            name="uq_agent_canvas_continuation_turn",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "payload_digest",
            "operation",
            name="uq_agent_canvas_continuation_delivery",
        ),
    )
    op.create_index(
        "ix_agent_canvas_continuation_due",
        "agent_canvas_continuation_outbox",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_continuation_due",
        table_name="agent_canvas_continuation_outbox",
    )
    op.drop_table("agent_canvas_continuation_outbox")
    with op.batch_alter_table("workflow_events") as batch_op:
        batch_op.drop_constraint(
            "uq_workflow_events_transition_key",
            type_="unique",
        )
        batch_op.drop_column("transition_key")
    with op.batch_alter_table("agent_canvas_guided_actions") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_canvas_guided_actions_state",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_guided_actions_state",
            "state IN ('pending','applying','applied','failed')",
        )
