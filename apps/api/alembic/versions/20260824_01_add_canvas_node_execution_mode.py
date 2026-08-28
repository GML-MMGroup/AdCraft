"""Add explicit execution authority to Agent Canvas nodes."""

from alembic import op
import sqlalchemy as sa


revision = "20260824_01"
down_revision = "20260823_01"
branch_labels = None
depends_on = None


_LEGACY_READY = (
    '{"status":"ready","operation_id":null,"attempt_no":0,'
    '"context_snapshot_id":null,"prompt_digest":"'
    + ("0" * 64)
    + '","error":null,"updated_at":"1970-01-01T00:00:00Z"}'
)


def upgrade() -> None:
    with op.batch_alter_table(
        "agent_canvas_nodes",
        reflect_args=(
            sa.Column(
                "prompt_preparation_json",
                sa.Text(),
                nullable=False,
                server_default=_LEGACY_READY,
            ),
        ),
    ) as batch:
        batch.add_column(
            sa.Column(
                "execution_mode",
                sa.Text(),
                nullable=False,
                server_default="generative",
            )
        )
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_execution_mode",
            "execution_mode IN ('generative', 'source_only')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_execution_mode", type_="check")
        batch.drop_column("execution_mode")
