"""Remove retired raw Agent Canvas model identifiers.

Revision ID: 20260731_26
Revises: 20260731_25
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_26"
down_revision = "20260731_25"
branch_labels = None
depends_on = None


_KNOWN_MODEL_REFS = {
    "zai-org/GLM-5.2": "siliconflow:zai-org/GLM-5.2",
    "doubao-seed-2-0-mini-260428": "volcengine_ark:doubao-seed-2-0-mini-260428",
    "doubao-seedream-5-0-lite-260128": "volcengine_ark:doubao-seedream-5-0-lite-260128",
    "doubao-seedance-2-0-fast-260128": "volcengine_ark:doubao-seedance-2-0-fast-260128",
    "TemPolor i3": "tianpuyue:TemPolor-i3",
    "TemPolor i3.5": "tianpuyue:TemPolor-i3.5",
}


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_variation_drafts") as batch_op:
        batch_op.add_column(
            sa.Column("model_selection_mode", sa.Text(), nullable=False, server_default="default")
        )
        batch_op.add_column(sa.Column("model_ref", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_agent_canvas_variations_model_selection",
            "model_selection_mode IN ('default', 'explicit')",
        )

    for raw_model_id, model_ref in _KNOWN_MODEL_REFS.items():
        for table in ("agent_canvas_nodes", "agent_canvas_variation_drafts"):
            op.execute(
                sa.text(
                    f"UPDATE {table} "
                    "SET model_selection_mode = 'explicit', model_ref = :model_ref "
                    "WHERE model_id = :raw_model_id"
                ).bindparams(model_ref=model_ref, raw_model_id=raw_model_id)
            )

    with op.batch_alter_table("agent_canvas_nodes") as batch_op:
        batch_op.drop_column("model_id")
    with op.batch_alter_table("agent_canvas_variation_drafts") as batch_op:
        batch_op.drop_column("model_id")


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_variation_drafts") as batch_op:
        batch_op.add_column(sa.Column("model_id", sa.Text(), nullable=True))
        batch_op.drop_constraint("ck_agent_canvas_variations_model_selection", type_="check")
        batch_op.drop_column("model_ref")
        batch_op.drop_column("model_selection_mode")
    with op.batch_alter_table("agent_canvas_nodes") as batch_op:
        batch_op.add_column(sa.Column("model_id", sa.Text(), nullable=True))
