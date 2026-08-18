"""Add durable guided media resume deliveries.

Revision ID: 20260818_01
Revises: 20260815_03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_01"
down_revision = "20260815_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_guided_media_resume_deliveries",
        sa.Column("delivery_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("confirmation_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.Text(), nullable=False),
        sa.Column("lease_owner_id", sa.Text()),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("terminal_at", sa.Text()),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_agent_canvas_guided_media_resume_status",
        ),
        sa.CheckConstraint(
            "attempt_no >= 0 AND max_attempts = 2 AND lease_generation >= 0",
            name="ck_agent_canvas_guided_media_resume_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND lease_owner_id IS NULL AND lease_expires_at IS NULL "
            "AND error_json IS NULL AND terminal_at IS NULL) OR "
            "(status = 'running' AND lease_owner_id IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND error_json IS NULL "
            "AND terminal_at IS NULL) OR "
            "(status = 'completed' AND lease_owner_id IS NULL "
            "AND lease_expires_at IS NULL AND error_json IS NULL "
            "AND terminal_at IS NOT NULL) OR "
            "(status = 'failed' AND lease_owner_id IS NULL "
            "AND lease_expires_at IS NULL AND error_json IS NOT NULL "
            "AND terminal_at IS NOT NULL)",
            name="ck_agent_canvas_guided_media_resume_state",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["agent_canvas_workflows.workflow_id"],
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["agent_canvas_guided_interaction_submissions.submission_id"],
        ),
        sa.UniqueConstraint(
            "submission_id",
            name="uq_agent_canvas_guided_media_resume_submission",
        ),
    )
    op.create_index(
        "ix_agent_canvas_guided_media_resume_due",
        "agent_canvas_guided_media_resume_deliveries",
        ["status", "available_at", "lease_expires_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_guided_media_resume_due",
        table_name="agent_canvas_guided_media_resume_deliveries",
    )
    op.drop_table("agent_canvas_guided_media_resume_deliveries")
