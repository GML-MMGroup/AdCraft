"""Allow independent supplemental Brand form generation rounds."""

from __future__ import annotations

from alembic import op


revision = "20261014_01"
down_revision = "20261013_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("brand_form_generation_leases") as batch:
        batch.drop_constraint("uq_brand_form_generation_leases_scope", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("brand_form_generation_leases") as batch:
        batch.create_unique_constraint(
            "uq_brand_form_generation_leases_scope",
            ["workflow_id", "stage", "stage_revision"],
        )
