"""Create durable Pi Agent run coordination state.

Revision ID: 20260723_04
Revises: 20260721_03
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260723_04"
down_revision = "20260721_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add operational Agent run state without storing prompts or credentials."""

    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("parent_run_id", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("workflow_id", sa.Text(), nullable=True),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("lease_owner_id", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.Text(), nullable=True),
        sa.Column("last_event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_target_revision", sa.Integer(), nullable=True),
        sa.Column("terminal_result_json", sa.Text(), nullable=True),
        sa.Column("tool_results_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("safe_error_code", sa.Text(), nullable=True),
        sa.Column("audit_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint("last_event_seq >= 0", name="ck_agent_runs_nonnegative_event_seq"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("request_id", name="uq_agent_runs_request_id"),
    )
    op.create_index(
        "ix_agent_runs_status_lease",
        "agent_runs",
        ["status", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Agent run coordination state."""

    op.drop_index("ix_agent_runs_status_lease", table_name="agent_runs")
    op.drop_table("agent_runs")
