"""Add immutable Agent Canvas materialization commit receipts.

Revision ID: 20260811_02
Revises: 20260811_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_02"
down_revision = "20260811_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_materialization_commits",
        sa.Column("materialization_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("action_turn_id", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["agent_canvas_workflows.workflow_id"],
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["agent_canvas_concept_proposals.proposal_id"],
        ),
        sa.PrimaryKeyConstraint("materialization_id"),
        sa.UniqueConstraint(
            "action_turn_id",
            name="uq_agent_canvas_materialization_commit_action_turn",
        ),
    )
    op.create_index(
        "ix_agent_canvas_materialization_commit_workflow_created",
        "agent_canvas_materialization_commits",
        ["workflow_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_canvas_materialization_commit_proposal",
        "agent_canvas_materialization_commits",
        ["proposal_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_materialization_commit_proposal",
        table_name="agent_canvas_materialization_commits",
    )
    op.drop_index(
        "ix_agent_canvas_materialization_commit_workflow_created",
        table_name="agent_canvas_materialization_commits",
    )
    op.drop_table("agent_canvas_materialization_commits")
