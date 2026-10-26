"""Persist optional version and rationale without changing historical selections."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_01"
down_revision = "20260917_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_skill_stack", sa.Column("version", sa.Text(), nullable=True))
    op.add_column("brand_skill_stack", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("brand_skill_stack") as batch:
        batch.drop_column("reason")
        batch.drop_column("version")
