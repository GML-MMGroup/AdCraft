"""Persist the exact creative method selected for a world direction."""

from alembic import op
import sqlalchemy as sa

revision = "20261028_01"
down_revision = "20261021_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_canvas_concept_options", sa.Column("creative_method_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "agent_canvas_concept_options",
        sa.Column("creative_method_version", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_canvas_concept_options", "creative_method_version")
    op.drop_column("agent_canvas_concept_options", "creative_method_id")
