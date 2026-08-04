"""Add the superseded Agent Canvas continuation state.

Revision ID: 20260731_24
Revises: 20260731_23
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op


revision = "20260731_24"
down_revision = "20260731_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_continuation_outbox") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_canvas_continuation_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_continuation_status",
            ("status IN ('queued','leased','retry_wait','completed','failed','superseded')"),
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_continuation_outbox") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_canvas_continuation_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_continuation_status",
            "status IN ('queued','leased','retry_wait','completed','failed')",
        )
