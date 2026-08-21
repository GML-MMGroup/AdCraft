"""Add guided interaction and durable awaiting authority.

Revision ID: 20260815_02
Revises: 20260815_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260815_02"
down_revision = "20260815_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_guided_interactions",
        sa.Column("interaction_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("response_locale", sa.Text(), nullable=False),
        sa.Column("expected_session_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("allowed_actions_json", sa.Text(), nullable=False),
        sa.Column("submit_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('clarification_questionnaire','concept_choice','media_review')",
            name="ck_agent_canvas_guided_interactions_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open','submitted','closed','superseded')",
            name="ck_agent_canvas_guided_interactions_status",
        ),
        sa.CheckConstraint(
            "expected_session_revision > 0 AND revision > 0",
            name="ck_agent_canvas_guided_interactions_revisions",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["agent_canvas_guidance_sessions.session_id"]),
    )
    op.create_index(
        "uq_agent_canvas_guided_interactions_open_checkpoint",
        "agent_canvas_guided_interactions",
        ["workflow_id", "session_id", "checkpoint_id"],
        unique=True,
        sqlite_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_agent_canvas_guided_interactions_workflow_updated",
        "agent_canvas_guided_interactions",
        ["workflow_id", "updated_at", "interaction_id"],
    )

    op.create_table(
        "agent_canvas_guided_interaction_submissions",
        sa.Column("submission_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("interaction_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(
            ["interaction_id"],
            ["agent_canvas_guided_interactions.interaction_id"],
        ),
        sa.UniqueConstraint(
            "interaction_id",
            "idempotency_key",
            name="uq_agent_canvas_guided_submission_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_canvas_guided_submissions_workflow_created",
        "agent_canvas_guided_interaction_submissions",
        ["workflow_id", "created_at", "submission_id"],
    )

    op.create_table(
        "agent_canvas_guidance_awaiting",
        sa.Column("awaiting_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("requires_user_action", sa.Boolean(), nullable=False),
        sa.Column("resume_policy", sa.Text(), nullable=False),
        sa.Column("interaction_id", sa.Text()),
        sa.Column("node_ids_json", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("stage_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('clarification','concept_selection','media_review',"
            "'manual_node_run','milestone_idle')",
            name="ck_agent_canvas_guidance_awaiting_kind",
        ),
        sa.CheckConstraint(
            "resume_policy IN ('submit_interaction','node_terminal',"
            "'next_user_message','explicit_resume')",
            name="ck_agent_canvas_guidance_awaiting_resume_policy",
        ),
        sa.CheckConstraint(
            "stage_revision > 0",
            name="ck_agent_canvas_guidance_awaiting_stage_revision",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["agent_canvas_guidance_sessions.session_id"]),
        sa.ForeignKeyConstraint(
            ["interaction_id"],
            ["agent_canvas_guided_interactions.interaction_id"],
        ),
        sa.UniqueConstraint("workflow_id", name="uq_agent_canvas_guidance_awaiting_workflow"),
        sa.UniqueConstraint(
            "session_id",
            "checkpoint_id",
            name="uq_agent_canvas_guidance_awaiting_checkpoint",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_canvas_guidance_awaiting")
    op.drop_index(
        "ix_agent_canvas_guided_submissions_workflow_created",
        table_name="agent_canvas_guided_interaction_submissions",
    )
    op.drop_table("agent_canvas_guided_interaction_submissions")
    op.drop_index(
        "ix_agent_canvas_guided_interactions_workflow_updated",
        table_name="agent_canvas_guided_interactions",
    )
    op.drop_index(
        "uq_agent_canvas_guided_interactions_open_checkpoint",
        table_name="agent_canvas_guided_interactions",
    )
    op.drop_table("agent_canvas_guided_interactions")
