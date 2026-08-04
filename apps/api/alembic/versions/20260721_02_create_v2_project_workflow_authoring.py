"""Create V2 Project and immutable Workflow authoring tables.

Revision ID: 20260721_02
Revises: 20260720_01
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260721_02"
down_revision = "20260720_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Project, Workflow pointer, and immutable revision persistence."""

    op.create_table(
        "projects",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cover_asset_id", sa.Text(), nullable=True),
        sa.Column("project_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'trashed')",
            name="ck_projects_status",
        ),
        sa.CheckConstraint("project_version > 0", name="ck_projects_positive_version"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "workflows",
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("current_revision_id", sa.Text(), nullable=True),
        sa.Column("semantic_revision_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("projection_state", sa.Text(), nullable=False, server_default="dirty"),
        sa.Column("projection_revision_no", sa.Integer(), nullable=True),
        sa.Column("projection_error_code", sa.Text(), nullable=True),
        sa.Column("projection_error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("semantic_revision_no >= 0", name="ck_workflows_nonnegative_revision"),
        sa.CheckConstraint("state_version > 0", name="ck_workflows_positive_state_version"),
        sa.CheckConstraint(
            "projection_state IN ('clean', 'dirty')",
            name="ck_workflows_projection_state",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.ForeignKeyConstraint(["current_revision_id"], ["workflow_revisions.revision_id"]),
        sa.PrimaryKeyConstraint("workflow_id"),
        sa.UniqueConstraint("project_id", name="uq_workflows_project_id"),
    )
    op.create_table(
        "workflow_revisions",
        sa.Column("revision_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("document_schema_version", sa.Integer(), nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("change_source", sa.Text(), nullable=False),
        sa.Column("restored_from_revision_no", sa.Integer(), nullable=True),
        sa.Column("source_execution_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("revision_no > 0", name="ck_workflow_revisions_positive_number"),
        sa.CheckConstraint(
            "state_version > 0", name="ck_workflow_revisions_positive_state_version"
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.workflow_id"]),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint("workflow_id", "revision_no", name="uq_workflow_revisions_number"),
        sa.UniqueConstraint("workflow_id", "state_version", name="uq_workflow_revisions_state"),
    )
    op.create_index(
        "ix_workflow_revisions_workflow_number",
        "workflow_revisions",
        ["workflow_id", "revision_no"],
        unique=False,
    )
    op.create_index(
        "uq_workflow_revisions_workflow_source_execution",
        "workflow_revisions",
        ["workflow_id", "source_execution_id"],
        unique=True,
        sqlite_where=sa.text("source_execution_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove V2 Project and authoring tables without altering event history."""

    op.drop_index(
        "uq_workflow_revisions_workflow_source_execution",
        table_name="workflow_revisions",
    )
    op.drop_index("ix_workflow_revisions_workflow_number", table_name="workflow_revisions")
    op.drop_table("workflow_revisions")
    op.drop_table("workflows")
    op.drop_table("projects")
