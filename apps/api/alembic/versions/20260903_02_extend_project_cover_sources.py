"""Extend project cover sources and default new projects to no cover."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_02"
down_revision = "20260903_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_projects_cover_source", type_="check")
        batch.alter_column(
            "cover_state",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default="none",
        )
        batch.create_check_constraint(
            "ck_projects_cover_source",
            "cover_source IS NULL OR cover_source IN "
            "('manual','product_main','scene_main','character_main',"
            "'storyboard_grid','video_poster','migrated')",
        )


def downgrade() -> None:
    op.execute(
        "UPDATE projects SET cover_source = 'migrated' "
        "WHERE cover_source IN "
        "('scene_main','character_main','storyboard_grid','video_poster')"
    )
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_projects_cover_source", type_="check")
        batch.alter_column(
            "cover_state",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default="unresolved",
        )
        batch.create_check_constraint(
            "ck_projects_cover_source",
            "cover_source IS NULL OR cover_source IN "
            "('manual','product_main','migrated')",
        )
