"""Persist Agent operation recovery and publication identity.

Revision ID: 20260810_04
Revises: 20260810_03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_04"
down_revision = "20260810_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(
            sa.Column("frozen_policy_digest", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("frozen_input_digest", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("retry_attempt_no", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("attempt_metadata_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column("safe_failure_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column("operation_stage", sa.Text(), nullable=False, server_default="running")
        )
        batch.add_column(sa.Column("completed_result_identity", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("completed_result_identity")
        batch.drop_column("operation_stage")
        batch.drop_column("safe_failure_json")
        batch.drop_column("attempt_metadata_json")
        batch.drop_column("retry_attempt_no")
        batch.drop_column("frozen_input_digest")
        batch.drop_column("frozen_policy_digest")
