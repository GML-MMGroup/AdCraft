"""Persist Agent Canvas advertising role contract versions.

Revision ID: 20260728_09
Revises: 20260728_08
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_09"
down_revision = "20260728_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_nodes",
        sa.Column(
            "role_contract_version",
            sa.Text(),
            nullable=False,
            server_default="ad-media-role-v1",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_canvas_nodes", "role_contract_version")
