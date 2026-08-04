"""Replace adaptive recipes with progressive guidance sessions.

Revision ID: 20260804_01
Revises: 20260803_28
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260804_01"
down_revision = "20260803_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_guidance_sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("guidance_mode", sa.Text(), nullable=False),
        sa.Column("creative_goal_json", sa.Text(), nullable=False),
        sa.Column("element_decisions_json", sa.Text(), nullable=False),
        sa.Column("current_topic_id", sa.Text()),
        sa.Column("active_proposal_id", sa.Text()),
        sa.Column("active_style_skill_run_id", sa.Text()),
        sa.Column("completion_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','paused','completed')",
            name="ck_agent_canvas_guidance_session_status",
        ),
        sa.CheckConstraint(
            "guidance_mode IN ('collaborative','delegated')",
            name="ck_agent_canvas_guidance_session_mode",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_agent_canvas_guidance_session_revision",
        ),
    )
    op.create_table(
        "agent_canvas_guidance_topics",
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_guidance_sessions.session_id"),
            primary_key=True,
        ),
        sa.Column("topic_id", sa.Text(), primary_key=True),
        sa.Column("topic_kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("specialist_name", sa.Text(), nullable=False),
        sa.Column("related_node_ids_json", sa.Text(), nullable=False),
        sa.Column("source_proposal_id", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed','selected','deferred','excluded')",
            name="ck_agent_canvas_guidance_topic_status",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_agent_canvas_guidance_topic_revision",
        ),
    )

    with op.batch_alter_table("agent_canvas_chat_turns") as batch_op:
        batch_op.add_column(sa.Column("guidance_decision_json", sa.Text()))
        batch_op.add_column(sa.Column("guidance_session_revision", sa.Integer()))
        batch_op.drop_column("recipe_revision")
        batch_op.drop_column("recipe_id")

    op.execute("DELETE FROM agent_canvas_concept_options")
    op.execute("DELETE FROM agent_canvas_concept_proposals")
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "guidance_session_id",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "guidance_session_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_concept_proposals_availability",
            "availability IN ('open','applied','superseded')",
        )

    with op.batch_alter_table("agent_canvas_guided_actions") as batch_op:
        batch_op.alter_column(
            "expected_semantic_revision",
            new_column_name="expected_session_revision",
            existing_type=sa.Integer(),
        )

    with op.batch_alter_table("agent_canvas_action_receipts") as batch_op:
        batch_op.add_column(sa.Column("proposal_action", sa.Text()))
        batch_op.drop_column("proposal_generation_action")

    with op.batch_alter_table("agent_canvas_skill_runs") as batch_op:
        batch_op.drop_column("active_recipe_revision")
        batch_op.drop_column("active_recipe_id")
        batch_op.drop_column("creation_mode_json")
        batch_op.drop_column("memory_revision")
        batch_op.drop_column("deferred_topic_ids_json")
        batch_op.drop_column("current_topic_id")

    op.drop_table("agent_canvas_production_recipes")
    op.drop_table("agent_canvas_planning_topics")


def downgrade() -> None:
    op.create_table(
        "agent_canvas_planning_topics",
        sa.Column(
            "skill_run_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_skill_runs.skill_run_id"),
            primary_key=True,
        ),
        sa.Column("topic_id", sa.Text(), primary_key=True),
        sa.Column("topic_kind", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("specialist_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text()),
        sa.Column("related_node_ids_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','in_review','resolved','skipped','not_required','deferred')",
            name="ck_agent_canvas_planning_topics_status",
        ),
    )
    op.create_table(
        "agent_canvas_production_recipes",
        sa.Column("recipe_id", sa.Text(), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column(
            "skill_run_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_skill_runs.skill_run_id"),
        ),
        sa.Column("creation_mode", sa.Text(), nullable=False),
        sa.Column("current_topic_id", sa.Text()),
        sa.Column("stages_json", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("deliverables_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("dependencies_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "recommended_next_topic_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "completion_criteria_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("anchor_digest", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "recipe_id",
            "revision",
            name="uq_agent_canvas_production_recipe_revision",
        ),
    )
    op.create_index(
        "ix_agent_canvas_production_recipe_workflow_revision",
        "agent_canvas_production_recipes",
        ["workflow_id", "created_at"],
    )

    with op.batch_alter_table("agent_canvas_skill_runs") as batch_op:
        batch_op.add_column(sa.Column("current_topic_id", sa.Text()))
        batch_op.add_column(
            sa.Column("deferred_topic_ids_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("memory_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("creation_mode_json", sa.Text()))
        batch_op.add_column(sa.Column("active_recipe_id", sa.Text()))
        batch_op.add_column(sa.Column("active_recipe_revision", sa.Integer()))

    with op.batch_alter_table("agent_canvas_action_receipts") as batch_op:
        batch_op.add_column(sa.Column("proposal_generation_action", sa.Text()))
        batch_op.drop_column("proposal_action")

    with op.batch_alter_table("agent_canvas_guided_actions") as batch_op:
        batch_op.alter_column(
            "expected_session_revision",
            new_column_name="expected_semantic_revision",
            existing_type=sa.Integer(),
        )

    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_canvas_concept_proposals_availability",
            type_="check",
        )
        batch_op.drop_column("guidance_session_revision")
        batch_op.drop_column("guidance_session_id")

    with op.batch_alter_table("agent_canvas_chat_turns") as batch_op:
        batch_op.add_column(sa.Column("recipe_id", sa.Text()))
        batch_op.add_column(sa.Column("recipe_revision", sa.Integer()))
        batch_op.drop_column("guidance_session_revision")
        batch_op.drop_column("guidance_decision_json")

    op.drop_table("agent_canvas_guidance_topics")
    op.drop_table("agent_canvas_guidance_sessions")
