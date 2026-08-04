"""Create durable V2 Agent conversations, messages, and actions.

Revision ID: 20260724_06
Revises: 20260724_05
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260724_06"
down_revision = "20260724_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_agent_conversations",
        sa.Column("conversation_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("rolling_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_message_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_v2_agent_conversations_status",
        ),
        sa.CheckConstraint(
            "last_message_sequence >= 0",
            name="ck_v2_agent_conversations_nonnegative_sequence",
        ),
    )
    op.create_index(
        "ix_v2_agent_conversations_workflow_updated",
        "v2_agent_conversations",
        ["workflow_id", "updated_at", "conversation_id"],
    )
    op.create_table(
        "v2_agent_messages",
        sa.Column("message_id", sa.Text(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("v2_agent_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_v2_agent_messages_role",
        ),
        sa.CheckConstraint(
            "sequence_no > 0",
            name="ck_v2_agent_messages_positive_sequence",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_no",
            name="uq_v2_agent_messages_conversation_sequence",
        ),
    )
    op.create_index(
        "ix_v2_agent_messages_conversation_sequence",
        "v2_agent_messages",
        ["conversation_id", "sequence_no"],
    )
    op.create_table(
        "v2_agent_actions",
        sa.Column("action_id", sa.Text(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("v2_agent_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("action_mode", sa.Text(), nullable=False),
        sa.Column("target_json", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_v2_agent_actions_status",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "request_id",
            name="uq_v2_agent_actions_conversation_request",
        ),
    )
    op.create_index(
        "ix_v2_agent_actions_conversation_created",
        "v2_agent_actions",
        ["conversation_id", "created_at", "action_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_agent_actions_conversation_created",
        table_name="v2_agent_actions",
    )
    op.drop_table("v2_agent_actions")
    op.drop_index(
        "ix_v2_agent_messages_conversation_sequence",
        table_name="v2_agent_messages",
    )
    op.drop_table("v2_agent_messages")
    op.drop_index(
        "ix_v2_agent_conversations_workflow_updated",
        table_name="v2_agent_conversations",
    )
    op.drop_table("v2_agent_conversations")
