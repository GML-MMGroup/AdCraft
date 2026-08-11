"""Add the canonical Agent Canvas response locale.

Revision ID: 20260811_01
Revises: 20260810_05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_01"
down_revision = "20260810_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_guidance_sessions",
        sa.Column(
            "response_locale",
            sa.String(length=64),
            nullable=False,
            server_default="und",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_canvas_guidance_sessions", "response_locale")
