"""Add user-visible guided proposal references.

Revision ID: 20260729_16
Revises: 20260729_15
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_16"
down_revision = "20260729_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.add_column(
            sa.Column(
                "proposed_references_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.drop_column("proposed_references_json")
