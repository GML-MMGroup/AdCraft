"""Persist one automatic default delivery per newly opted-in Editing node."""

from alembic import op
import sqlalchemy as sa

revision = "20261113_01"
down_revision = "20261112_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_canvas_editing_default_exports",
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_nodes.node_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("export_id", sa.Text(), nullable=True),
        sa.Column("output_node_id", sa.Text(), nullable=True),
        sa.Column("position_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('waiting','exporting','completed','failed','skipped')",
            name="ck_editing_default_exports_status",
        ),
    )
    op.create_index(
        "ix_editing_default_exports_pending",
        "agent_canvas_editing_default_exports",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM agent_canvas_editing_default_exports LIMIT 1"))
        .first()
    ):
        raise RuntimeError(
            "Restore a pre-upgrade backup before removing automatic delivery receipts."
        )
    op.drop_table("agent_canvas_editing_default_exports")
