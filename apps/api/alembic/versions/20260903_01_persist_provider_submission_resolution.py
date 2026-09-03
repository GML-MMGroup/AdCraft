"""Persist the frozen model resolution on provider submission intents."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_01"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_provider_submission_intents",
        sa.Column("frozen_model_resolution_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(
        "agent_canvas_provider_submission_intents",
        "frozen_model_resolution_json",
    )
