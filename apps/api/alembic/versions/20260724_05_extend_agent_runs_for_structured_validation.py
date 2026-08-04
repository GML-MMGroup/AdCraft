"""Extend Agent runs with trusted structured-validation metadata.

Revision ID: 20260724_05
Revises: 20260723_04
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260724_05"
down_revision = "20260723_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add bounded validation authority fields to durable Agent runs."""

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("contract_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("validation_profile", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "validation_context_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch_op.add_column(sa.Column("deadline_at", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove structured-validation metadata from Agent runs."""

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_column("deadline_at")
        batch_op.drop_column("validation_context_json")
        batch_op.drop_column("validation_profile")
        batch_op.drop_column("contract_name")
