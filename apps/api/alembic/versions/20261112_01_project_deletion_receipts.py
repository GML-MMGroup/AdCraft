"""Persist permanent Project deletion and recoverable object cleanup."""

from alembic import op
import sqlalchemy as sa

revision = "20261112_01"
down_revision = "20261109_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_deletion_receipts",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("project_version", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("cleanup_completed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM project_deletion_receipts LIMIT 1")).first():
        raise RuntimeError("Restore a pre-deletion backup before removing deletion tombstones.")
    op.drop_table("project_deletion_receipts")
