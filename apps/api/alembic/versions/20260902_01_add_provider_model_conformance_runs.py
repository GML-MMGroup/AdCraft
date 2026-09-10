"""Add secret-safe provider model conformance evidence."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_01"
down_revision = "20260831_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_model_conformance_runs",
        sa.Column("conformance_run_id", sa.Text(), primary_key=True),
        sa.Column(
            "model_ref",
            sa.Text(),
            sa.ForeignKey("provider_models.model_ref"),
            nullable=False,
        ),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("adapter_id", sa.Text(), nullable=False),
        sa.Column("transport_kind", sa.Text(), nullable=False),
        sa.Column("adapter_revision", sa.Text(), nullable=False),
        sa.Column("capability_revision", sa.Text(), nullable=False),
        sa.Column("contract_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="unverified"),
        sa.Column("safe_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('unverified', 'compatible', 'certified', 'revoked')",
            name="ck_provider_model_conformance_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_provider_model_conformance_revision"),
    )
    op.create_index(
        "ix_provider_model_conformance_model_operation",
        "provider_model_conformance_runs",
        ["model_ref", "operation", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_model_conformance_model_operation",
        table_name="provider_model_conformance_runs",
    )
    op.drop_table("provider_model_conformance_runs")
