"""Add durable Agent Canvas result publication intents."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_04"
down_revision = "20260903_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_result_publication_intents",
        sa.Column("intent_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("member_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("logical_result_key", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("source_snapshot_id", sa.Text(), nullable=False),
        sa.Column("source_snapshot_digest", sa.Text(), nullable=False),
        sa.Column("expected_storage_key", sa.Text(), nullable=False),
        sa.Column("expected_object_sha256", sa.Text(), nullable=False),
        sa.Column("planned_result_json", sa.Text(), nullable=False),
        sa.Column("prepared_result_json", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Text(), nullable=False),
        sa.Column("recovery_deadline", sa.Text(), nullable=False),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("committed_receipt_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "state IN ('preparing','prepared','committed','abandoned')",
            name="ck_agent_canvas_result_publication_intents_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 16",
            name="ck_agent_canvas_result_publication_intents_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["agent_canvas_executions.execution_id"],
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["agent_canvas_execution_members.member_id"],
        ),
        sa.ForeignKeyConstraint(["node_id"], ["agent_canvas_nodes.node_id"]),
        sa.UniqueConstraint(
            "logical_result_key",
            name="uq_agent_canvas_result_publication_intents_result_key",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "member_id",
            name="uq_agent_canvas_result_publication_intents_member",
        ),
    )
    op.create_index(
        "ix_agent_canvas_result_publication_intents_due",
        "agent_canvas_result_publication_intents",
        ["state", "next_attempt_at", "recovery_deadline"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_result_publication_intents_due",
        table_name="agent_canvas_result_publication_intents",
    )
    op.drop_table("agent_canvas_result_publication_intents")
