"""Create Agent Canvas V1 authoring tables.

Revision ID: 20260728_07
Revises: 20260724_06
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_07"
down_revision = "20260724_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_workflows",
        sa.Column("workflow_id", sa.Text(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.project_id"),
            nullable=False,
        ),
        sa.Column("workflow_schema_version", sa.Integer(), nullable=False),
        sa.Column("canvas_model", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "canvas_model = 'agent_canvas_v1'",
            name="ck_agent_canvas_workflows_model",
        ),
        sa.CheckConstraint(
            "workflow_schema_version = 2",
            name="ck_agent_canvas_workflows_schema_version",
        ),
        sa.CheckConstraint("revision > 0", name="ck_agent_canvas_workflows_revision"),
        sa.UniqueConstraint(
            "project_id",
            name="uq_agent_canvas_workflows_project",
        ),
    )
    op.create_table(
        "agent_canvas_nodes",
        sa.Column("node_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("semantic_role", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("summary_prompt", sa.Text(), nullable=True),
        sa.Column("generation_prompt", sa.Text(), nullable=True),
        sa.Column("structured_content_json", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("prompt_context_snapshot_id", sa.Text(), nullable=True),
        sa.Column("output_asset_id", sa.Text(), nullable=True),
        sa.Column("video_skill_run_id", sa.Text(), nullable=True),
        sa.Column("position_x", sa.Float(), nullable=False),
        sa.Column("position_y", sa.Float(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing')",
            name="ck_agent_canvas_nodes_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'working', 'ready', 'failed')",
            name="ck_agent_canvas_nodes_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_agent_canvas_nodes_revision"),
    )
    op.create_index(
        "ix_agent_canvas_nodes_workflow_created",
        "agent_canvas_nodes",
        ["workflow_id", "created_at", "node_id"],
    )
    op.create_table(
        "agent_canvas_documents",
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            primary_key=True,
        ),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("document_kind", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("node_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "document_kind IN ('text', 'script', 'editing_manifest')",
            name="ck_agent_canvas_documents_kind",
        ),
        sa.CheckConstraint(
            "node_revision > 0",
            name="ck_agent_canvas_documents_revision",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "node_id",
            name="uq_agent_canvas_documents_workflow_node",
        ),
    )
    op.create_table(
        "agent_canvas_bindings",
        sa.Column("binding_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "source_node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=True,
        ),
        sa.Column("source_asset_id", sa.Text(), nullable=True),
        sa.Column(
            "target_node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=False,
        ),
        sa.Column("binding_kind", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('node', 'image_asset')",
            name="ck_agent_canvas_bindings_source_kind",
        ),
        sa.CheckConstraint(
            "binding_kind IN "
            "('brief_context', 'script_context', 'image_reference', "
            "'video_reference', 'audio_reference')",
            name="ck_agent_canvas_bindings_kind",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_agent_canvas_bindings_order",
        ),
    )
    op.create_index(
        "ix_agent_canvas_bindings_target_order",
        "agent_canvas_bindings",
        ["workflow_id", "target_node_id", "display_order", "binding_id"],
    )
    op.create_table(
        "agent_canvas_prompt_context_snapshots",
        sa.Column("snapshot_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id"),
            nullable=False,
        ),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_agent_canvas_prompt_snapshots_target",
        "agent_canvas_prompt_context_snapshots",
        ["workflow_id", "target_node_id", "created_at"],
    )
    op.create_table(
        "agent_canvas_idempotency",
        sa.Column("record_id", sa.Text(), primary_key=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "operation",
            "idempotency_key",
            name="uq_agent_canvas_idempotency_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_canvas_idempotency")
    op.drop_index(
        "ix_agent_canvas_prompt_snapshots_target",
        table_name="agent_canvas_prompt_context_snapshots",
    )
    op.drop_table("agent_canvas_prompt_context_snapshots")
    op.drop_index(
        "ix_agent_canvas_bindings_target_order",
        table_name="agent_canvas_bindings",
    )
    op.drop_table("agent_canvas_bindings")
    op.drop_table("agent_canvas_documents")
    op.drop_index(
        "ix_agent_canvas_nodes_workflow_created",
        table_name="agent_canvas_nodes",
    )
    op.drop_table("agent_canvas_nodes")
    op.drop_table("agent_canvas_workflows")
