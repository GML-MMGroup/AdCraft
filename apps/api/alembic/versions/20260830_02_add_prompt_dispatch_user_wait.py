"""Add guided user-wait admission to prompt-preparation dispatches."""

from __future__ import annotations

from alembic import op


revision = "20260830_02"
down_revision = "20260830_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_prompt_preparation_outbox") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_prompt_preparation_dispatch_status",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_prompt_preparation_dispatch_status",
            "status IN ('waiting_user','queued','leased','completed','failed','superseded')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_prompt_preparation_outbox") as batch:
        batch.drop_constraint(
            "ck_agent_canvas_prompt_preparation_dispatch_status",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_agent_canvas_prompt_preparation_dispatch_status",
            "status IN ('queued','leased','completed','failed','superseded')",
        )
