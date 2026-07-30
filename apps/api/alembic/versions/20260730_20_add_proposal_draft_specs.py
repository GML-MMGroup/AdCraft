"""Persist private proposal draft prompts.

Revision ID: 20260730_20
Revises: 20260730_19
Create Date: 2026-07-30
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260730_20"
down_revision = "20260730_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_options") as batch_op:
        batch_op.add_column(
            sa.Column(
                "draft_spec_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.add_column(sa.Column("topic_id", sa.Text()))
        batch_op.add_column(sa.Column("creative_direction_snapshot_id", sa.Text()))
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT option_id, description FROM agent_canvas_concept_options "
            "WHERE draft_spec_json = '{}'"
        )
    ).mappings()
    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE agent_canvas_concept_options "
                "SET draft_spec_json = :draft_spec_json WHERE option_id = :option_id"
            ),
            {
                "option_id": row["option_id"],
                "draft_spec_json": json.dumps(
                    {"prompt": row["description"]},
                    separators=(",", ":"),
                ),
            },
        )
    with op.batch_alter_table("agent_canvas_planning_topics") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','in_review','resolved','skipped','not_required',"
            "'working','completed','deferred','reopened')",
        )
    connection.execute(
        sa.text(
            "UPDATE agent_canvas_planning_topics SET status = CASE status "
            "WHEN 'working' THEN 'in_review' "
            "WHEN 'completed' THEN 'resolved' "
            "WHEN 'reopened' THEN 'in_review' "
            "ELSE status END"
        )
    )
    with op.batch_alter_table("agent_canvas_planning_topics") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','in_review','resolved','skipped','not_required','deferred')",
        )
    connection.execute(
        sa.text(
            "UPDATE agent_canvas_expert_activities SET status = 'working' "
            "WHERE status IN ('started', 'waiting')"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_planning_topics") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','in_review','resolved','skipped','not_required',"
            "'working','completed','deferred','reopened')",
        )
    op.get_bind().execute(
        sa.text(
            "UPDATE agent_canvas_planning_topics SET status = CASE status "
            "WHEN 'in_review' THEN 'working' "
            "WHEN 'resolved' THEN 'completed' "
            "WHEN 'not_required' THEN 'skipped' "
            "ELSE status END"
        )
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE agent_canvas_expert_activities SET status = 'started' WHERE status = 'working'"
        )
    )
    with op.batch_alter_table("agent_canvas_planning_topics") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_planning_topics_status", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_canvas_planning_topics_status",
            "status IN ('pending','working','completed','skipped','deferred','reopened')",
        )
    with op.batch_alter_table("agent_canvas_concept_options") as batch_op:
        batch_op.drop_column("draft_spec_json")
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.drop_column("creative_direction_snapshot_id")
        batch_op.drop_column("topic_id")
