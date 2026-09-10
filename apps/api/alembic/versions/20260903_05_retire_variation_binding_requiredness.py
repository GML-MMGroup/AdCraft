"""Retire variation storage and Binding execution requiredness.

Revision ID: 20260903_05
Revises: 20260903_04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_05"
down_revision = "20260903_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("agent_canvas_variation_drafts")
    with op.batch_alter_table("agent_canvas_bindings") as batch:
        batch.drop_column("required")


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_bindings") as batch:
        batch.add_column(
            sa.Column(
                "required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )

    op.create_table(
        "agent_canvas_variation_drafts",
        sa.Column(
            "source_node_id",
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
        sa.Column("source_node_revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("generation_prompt", sa.Text(), nullable=False),
        sa.Column(
            "model_selection_mode",
            sa.Text(),
            nullable=False,
            server_default="default",
        ),
        sa.Column("model_ref", sa.Text()),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("variation_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "variation_revision > 0",
            name="ck_agent_canvas_variation_revision",
        ),
        sa.CheckConstraint(
            "model_selection_mode IN ('default', 'explicit')",
            name="ck_agent_canvas_variations_model_selection",
        ),
    )
