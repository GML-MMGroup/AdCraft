"""Add canonical input roles to Agent Canvas bindings.

Revision ID: 20260729_13
Revises: 20260729_12
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_13"
down_revision = "20260729_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_bindings",
        sa.Column("input_role", sa.Text(), nullable=False, server_default="instruction"),
    )
    op.execute(
        "UPDATE agent_canvas_bindings SET input_role = CASE binding_kind "
        "WHEN 'brief_context' THEN 'instruction' "
        "WHEN 'script_context' THEN 'instruction' "
        "WHEN 'image_reference' THEN 'visual_reference' "
        "WHEN 'video_reference' THEN 'source_video' "
        "WHEN 'audio_reference' THEN 'audio_reference' "
        "ELSE 'instruction' END"
    )


def downgrade() -> None:
    op.drop_column("agent_canvas_bindings", "input_role")
