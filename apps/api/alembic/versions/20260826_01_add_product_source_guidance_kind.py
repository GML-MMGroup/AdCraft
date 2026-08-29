"""Allow typed Product source Guidance interactions and waits.

Revision ID: 20260826_01
Revises: 20260824_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260826_01"
down_revision = "20260824_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guided_interactions") as batch:
        batch.drop_constraint("ck_agent_canvas_guided_interactions_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guided_interactions_kind",
            "kind IN ('clarification_questionnaire','concept_choice','product_source','media_review')",
        )
    with op.batch_alter_table("agent_canvas_guidance_awaiting") as batch:
        batch.drop_constraint("ck_agent_canvas_guidance_awaiting_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guidance_awaiting_kind",
            "kind IN ('clarification','concept_selection','product_source','media_review',"
            "'manual_node_run','milestone_idle')",
        )
    op.create_table(
        "agent_canvas_guided_product_handoffs",
        sa.Column("handoff_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("input_kind", sa.Text(), nullable=False),
        sa.Column("asset_versions_json", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("consumed_at", sa.Text()),
        sa.CheckConstraint(
            "input_kind IN ('main','multiview')",
            name="ck_agent_canvas_guided_product_handoff_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','consumed')",
            name="ck_agent_canvas_guided_product_handoff_status",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["agent_canvas_guidance_sessions.session_id"]),
    )
    op.create_index(
        "ix_agent_canvas_guided_product_handoffs_workflow_created",
        "agent_canvas_guided_product_handoffs",
        ["workflow_id", "created_at", "handoff_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_guided_product_handoffs_workflow_created",
        table_name="agent_canvas_guided_product_handoffs",
    )
    op.drop_table("agent_canvas_guided_product_handoffs")
    with op.batch_alter_table("agent_canvas_guidance_awaiting") as batch:
        batch.drop_constraint("ck_agent_canvas_guidance_awaiting_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guidance_awaiting_kind",
            "kind IN ('clarification','concept_selection','media_review',"
            "'manual_node_run','milestone_idle')",
        )
    with op.batch_alter_table("agent_canvas_guided_interactions") as batch:
        batch.drop_constraint("ck_agent_canvas_guided_interactions_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guided_interactions_kind",
            "kind IN ('clarification_questionnaire','concept_choice','media_review')",
        )
