"""Create the V2 runtime event-store schema.

Revision ID: 20260720_01
Revises:
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the initial V2 persistence tables and indexes."""

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("item_id", sa.Text(), nullable=True),
        sa.Column("slot_id", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.Text(), nullable=True),
        sa.Column("version_id", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("seq > 0", name="ck_workflow_events_positive_seq"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "seq", name="uq_workflow_events_workflow_seq"),
    )
    op.create_index(
        "ix_workflow_events_workflow_seq",
        "workflow_events",
        ["workflow_id", "seq"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_events_execution_seq",
        "workflow_events",
        ["execution_id", "seq"],
        unique=False,
    )
    op.create_table(
        "data_migrations",
        sa.Column("migration_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("migration_name"),
    )


def downgrade() -> None:
    """Remove the initial V2 persistence schema."""

    op.drop_index("ix_workflow_events_execution_seq", table_name="workflow_events")
    op.drop_index("ix_workflow_events_workflow_seq", table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_table("data_migrations")
