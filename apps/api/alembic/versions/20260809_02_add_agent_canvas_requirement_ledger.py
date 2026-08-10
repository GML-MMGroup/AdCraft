"""Add canonical Agent Canvas Requirement Ledger persistence.

Revision ID: 20260809_02
Revises: 20260809_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260809_02"
down_revision = "20260809_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_requirement_ledger_revisions",
        sa.Column("revision_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column(
            "parent_revision_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_requirement_ledger_revisions.revision_id"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_turn_id", sa.Text(), nullable=True),
        sa.Column("source_proposal_id", sa.Text(), nullable=True),
        sa.Column("source_node_id", sa.Text(), nullable=True),
        sa.Column("ledger_json", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "revision_no > 0",
            name="ck_agent_canvas_requirement_revisions_positive",
        ),
        sa.CheckConstraint(
            "source_kind IN "
            "('initialization','user_turn','proposal_selection','manual_edit','node_deletion')",
            name="ck_agent_canvas_requirement_revisions_source",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "revision_no",
            name="uq_agent_canvas_requirement_revisions_workflow_no",
        ),
    )
    op.create_index(
        "ix_agent_canvas_requirement_revisions_workflow_no",
        "agent_canvas_requirement_ledger_revisions",
        ["workflow_id", "revision_no"],
    )
    op.create_table(
        "agent_canvas_requirement_ledgers",
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "current_revision_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_requirement_ledger_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("current_revision_no", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "current_revision_no > 0",
            name="ck_agent_canvas_requirement_ledgers_positive",
        ),
    )
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.add_column(sa.Column("requirement_revision_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("requirement_revision_no", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("requirement_digest", sa.Text(), nullable=True))
    with op.batch_alter_table("agent_canvas_prompt_context_snapshots") as batch:
        batch.add_column(sa.Column("requirement_revision_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("requirement_revision_no", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("requirement_digest", sa.Text(), nullable=True))
        batch.add_column(sa.Column("requirement_projection_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_prompt_context_snapshots") as batch:
        batch.drop_column("requirement_projection_digest")
        batch.drop_column("requirement_digest")
        batch.drop_column("requirement_revision_no")
        batch.drop_column("requirement_revision_id")
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.drop_column("requirement_digest")
        batch.drop_column("requirement_revision_no")
        batch.drop_column("requirement_revision_id")
    op.drop_table("agent_canvas_requirement_ledgers")
    op.drop_index(
        "ix_agent_canvas_requirement_revisions_workflow_no",
        table_name="agent_canvas_requirement_ledger_revisions",
    )
    op.drop_table("agent_canvas_requirement_ledger_revisions")
