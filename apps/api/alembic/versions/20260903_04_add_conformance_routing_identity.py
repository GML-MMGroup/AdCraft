"""Bind provider conformance to an optional frozen routing policy."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_04"
down_revision = "20260903_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_model_conformance_runs") as batch:
        batch.add_column(sa.Column("routing_policy_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("routing_policy_digest", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_provider_model_conformance_routing_pair",
            "(routing_policy_id IS NULL AND routing_policy_digest IS NULL) OR "
            "(routing_policy_id IS NOT NULL AND routing_policy_digest IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_model_conformance_runs") as batch:
        batch.drop_constraint(
            "ck_provider_model_conformance_routing_pair",
            type_="check",
        )
        batch.drop_column("routing_policy_digest")
        batch.drop_column("routing_policy_id")
