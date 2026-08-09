"""Separate capability Proposals from selected-option Materialization.

Revision ID: 20260808_01
Revises: 20260807_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_01"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM agent_canvas_concept_options")
    op.execute("DELETE FROM agent_canvas_concept_proposals")
    op.execute("DELETE FROM agent_canvas_continuation_outbox")
    op.execute("DELETE FROM agent_canvas_operation_envelopes")

    with op.batch_alter_table("agent_canvas_concept_options") as batch_op:
        batch_op.drop_column("draft_spec_json")
        batch_op.add_column(
            sa.Column("key_decisions_json", sa.Text(), nullable=False, server_default="[]")
        )

    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.add_column(sa.Column("materialization_id", sa.Text()))
        batch_op.add_column(sa.Column("materialization_option_id", sa.Text()))
        batch_op.add_column(sa.Column("materialization_turn_id", sa.Text()))
        batch_op.add_column(
            sa.Column(
                "materialization_attempt_no",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("materialization_status", sa.Text()))
        batch_op.add_column(sa.Column("materialization_retryable", sa.Boolean()))
        batch_op.add_column(sa.Column("materialization_error_code", sa.Text()))
        batch_op.add_column(sa.Column("materialization_error_message", sa.Text()))
        batch_op.add_column(sa.Column("materialization_created_at", sa.Text()))
        batch_op.add_column(sa.Column("materialization_updated_at", sa.Text()))

    with op.batch_alter_table("agent_canvas_continuation_outbox") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_continuation_operation", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_canvas_continuation_operation",
            "operation IN ('next_action','capability_command','capability_materialization')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM agent_canvas_concept_options")
    op.execute("DELETE FROM agent_canvas_concept_proposals")
    op.execute("DELETE FROM agent_canvas_continuation_outbox")
    op.execute("DELETE FROM agent_canvas_operation_envelopes")

    with op.batch_alter_table("agent_canvas_continuation_outbox") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_continuation_operation", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_canvas_continuation_operation",
            "operation IN ('next_action','capability_command')",
        )

    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        for column in (
            "materialization_updated_at",
            "materialization_created_at",
            "materialization_error_message",
            "materialization_error_code",
            "materialization_retryable",
            "materialization_status",
            "materialization_attempt_no",
            "materialization_turn_id",
            "materialization_option_id",
            "materialization_id",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("agent_canvas_concept_options") as batch_op:
        batch_op.drop_column("key_decisions_json")
        batch_op.add_column(
            sa.Column("draft_spec_json", sa.Text(), nullable=False, server_default="{}")
        )
