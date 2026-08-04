"""Persist adaptive Agent Canvas production recipe revisions.

Revision ID: 20260731_22
Revises: 20260730_21
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_22"
down_revision = "20260730_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_skill_runs") as batch_op:
        batch_op.add_column(sa.Column("creation_mode_json", sa.Text()))
        batch_op.add_column(sa.Column("active_recipe_id", sa.Text()))
        batch_op.add_column(sa.Column("active_recipe_revision", sa.Integer()))
    with op.batch_alter_table("agent_canvas_chat_turns") as batch_op:
        batch_op.add_column(sa.Column("creation_mode_json", sa.Text()))
        batch_op.add_column(sa.Column("recipe_id", sa.Text()))
        batch_op.add_column(sa.Column("recipe_revision", sa.Integer()))
    op.create_table(
        "agent_canvas_production_recipes",
        sa.Column("recipe_id", sa.Text(), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column(
            "skill_run_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_skill_runs.skill_run_id"),
        ),
        sa.Column("creation_mode", sa.Text(), nullable=False),
        sa.Column("current_topic_id", sa.Text()),
        sa.Column("stages_json", sa.Text(), nullable=False),
        sa.Column("anchor_digest", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "recipe_id",
            "revision",
            name="uq_agent_canvas_production_recipe_revision",
        ),
    )
    op.create_index(
        "ix_agent_canvas_production_recipe_workflow_revision",
        "agent_canvas_production_recipes",
        ["workflow_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_production_recipe_workflow_revision",
        table_name="agent_canvas_production_recipes",
    )
    op.drop_table("agent_canvas_production_recipes")
    with op.batch_alter_table("agent_canvas_chat_turns") as batch_op:
        batch_op.drop_column("recipe_revision")
        batch_op.drop_column("recipe_id")
        batch_op.drop_column("creation_mode_json")
    with op.batch_alter_table("agent_canvas_skill_runs") as batch_op:
        batch_op.drop_column("active_recipe_revision")
        batch_op.drop_column("active_recipe_id")
        batch_op.drop_column("creation_mode_json")
