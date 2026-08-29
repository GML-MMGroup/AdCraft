"""Add durable Node prompt-preparation dispatch ownership."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260828_01"
down_revision = "20260827_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_prompt_preparation_outbox",
        sa.Column("dispatch_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("node_revision", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("logical_key", sa.Text(), nullable=False),
        sa.Column("role_variant", sa.Text()),
        sa.Column("occurrence_id", sa.Text()),
        sa.Column("character_phase", sa.Text()),
        sa.Column("context_snapshot_id", sa.Text()),
        sa.Column("context_digest", sa.Text()),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("binding_digest", sa.Text()),
        sa.Column("recipe_digest", sa.Text()),
        sa.Column("style_projection_digest", sa.Text()),
        sa.Column("brief_digest", sa.Text()),
        sa.Column("requirement_revision_id", sa.Text()),
        sa.Column("requirement_revision_no", sa.Integer()),
        sa.Column("document_revisions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("model_policy_revision", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.Text(), nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("supersession_reason", sa.Text()),
        sa.Column("superseded_by_dispatch_id", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("terminal_at", sa.Text()),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["agent_canvas_workflows.workflow_id"],
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["agent_canvas_nodes.node_id"],
        ),
        sa.CheckConstraint(
            "status IN ('queued','leased','completed','failed','superseded')",
            name="ck_agent_canvas_prompt_preparation_dispatch_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_agent_canvas_prompt_preparation_dispatch_attempts",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_agent_canvas_prompt_preparation_dispatch_lease_generation",
        ),
        sa.UniqueConstraint(
            "logical_key",
            name="uq_agent_canvas_prompt_preparation_dispatch_logical_key",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "node_id",
            "operation_id",
            name="uq_agent_canvas_prompt_preparation_dispatch_operation",
        ),
    )
    op.create_index(
        "ix_agent_canvas_prompt_preparation_dispatch_due",
        "agent_canvas_prompt_preparation_outbox",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_agent_canvas_prompt_preparation_dispatch_node",
        "agent_canvas_prompt_preparation_outbox",
        ["workflow_id", "node_id", "node_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_prompt_preparation_dispatch_node",
        table_name="agent_canvas_prompt_preparation_outbox",
    )
    op.drop_index(
        "ix_agent_canvas_prompt_preparation_dispatch_due",
        table_name="agent_canvas_prompt_preparation_outbox",
    )
    op.drop_table("agent_canvas_prompt_preparation_outbox")
