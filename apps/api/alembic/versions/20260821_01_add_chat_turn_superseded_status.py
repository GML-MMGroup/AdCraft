"""Allow superseded Agent Canvas capability turns.

Revision ID: 20260821_01
Revises: 20260818_01
"""

from alembic import op


revision = "20260821_01"
down_revision = "20260818_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_chat_turns") as batch:
        batch.drop_constraint("ck_agent_canvas_chat_turns_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_chat_turns_status",
            "status IN ('queued','running','completed','failed','superseded')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_chat_turns") as batch:
        batch.drop_constraint("ck_agent_canvas_chat_turns_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_chat_turns_status",
            "status IN ('queued','running','completed','failed')",
        )
