"""Retain exact creative method versions while retiring absent seeds."""

from alembic import op
import sqlalchemy as sa

revision = "20261028_02"
down_revision = "20261028_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("creative_skill_catalog", sa.Column("retired_at", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("creative_skill_catalog", "retired_at")
