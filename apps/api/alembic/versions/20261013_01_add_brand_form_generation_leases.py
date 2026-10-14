"""Prevent duplicate concurrent Brand foundation form generation."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261013_01"
down_revision = "20261012_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_form_generation_leases",
        sa.Column("generation_key", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("stage_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("form_json", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.Text(), nullable=False),
        sa.Column("lease_until", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('generating', 'published')",
            name="ck_brand_form_generation_leases_status",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "stage",
            "stage_revision",
            name="uq_brand_form_generation_leases_scope",
        ),
    )
    op.create_index(
        "ix_brand_form_generation_leases_workflow",
        "brand_form_generation_leases",
        ["workflow_id", "stage", "stage_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brand_form_generation_leases_workflow",
        table_name="brand_form_generation_leases",
    )
    op.drop_table("brand_form_generation_leases")
