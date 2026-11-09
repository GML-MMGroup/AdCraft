"""Durable continuation of accepted Brand decisions."""

from alembic import op
import sqlalchemy as sa

revision = "20261109_01"
down_revision = "20261102_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_continuations",
        sa.Column("work_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.Text()),
        sa.Column("lease_until", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','failed','completed','superseded')",
            name="ck_brand_continuations_status",
        ),
    )
    op.create_index("ix_brand_continuations_due", "brand_continuations", ["status", "lease_until"])
    op.create_index(
        "ix_brand_continuations_workflow",
        "brand_continuations",
        ["workflow_id", "current_revision"],
    )


def downgrade() -> None:
    op.drop_table("brand_continuations")
