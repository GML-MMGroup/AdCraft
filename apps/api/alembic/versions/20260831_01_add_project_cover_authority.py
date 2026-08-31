"""Add exact project cover authority fields."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260831_01"
down_revision = "20260830_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("cover_version_id", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "cover_state",
                sa.Text(),
                nullable=False,
                server_default="unresolved",
            )
        )
        batch.add_column(sa.Column("cover_source", sa.Text(), nullable=True))
        batch.add_column(sa.Column("cover_updated_at", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_projects_cover_state",
            "cover_state IN ('ready','unresolved','none','broken')",
        )
        batch.create_check_constraint(
            "ck_projects_cover_source",
            "cover_source IS NULL OR cover_source IN ('manual','product_main','migrated')",
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_projects_cover_source", type_="check")
        batch.drop_constraint("ck_projects_cover_state", type_="check")
        batch.drop_column("cover_updated_at")
        batch.drop_column("cover_source")
        batch.drop_column("cover_state")
        batch.drop_column("cover_version_id")
