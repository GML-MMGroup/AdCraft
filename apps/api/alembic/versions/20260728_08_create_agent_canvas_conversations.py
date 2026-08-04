"""Create Agent Canvas conversation and Video Skill tables.

Revision ID: 20260728_08
Revises: 20260728_07
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_08"
down_revision = "20260728_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_conversations",
        sa.Column("conversation_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "agent_canvas_skill_runs",
        sa.Column("skill_run_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("skill_version", sa.Text(), nullable=False),
        sa.Column("source_skill_run_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "agent_canvas_planning_topics",
        sa.Column(
            "skill_run_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_skill_runs.skill_run_id"),
            primary_key=True,
        ),
        sa.Column("topic_id", sa.Text(), primary_key=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("related_node_ids_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','in_review','resolved','skipped','not_required')",
            name="ck_agent_canvas_planning_topics_status",
        ),
    )
    op.create_table(
        "agent_canvas_chat_entries",
        sa.Column("entry_id", sa.Text(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("speaker", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_no",
            name="uq_agent_canvas_chat_sequence",
        ),
    )
    op.create_table(
        "agent_canvas_chat_turns",
        sa.Column("turn_id", sa.Text(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("turn_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_agent_canvas_chat_turns_status",
        ),
    )
    op.create_table(
        "agent_canvas_concept_proposals",
        sa.Column("proposal_id", sa.Text(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("proposal_kind", sa.Text(), nullable=False),
        sa.Column("specialist_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("selected_option_id", sa.Text()),
        sa.Column("selection_actor", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','selected','revised','skipped')",
            name="ck_agent_canvas_concept_proposals_status",
        ),
    )
    op.create_table(
        "agent_canvas_concept_options",
        sa.Column("option_id", sa.Text(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_concept_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_table(
        "agent_canvas_expert_activities",
        sa.Column("activity_id", sa.Text(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column("specialist_name", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "agent_canvas_operation_envelopes",
        sa.Column("envelope_id", sa.Text(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_chat_turns.turn_id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("envelope_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_canvas_operation_envelopes")
    op.drop_table("agent_canvas_expert_activities")
    op.drop_table("agent_canvas_concept_options")
    op.drop_table("agent_canvas_concept_proposals")
    op.drop_table("agent_canvas_chat_turns")
    op.drop_table("agent_canvas_chat_entries")
    op.drop_table("agent_canvas_planning_topics")
    op.drop_table("agent_canvas_skill_runs")
    op.drop_table("agent_canvas_conversations")
