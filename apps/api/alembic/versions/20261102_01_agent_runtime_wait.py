"""Persist bounded runtime availability waits independently of task attempts."""

from alembic import op
import sqlalchemy as sa

revision = "20261102_01"
down_revision = "20261029_01"
branch_labels = None
depends_on = None

_TABLES = (
    "agent_canvas_continuation_outbox",
    "agent_canvas_prompt_preparation_outbox",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("runtime_wait_started_at", sa.Text(), nullable=True))
        op.add_column(
            table, sa.Column("runtime_wait_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, "runtime_wait_count")
        op.drop_column(table, "runtime_wait_started_at")
