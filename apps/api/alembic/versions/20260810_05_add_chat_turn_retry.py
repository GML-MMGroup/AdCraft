"""Add failed chat-turn retry lineage and safe recovery metadata.

Revision ID: 20260810_05
Revises: 20260810_04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_05"
down_revision = "20260810_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_chat_turns") as batch:
        batch.add_column(sa.Column("retry_of_turn_id", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("retry_attempt_no", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("operation_stage", sa.Text(), nullable=True))
        batch.add_column(sa.Column("operation_failure_json", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("retry_snapshot_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.create_foreign_key(
            "fk_agent_canvas_chat_turn_retry_parent",
            "agent_canvas_chat_turns",
            ["retry_of_turn_id"],
            ["turn_id"],
        )
    op.create_index(
        "uq_agent_canvas_chat_turn_active_retry",
        "agent_canvas_chat_turns",
        ["retry_of_turn_id"],
        unique=True,
        sqlite_where=sa.text("retry_of_turn_id IS NOT NULL AND status IN ('queued','running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_canvas_chat_turn_active_retry",
        table_name="agent_canvas_chat_turns",
    )
    with op.batch_alter_table("agent_canvas_chat_turns") as batch:
        batch.drop_constraint(
            "fk_agent_canvas_chat_turn_retry_parent",
            type_="foreignkey",
        )
        batch.drop_column("retry_snapshot_json")
        batch.drop_column("operation_failure_json")
        batch.drop_column("operation_stage")
        batch.drop_column("retryable")
        batch.drop_column("retry_attempt_no")
        batch.drop_column("retry_of_turn_id")
