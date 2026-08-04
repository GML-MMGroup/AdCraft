"""Finalize generic Agent Canvas node and binding records.

Revision ID: 20260730_18
Revises: 20260730_17
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_18"
down_revision = "20260730_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE agent_canvas_nodes SET semantic_role = CASE semantic_role "
        "WHEN 'advertising_script' THEN 'script' "
        "WHEN 'character_main' THEN 'character' "
        "WHEN 'final_composition' THEN 'editing' "
        "WHEN 'generic_audio' THEN 'general_audio' "
        "WHEN 'generic_image' THEN 'general_image' "
        "WHEN 'generic_text' THEN 'general_text' "
        "WHEN 'generic_video' THEN 'general_video' "
        "WHEN 'note' THEN 'general_text' "
        "WHEN 'scene_design_board' THEN 'scene' "
        "WHEN 'storyboard_grid' THEN 'storyboard_sequence' "
        "WHEN 'storyboard_video_segment' THEN 'storyboard_video' "
        "WHEN 'shot_video' THEN 'storyboard_video' "
        "ELSE semantic_role END"
    )
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.alter_column("semantic_role", new_column_name="creative_role")
        batch.drop_column("video_skill_run_id")
        batch.drop_column("derived_from_node_id")
        batch.drop_column("source_proposal_id")
        batch.drop_column("source_option_id")

    op.execute(
        "UPDATE agent_canvas_bindings SET source_kind = 'node_output' WHERE source_kind = 'node'"
    )
    op.execute(
        "UPDATE agent_canvas_bindings SET input_role = CASE input_role "
        "WHEN 'instruction' THEN 'text_context' "
        "WHEN 'visual_reference' THEN 'image_reference' "
        "WHEN 'first_frame' THEN 'image_reference' "
        "WHEN 'motion_reference' THEN 'video_reference' "
        "WHEN 'source_video' THEN 'video_reference' "
        "ELSE input_role END"
    )
    with op.batch_alter_table("agent_canvas_bindings") as batch:
        batch.drop_constraint("ck_agent_canvas_bindings_source_kind", type_="check")
        batch.drop_constraint("ck_agent_canvas_bindings_kind", type_="check")
        batch.drop_constraint("ck_agent_canvas_bindings_order", type_="check")
        batch.drop_column("binding_kind")
        batch.alter_column("display_order", new_column_name="order_index")
        batch.add_column(
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("label", sa.Text()))
        batch.add_column(sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("updated_at", sa.Text(), nullable=False, server_default=""))
        batch.create_check_constraint(
            "ck_agent_canvas_bindings_source_kind",
            "source_kind IN ('node_output', 'image_asset')",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_bindings_input_role",
            "input_role IN ('text_context','image_reference','video_reference','audio_reference')",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_bindings_order",
            "order_index >= 0",
        )
    op.execute("UPDATE agent_canvas_bindings SET updated_at = created_at WHERE updated_at = ''")


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_bindings") as batch:
        batch.drop_constraint("ck_agent_canvas_bindings_source_kind", type_="check")
        batch.drop_constraint("ck_agent_canvas_bindings_input_role", type_="check")
        batch.drop_constraint("ck_agent_canvas_bindings_order", type_="check")
        batch.add_column(sa.Column("binding_kind", sa.Text()))
        batch.alter_column("order_index", new_column_name="display_order")
        batch.drop_column("updated_at")
        batch.drop_column("metadata_json")
        batch.drop_column("label")
        batch.drop_column("enabled")
        batch.create_check_constraint(
            "ck_agent_canvas_bindings_source_kind",
            "source_kind IN ('node', 'image_asset')",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_bindings_kind",
            "binding_kind IN ('brief_context','script_context','image_reference',"
            "'video_reference','audio_reference')",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_bindings_order",
            "display_order >= 0",
        )
    op.execute(
        "UPDATE agent_canvas_bindings SET binding_kind = input_role, "
        "source_kind = CASE source_kind WHEN 'node_output' THEN 'node' ELSE source_kind END"
    )

    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.alter_column("creative_role", new_column_name="semantic_role")
        batch.add_column(sa.Column("video_skill_run_id", sa.Text()))
        batch.add_column(sa.Column("derived_from_node_id", sa.Text()))
        batch.add_column(sa.Column("source_proposal_id", sa.Text()))
        batch.add_column(sa.Column("source_option_id", sa.Text()))
