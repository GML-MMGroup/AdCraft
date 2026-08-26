"""Pin direct Canvas asset bindings to immutable versions.

Revision ID: 20260826_02
Revises: 20260826_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260826_02"
down_revision = "20260826_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_bindings") as batch:
        batch.add_column(sa.Column("source_asset_version_id", sa.Text(), nullable=True))
        batch.create_index(
            "ix_agent_canvas_bindings_asset_version",
            ["source_asset_id", "source_asset_version_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_bindings") as batch:
        batch.drop_index("ix_agent_canvas_bindings_asset_version")
        batch.drop_column("source_asset_version_id")
