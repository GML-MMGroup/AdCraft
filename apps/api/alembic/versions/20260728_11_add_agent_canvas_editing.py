"""Add durable Agent Canvas Editing exports.

Revision ID: 20260728_11
Revises: 20260728_10
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_11"
down_revision = "20260728_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_editing_exports",
        sa.Column("export_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("manifest_revision", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("ready_video_node_ids_json", sa.Text(), nullable=False),
        sa.Column("skipped_inputs_json", sa.Text(), nullable=False),
        sa.Column("bgm_node_id", sa.Text()),
        sa.Column("output_asset_id", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','exporting','completed','failed','cancelled')",
            name="ck_agent_canvas_editing_exports_status",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "node_id",
            "idempotency_key",
            name="uq_agent_canvas_editing_export_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_canvas_editing_exports_node_status",
        "agent_canvas_editing_exports",
        ["workflow_id", "node_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_editing_exports_node_status",
        table_name="agent_canvas_editing_exports",
    )
    op.drop_table("agent_canvas_editing_exports")
