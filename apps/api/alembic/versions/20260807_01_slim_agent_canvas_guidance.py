"""Slim Agent Canvas guidance persistence contracts.

Revision ID: 20260807_01
Revises: 20260806_07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_01"
down_revision = "20260806_07"
branch_labels = None
depends_on = None


_CONVERSATION_TABLES = (
    "agent_working_document_patch_receipts",
    "agent_working_documents",
    "agent_canvas_command_operation_results",
    "agent_canvas_action_receipts",
    "agent_canvas_command_plans",
    "agent_canvas_guided_actions",
    "agent_canvas_continuation_outbox",
    "agent_canvas_concept_options",
    "agent_canvas_concept_proposals",
    "agent_canvas_expert_activities",
    "agent_canvas_chat_entries",
    "agent_canvas_operation_envelopes",
    "agent_canvas_chat_turns",
    "agent_canvas_guidance_topics",
    "agent_canvas_guidance_sessions",
    "agent_canvas_conversations",
)


def upgrade() -> None:
    for table_name in _CONVERSATION_TABLES:
        op.execute(f"DELETE FROM {table_name}")

    with op.batch_alter_table("agent_canvas_chat_turns") as batch_op:
        batch_op.drop_column("guidance_decision_json")

    for table_name in (
        "agent_canvas_guidance_topics",
        "agent_canvas_concept_proposals",
        "agent_canvas_expert_activities",
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "specialist_name",
                new_column_name="capability_id",
                existing_type=sa.Text(),
                existing_nullable=False,
            )

    with op.batch_alter_table("agent_canvas_continuation_outbox") as batch_op:
        batch_op.create_check_constraint(
            "ck_agent_canvas_continuation_operation",
            "operation IN ('next_action','capability_command')",
        )


def downgrade() -> None:
    for table_name in _CONVERSATION_TABLES:
        op.execute(f"DELETE FROM {table_name}")

    with op.batch_alter_table("agent_canvas_continuation_outbox") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_canvas_continuation_operation",
            type_="check",
        )

    for table_name in (
        "agent_canvas_guidance_topics",
        "agent_canvas_concept_proposals",
        "agent_canvas_expert_activities",
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "capability_id",
                new_column_name="specialist_name",
                existing_type=sa.Text(),
                existing_nullable=False,
            )

    with op.batch_alter_table("agent_canvas_chat_turns") as batch_op:
        batch_op.add_column(sa.Column("guidance_decision_json", sa.Text()))
