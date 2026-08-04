"""Add SQLite-backed provider connection and model registry metadata.

Revision ID: 20260731_25
Revises: 20260731_24
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_25"
down_revision = "20260731_24"
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
    op.create_table(
        "provider_connections",
        sa.Column("provider_id", sa.Text(), primary_key=True),
        sa.Column("connection_state", sa.Text(), nullable=False),
        sa.Column("credential_status_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("credential_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "connection_state IN ('configured', 'unconfigured', 'invalid')",
            name="ck_provider_connections_state",
        ),
        sa.CheckConstraint(
            "credential_revision > 0",
            name="ck_provider_connections_positive_revision",
        ),
    )
    op.create_table(
        "provider_models",
        sa.Column("model_ref", sa.Text(), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Text(),
            sa.ForeignKey("provider_connections.provider_id"),
            nullable=False,
        ),
        sa.Column("provider_model_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("capability_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("availability", sa.Text(), nullable=False),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("catalog_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "capability IN ('agent', 'text', 'image', 'video', 'audio')",
            name="ck_provider_models_capability",
        ),
        sa.CheckConstraint(
            "availability IN ('available', 'unavailable', 'unauthorized', 'unsupported', 'deprecated')",
            name="ck_provider_models_availability",
        ),
        sa.CheckConstraint("catalog_revision > 0", name="ck_provider_models_positive_revision"),
    )
    op.create_index(
        "ix_provider_models_provider_capability",
        "provider_models",
        ["provider_id", "capability"],
    )
    op.create_table(
        "model_defaults",
        sa.Column("default_key", sa.Text(), primary_key=True),
        sa.Column(
            "model_ref",
            sa.Text(),
            sa.ForeignKey("provider_models.model_ref"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "default_key IN ('agent', 'text', 'image', 'video', 'audio')",
            name="ck_model_defaults_key",
        ),
        sa.CheckConstraint("revision > 0", name="ck_model_defaults_positive_revision"),
    )
    op.create_table(
        "provider_model_sync_runs",
        sa.Column("sync_run_id", sa.Text(), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Text(),
            sa.ForeignKey("provider_connections.provider_id"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("catalog_revision", sa.Integer(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_provider_model_sync_runs_status",
        ),
    )
    op.create_index(
        "ix_provider_model_sync_runs_provider_created",
        "provider_model_sync_runs",
        ["provider_id", "created_at"],
    )
    with op.batch_alter_table("agent_canvas_nodes") as batch_op:
        batch_op.add_column(
            sa.Column("model_selection_mode", sa.Text(), nullable=False, server_default="default")
        )
        batch_op.add_column(sa.Column("model_ref", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_agent_canvas_nodes_model_selection",
            "model_selection_mode IN ('default', 'explicit')",
        )

    for raw_model_id, model_ref in _KNOWN_MODEL_REFS.items():
        op.execute(
            sa.text(
                "UPDATE agent_canvas_nodes "
                "SET model_selection_mode = 'explicit', model_ref = :model_ref "
                "WHERE model_id = :raw_model_id"
            ).bindparams(model_ref=model_ref, raw_model_id=raw_model_id)
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch_op:
        batch_op.drop_constraint("ck_agent_canvas_nodes_model_selection", type_="check")
        batch_op.drop_column("model_ref")
        batch_op.drop_column("model_selection_mode")
    op.drop_index(
        "ix_provider_model_sync_runs_provider_created",
        table_name="provider_model_sync_runs",
    )
    op.drop_table("provider_model_sync_runs")
    op.drop_table("model_defaults")
    op.drop_index("ix_provider_models_provider_capability", table_name="provider_models")
    op.drop_table("provider_models")
    op.drop_table("provider_connections")
