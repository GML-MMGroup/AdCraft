"""Add private Draft Seed columns to Agent Canvas Proposal options.

Revision ID: 20260809_01
Revises: 20260808_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260809_01"
down_revision = "20260808_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_options") as batch:
        batch.add_column(sa.Column("draft_seed_schema", sa.Text(), nullable=True))
        batch.add_column(sa.Column("draft_seed_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("draft_seed_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_options") as batch:
        batch.drop_column("draft_seed_digest")
        batch.drop_column("draft_seed_json")
        batch.drop_column("draft_seed_schema")
