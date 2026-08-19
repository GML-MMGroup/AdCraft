"""Add durable Agent Canvas Decision Bundles.

Revision ID: 20260810_01
Revises: 20260809_02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_01"
down_revision = "20260809_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_decision_bundles",
        sa.Column("bundle_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_conversations.conversation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column(
            "replacement_bundle_id",
            sa.Text(),
            sa.ForeignKey("agent_decision_bundles.bundle_id"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("answer_json", sa.Text(), nullable=True),
        sa.Column("requirement_revision_no", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("request_fingerprint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("closed_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open','answered','skipped','superseded')",
            name="ck_agent_decision_bundles_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_agent_decision_bundles_revision"),
    )
    op.create_index(
        "uq_agent_decision_bundles_open_conversation",
        "agent_decision_bundles",
        ["conversation_id"],
        unique=True,
        sqlite_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_agent_decision_bundles_workflow_created",
        "agent_decision_bundles",
        ["workflow_id", "created_at"],
    )
    op.create_index(
        "ix_agent_decision_bundles_conversation_created",
        "agent_decision_bundles",
        ["conversation_id", "created_at"],
    )
    with op.batch_alter_table("agent_canvas_requirement_ledger_revisions") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_requirement_revisions_source",
            type_="check",
        )
        batch.add_column(sa.Column("source_bundle_id", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_agent_canvas_requirement_revisions_source",
            "source_kind IN "
            "('initialization','user_turn','proposal_selection','manual_edit','node_deletion',"
            "'decision_bundle_answer')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_requirement_ledger_revisions") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_requirement_revisions_source",
            type_="check",
        )
        batch.drop_column("source_bundle_id")
        batch.create_check_constraint(
            "ck_agent_canvas_requirement_revisions_source",
            "source_kind IN "
            "('initialization','user_turn','proposal_selection','manual_edit','node_deletion')",
        )
    op.drop_index(
        "ix_agent_decision_bundles_conversation_created",
        table_name="agent_decision_bundles",
    )
    op.drop_index(
        "ix_agent_decision_bundles_workflow_created",
        table_name="agent_decision_bundles",
    )
    op.drop_index(
        "uq_agent_decision_bundles_open_conversation",
        table_name="agent_decision_bundles",
    )
    op.drop_table("agent_decision_bundles")
