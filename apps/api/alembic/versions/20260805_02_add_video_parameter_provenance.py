"""Persist Agent Canvas video parameter provenance.

Revision ID: 20260805_02
Revises: 20260804_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260805_02"
down_revision = "20260804_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_nodes",
        sa.Column(
            "parameter_provenance_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "agent_canvas_execution_members",
        sa.Column("parameter_compilation_snapshot_id", sa.Text(), nullable=True),
    )
    op.create_table(
        "agent_canvas_video_parameter_compilation_snapshots",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("member_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("snapshot_digest", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_canvas_executions.execution_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["agent_canvas_execution_members.member_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("member_id", name="uq_agent_canvas_video_parameter_snapshot_member"),
    )
    op.create_index(
        "ix_agent_canvas_video_parameter_snapshots_execution",
        "agent_canvas_video_parameter_compilation_snapshots",
        ["execution_id", "member_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_video_parameter_snapshots_execution",
        table_name="agent_canvas_video_parameter_compilation_snapshots",
    )
    op.drop_table("agent_canvas_video_parameter_compilation_snapshots")
    op.drop_column("agent_canvas_execution_members", "parameter_compilation_snapshot_id")
    op.drop_column("agent_canvas_nodes", "parameter_provenance_json")
