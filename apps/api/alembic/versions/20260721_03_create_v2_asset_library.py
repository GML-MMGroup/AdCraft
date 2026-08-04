"""Create V2 unified asset-library metadata tables.

Revision ID: 20260721_03
Revises: 20260721_02
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260721_03"
down_revision = "20260721_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add relational V2 asset metadata without storing media bytes in SQLite."""

    op.create_table(
        "asset_catalogs",
        sa.Column("catalog_id", sa.Text(), nullable=False),
        sa.Column("catalog_key", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.Text(), nullable=False),
        sa.Column("archive_url", sa.Text(), nullable=False),
        sa.Column("archive_sha256", sa.Text(), nullable=False),
        sa.Column("license_manifest_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("installed_at", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('not_installed', 'downloading', 'verifying', 'installing', 'ready', 'failed')",
            name="ck_asset_catalogs_status",
        ),
        sa.CheckConstraint("progress_current >= 0", name="ck_asset_catalogs_progress_current"),
        sa.CheckConstraint("progress_total >= 0", name="ck_asset_catalogs_progress_total"),
        sa.PrimaryKeyConstraint("catalog_id"),
        sa.UniqueConstraint("catalog_key", "catalog_version", name="uq_asset_catalogs_key_version"),
    )
    op.create_table(
        "asset_entities",
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("library_category", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("catalog_id", sa.Text(), nullable=True),
        sa.Column("derived_from_entity_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("scope IN ('user', 'recommended')", name="ck_asset_entities_scope"),
        sa.CheckConstraint(
            "entity_type IN ('product', 'character', 'scene', 'prop', 'generic')",
            name="ck_asset_entities_type",
        ),
        sa.CheckConstraint(
            "library_category IN ('characters', 'scenes', 'props')",
            name="ck_asset_entities_category",
        ),
        sa.CheckConstraint("status IN ('active', 'trashed')", name="ck_asset_entities_status"),
        sa.ForeignKeyConstraint(["catalog_id"], ["asset_catalogs.catalog_id"]),
        sa.ForeignKeyConstraint(["derived_from_entity_id"], ["asset_entities.entity_id"]),
        sa.PrimaryKeyConstraint("entity_id"),
    )
    op.create_index(
        "ix_asset_entities_scope_category",
        "asset_entities",
        ["scope", "library_category", "updated_at"],
        unique=False,
    )
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('image', 'video', 'audio', 'text')", name="ck_assets_media_type"
        ),
        sa.CheckConstraint(
            "source_type IN ('recommended', 'upload', 'generated', 'derived')",
            name="ck_assets_source_type",
        ),
        sa.CheckConstraint("status IN ('active', 'unavailable')", name="ck_assets_status"),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_table(
        "asset_versions",
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("source_workflow_id", sa.Text(), nullable=True),
        sa.Column("source_node_id", sa.Text(), nullable=True),
        sa.Column("source_item_id", sa.Text(), nullable=True),
        sa.Column("source_slot_id", sa.Text(), nullable=True),
        sa.Column("parent_version_id", sa.Text(), nullable=True),
        sa.Column("quality_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("version_no > 0", name="ck_asset_versions_positive_number"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_asset_versions_nonnegative_size"),
        sa.CheckConstraint("status IN ('ready', 'unavailable')", name="ck_asset_versions_status"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["asset_versions.version_id"]),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("asset_id", "version_no", name="uq_asset_versions_number"),
        sa.UniqueConstraint("asset_id", "version_id", name="uq_asset_versions_asset_version"),
    )
    op.create_index("ix_asset_versions_sha256", "asset_versions", ["sha256"], unique=False)
    op.create_table(
        "asset_entity_members",
        sa.Column("member_id", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("semantic_type", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default_reference", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name="ck_asset_entity_members_sort_order"),
        sa.ForeignKeyConstraint(["entity_id"], ["asset_entities.entity_id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"]),
        sa.ForeignKeyConstraint(
            ["asset_id", "version_id"],
            ["asset_versions.asset_id", "asset_versions.version_id"],
        ),
        sa.PrimaryKeyConstraint("member_id"),
        sa.UniqueConstraint("entity_id", "sort_order", name="uq_asset_entity_members_order"),
        sa.UniqueConstraint(
            "entity_id",
            "asset_id",
            "version_id",
            "semantic_type",
            name="uq_asset_entity_members_version_semantic",
        ),
    )
    op.create_index(
        "ix_asset_entity_members_entity_order",
        "asset_entity_members",
        ["entity_id", "sort_order"],
        unique=False,
    )
    op.create_table(
        "asset_bindings",
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("selection_group_id", sa.Text(), nullable=False),
        sa.Column("binding_type", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("target_node_id", sa.Text(), nullable=True),
        sa.Column("target_item_id", sa.Text(), nullable=True),
        sa.Column("target_slot_id", sa.Text(), nullable=True),
        sa.Column("source_entity_id", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("reference_role", sa.Text(), nullable=True),
        sa.Column("use_as_prompt", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("removed_at", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name="ck_asset_bindings_sort_order"),
        sa.CheckConstraint("status IN ('active', 'removed')", name="ck_asset_bindings_status"),
        sa.ForeignKeyConstraint(["source_entity_id"], ["asset_entities.entity_id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"]),
        sa.ForeignKeyConstraint(
            ["asset_id", "version_id"],
            ["asset_versions.asset_id", "asset_versions.version_id"],
        ),
        sa.PrimaryKeyConstraint("binding_id"),
    )
    op.create_index(
        "ix_asset_bindings_active_target",
        "asset_bindings",
        ["workflow_id", "target_slot_id", "sort_order"],
        unique=False,
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_asset_bindings_selection_group",
        "asset_bindings",
        ["selection_group_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove asset-library metadata only; media objects are never deleted."""

    op.drop_index("ix_asset_bindings_selection_group", table_name="asset_bindings")
    op.drop_index("ix_asset_bindings_active_target", table_name="asset_bindings")
    op.drop_table("asset_bindings")
    op.drop_index("ix_asset_entity_members_entity_order", table_name="asset_entity_members")
    op.drop_table("asset_entity_members")
    op.drop_index("ix_asset_versions_sha256", table_name="asset_versions")
    op.drop_table("asset_versions")
    op.drop_table("assets")
    op.drop_index("ix_asset_entities_scope_category", table_name="asset_entities")
    op.drop_table("asset_entities")
    op.drop_table("asset_catalogs")
