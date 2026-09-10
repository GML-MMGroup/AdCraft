"""Persist immutable Character Proposal occurrence scope."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260829_01"
down_revision = "20260828_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.add_column(sa.Column("character_occurrence_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("character_occurrence_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("character_occurrence_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("character_phase", sa.Text(), nullable=True))
        batch.add_column(sa.Column("character_scope_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.drop_column("character_scope_digest")
        batch.drop_column("character_phase")
        batch.drop_column("character_occurrence_count")
        batch.drop_column("character_occurrence_index")
        batch.drop_column("character_occurrence_id")
