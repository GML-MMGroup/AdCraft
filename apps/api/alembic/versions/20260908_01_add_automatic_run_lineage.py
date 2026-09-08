"""Add explicit automatic Run operation lineage.

Revision ID: 20260908_01
Revises: 20260906_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_01"
down_revision = "20260906_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_automatic_run_commands",
        sa.Column("logical_operation_id", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_canvas_automatic_run_commands",
        sa.Column("operation_generation", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "agent_canvas_automatic_run_commands",
        sa.Column("retry_ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_canvas_automatic_run_commands",
        sa.Column("max_automatic_retries", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(
        sa.text(
            "UPDATE agent_canvas_automatic_run_commands "
            "SET logical_operation_id = command_id, "
            "operation_generation = 1, "
            "retry_ordinal = attempt_count, "
            "max_automatic_retries = CASE "
            "WHEN max_attempts > 0 THEN max_attempts - 1 ELSE 0 END"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_automatic_run_commands") as batch:
        batch.drop_column("max_automatic_retries")
        batch.drop_column("retry_ordinal")
        batch.drop_column("operation_generation")
        batch.drop_column("logical_operation_id")
