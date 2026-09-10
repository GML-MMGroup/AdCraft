"""Allow typed Character and Scene reference interactions."""

from __future__ import annotations

from alembic import op


revision = "20260830_01"
down_revision = "20260829_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guided_interactions") as batch:
        batch.drop_constraint("ck_agent_canvas_guided_interactions_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guided_interactions_kind",
            "kind IN ('clarification_questionnaire','concept_choice','product_source',"
            "'reference_source','media_review')",
        )
    with op.batch_alter_table("agent_canvas_guidance_awaiting") as batch:
        batch.drop_constraint("ck_agent_canvas_guidance_awaiting_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guidance_awaiting_kind",
            "kind IN ('clarification','concept_selection','product_source','reference_source',"
            "'media_review','manual_node_run','milestone_idle')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_guidance_awaiting") as batch:
        batch.drop_constraint("ck_agent_canvas_guidance_awaiting_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guidance_awaiting_kind",
            "kind IN ('clarification','concept_selection','product_source','media_review',"
            "'manual_node_run','milestone_idle')",
        )
    with op.batch_alter_table("agent_canvas_guided_interactions") as batch:
        batch.drop_constraint("ck_agent_canvas_guided_interactions_kind", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_guided_interactions_kind",
            "kind IN ('clarification_questionnaire','concept_choice','product_source',"
            "'media_review')",
        )
