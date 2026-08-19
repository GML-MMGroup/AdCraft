"""Remove obsolete Agent Canvas World Setting projection bundles.

Revision ID: 20260806_06
Revises: 20260806_05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_06"
down_revision = "20260806_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("agent_canvas_world_setting_projection_bundles")


def downgrade() -> None:
    op.create_table(
        "agent_canvas_world_setting_projection_bundles",
        sa.Column("projection_snapshot_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("source_node_id", sa.Text(), nullable=False),
        sa.Column("source_node_revision", sa.Integer(), nullable=False),
        sa.Column("source_content_digest", sa.Text(), nullable=False),
        sa.Column("projection_contract_version", sa.Text(), nullable=False),
        sa.Column("projection_prompt_digest", sa.Text(), nullable=False),
        sa.Column("projection_skill_digest", sa.Text(), nullable=False),
        sa.Column("model_ref", sa.Text(), nullable=False),
        sa.Column("compiler_digest", sa.Text(), nullable=False),
        sa.Column("projection_mode", sa.Text(), nullable=False),
        sa.Column("shared_projection_json", sa.Text(), nullable=False),
        sa.Column("role_projections_json", sa.Text(), nullable=False),
        sa.Column("projection_digest", sa.Text(), nullable=False),
        sa.Column("warning_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "source_node_revision > 0",
            name="ck_world_setting_projection_positive_source_revision",
        ),
        sa.CheckConstraint(
            "projection_mode IN ('ready', 'fallback')",
            name="ck_world_setting_projection_mode",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["agent_canvas_workflows.workflow_id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["agent_canvas_nodes.node_id"],
        ),
        sa.PrimaryKeyConstraint("projection_snapshot_id"),
        sa.UniqueConstraint(
            "source_node_id",
            "source_node_revision",
            "source_content_digest",
            "compiler_digest",
            name="uq_world_setting_projection_cache_identity",
        ),
    )
    op.create_index(
        "ix_world_setting_projection_workflow_source_revision",
        "agent_canvas_world_setting_projection_bundles",
        ["workflow_id", "source_node_id", "source_node_revision"],
        unique=False,
    )
    op.create_index(
        "ix_world_setting_projection_digest",
        "agent_canvas_world_setting_projection_bundles",
        ["projection_digest"],
        unique=False,
    )
