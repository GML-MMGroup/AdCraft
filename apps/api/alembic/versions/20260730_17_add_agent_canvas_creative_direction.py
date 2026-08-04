"""Add Agent Canvas Creative Direction and context snapshot metadata.

Revision ID: 20260730_17
Revises: 20260729_16
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_17"
down_revision = "20260729_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_skill_runs") as batch:
        batch.add_column(sa.Column("active_creative_direction_snapshot_id", sa.Text()))

    op.create_table(
        "agent_canvas_creative_direction_snapshots",
        sa.Column("snapshot_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "skill_run_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_skill_runs.skill_run_id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_skill_id", sa.Text()),
        sa.Column("source_skill_version", sa.Text()),
        sa.Column("source_skill_digest", sa.Text()),
        sa.Column("global_direction_json", sa.Text(), nullable=False),
        sa.Column("role_projections_json", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.Text()),
        sa.Column("source_proposal_id", sa.Text()),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "skill_run_id",
            "version",
            name="uq_agent_canvas_creative_direction_version",
        ),
    )
    op.create_index(
        "ix_agent_canvas_creative_direction_workflow_created",
        "agent_canvas_creative_direction_snapshots",
        ["workflow_id", "created_at"],
    )

    with op.batch_alter_table("agent_canvas_prompt_context_snapshots") as batch:
        batch.add_column(sa.Column("turn_id", sa.Text()))
        batch.add_column(sa.Column("role", sa.Text()))
        batch.add_column(sa.Column("operation", sa.Text()))
        batch.add_column(
            sa.Column("target_asset_ids_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("binding_ids_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("creative_direction_snapshot_id", sa.Text()))
        batch.add_column(
            sa.Column("skill_refs_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("memory_digest", sa.Text()))
        batch.add_column(sa.Column("upstream_summary_digest", sa.Text()))
        batch.add_column(
            sa.Column("byte_estimate", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("content_digest", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_prompt_context_snapshots") as batch:
        batch.drop_column("content_digest")
        batch.drop_column("token_estimate")
        batch.drop_column("byte_estimate")
        batch.drop_column("upstream_summary_digest")
        batch.drop_column("memory_digest")
        batch.drop_column("skill_refs_json")
        batch.drop_column("creative_direction_snapshot_id")
        batch.drop_column("binding_ids_json")
        batch.drop_column("target_asset_ids_json")
        batch.drop_column("operation")
        batch.drop_column("role")
        batch.drop_column("turn_id")

    op.drop_index(
        "ix_agent_canvas_creative_direction_workflow_created",
        table_name="agent_canvas_creative_direction_snapshots",
    )
    op.drop_table("agent_canvas_creative_direction_snapshots")

    with op.batch_alter_table("agent_canvas_skill_runs") as batch:
        batch.drop_column("active_creative_direction_snapshot_id")
