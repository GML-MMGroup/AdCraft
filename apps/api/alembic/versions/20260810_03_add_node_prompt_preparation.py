"""Add canonical Agent Canvas node prompt-preparation state.

Revision ID: 20260810_03
Revises: 20260810_02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_03"
down_revision = "20260810_02"
branch_labels = None
depends_on = None


_LEGACY_READY = (
    '{"status":"ready","operation_id":null,"attempt_no":0,'
    '"context_snapshot_id":null,"prompt_digest":"'
    + ("0" * 64)
    + '","error":null,"updated_at":"1970-01-01T00:00:00Z"}'
)


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.add_column(
            sa.Column(
                "prompt_preparation_json",
                sa.Text(),
                nullable=False,
                server_default=_LEGACY_READY,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_column("prompt_preparation_json")
