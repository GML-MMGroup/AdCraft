"""Add durable progressive creative-session state.

Revision ID: 20260729_15
Revises: 20260729_14
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_15"
down_revision = "20260729_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_skill_runs") as batch:
        batch.add_column(sa.Column("status", sa.Text(), nullable=False, server_default="active"))
        batch.add_column(sa.Column("current_topic_id", sa.Text()))
        batch.add_column(
            sa.Column("deferred_topic_ids_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("memory_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("updated_at", sa.Text(), nullable=False, server_default=""))
    op.execute("UPDATE agent_canvas_skill_runs SET updated_at = created_at WHERE updated_at = ''")
    op.execute(
        "UPDATE agent_canvas_skill_runs AS older SET status = 'superseded' "
        "WHERE EXISTS (SELECT 1 FROM agent_canvas_skill_runs AS newer "
        "WHERE newer.workflow_id = older.workflow_id "
        "AND (newer.updated_at > older.updated_at "
        "OR (newer.updated_at = older.updated_at AND newer.skill_run_id > older.skill_run_id)))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_canvas_skill_runs_one_active "
        "ON agent_canvas_skill_runs(workflow_id) WHERE status = 'active'"
    )

    with op.batch_alter_table("agent_canvas_planning_topics") as batch:
        batch.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch.add_column(
            sa.Column("topic_kind", sa.Text(), nullable=False, server_default="generic")
        )
        batch.add_column(
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("specialist_name", sa.Text(), nullable=False, server_default="script_writer")
        )
        batch.add_column(sa.Column("outcome", sa.Text()))
        batch.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','in_review','resolved','skipped','not_required',"
            "'working','completed','deferred','reopened')",
        )
    op.execute(
        "UPDATE agent_canvas_planning_topics SET status = CASE status "
        "WHEN 'in_review' THEN 'working' "
        "WHEN 'resolved' THEN 'completed' "
        "WHEN 'not_required' THEN 'skipped' "
        "ELSE status END"
    )
    with op.batch_alter_table("agent_canvas_planning_topics") as batch:
        batch.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','working','completed','skipped','deferred','reopened')",
        )

    op.create_table(
        "agent_canvas_creative_memory",
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            primary_key=True,
        ),
        sa.Column("creative_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_format", sa.Text(), nullable=False, server_default=""),
        sa.Column("approved_style_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("approved_node_ids_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("open_questions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("deferred_topics_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rejection_notes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("conversation_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_through_sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memory_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )

    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.add_column(sa.Column("derived_from_node_id", sa.Text()))
        batch.add_column(sa.Column("source_proposal_id", sa.Text()))
        batch.add_column(sa.Column("source_option_id", sa.Text()))
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.add_column(sa.Column("video_skill_run_id", sa.Text()))
        batch.add_column(
            sa.Column("proposal_revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("source_proposal_id", sa.Text()))
        batch.add_column(sa.Column("publication_identity", sa.Text()))
        batch.create_unique_constraint(
            "uq_agent_canvas_proposal_publication_identity",
            ["publication_identity"],
        )
    with op.batch_alter_table("agent_canvas_expert_activities") as batch:
        batch.add_column(sa.Column("workflow_id", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("error_code", sa.Text()))
        batch.add_column(sa.Column("error_message", sa.Text()))
    op.execute(
        "UPDATE agent_canvas_expert_activities SET workflow_id = ("
        "SELECT workflow_id FROM agent_canvas_chat_turns "
        "WHERE agent_canvas_chat_turns.turn_id = agent_canvas_expert_activities.turn_id) "
        "WHERE workflow_id = ''"
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_expert_activities") as batch:
        batch.drop_column("error_message")
        batch.drop_column("error_code")
        batch.drop_column("workflow_id")
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.drop_constraint("uq_agent_canvas_proposal_publication_identity", type_="unique")
        batch.drop_column("publication_identity")
        batch.drop_column("source_proposal_id")
        batch.drop_column("proposal_revision")
        batch.drop_column("video_skill_run_id")
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_column("source_option_id")
        batch.drop_column("source_proposal_id")
        batch.drop_column("derived_from_node_id")
    op.drop_table("agent_canvas_creative_memory")
    with op.batch_alter_table("agent_canvas_planning_topics") as batch:
        batch.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','in_review','resolved','skipped','not_required',"
            "'working','completed','deferred','reopened')",
        )
    op.execute(
        "UPDATE agent_canvas_planning_topics SET status = CASE status "
        "WHEN 'working' THEN 'in_review' "
        "WHEN 'completed' THEN 'resolved' "
        "WHEN 'deferred' THEN 'pending' "
        "WHEN 'reopened' THEN 'in_review' "
        "ELSE status END"
    )
    with op.batch_alter_table("agent_canvas_planning_topics") as batch:
        batch.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','in_review','resolved','skipped','not_required')",
        )
        batch.drop_column("outcome")
        batch.drop_column("specialist_name")
        batch.drop_column("required")
        batch.drop_column("topic_kind")
    op.execute("DROP INDEX uq_agent_canvas_skill_runs_one_active")
    with op.batch_alter_table("agent_canvas_skill_runs") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("memory_revision")
        batch.drop_column("deferred_topic_ids_json")
        batch.drop_column("current_topic_id")
        batch.drop_column("status")
