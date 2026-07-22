"""SQLAlchemy models for the V2 runtime event persistence boundary."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base model metadata owned by the V2 persistence boundary."""


class WorkflowEventRow(Base):
    """A single ordered V2 runtime event."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        CheckConstraint("seq > 0", name="ck_workflow_events_positive_seq"),
        UniqueConstraint("workflow_id", "seq", name="uq_workflow_events_workflow_seq"),
        Index("ix_workflow_events_workflow_seq", "workflow_id", "seq"),
        Index("ix_workflow_events_execution_seq", "execution_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(Text)
    item_id: Mapped[str | None] = mapped_column(Text)
    slot_id: Mapped[str | None] = mapped_column(Text)
    asset_id: Mapped[str | None] = mapped_column(Text)
    version_id: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class DataMigrationRow(Base):
    """Records the state of one explicit data migration."""

    __tablename__ = "data_migrations"

    migration_name: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_count: Mapped[int | None] = mapped_column(Integer)
    imported_count: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectRow(Base):
    """One durable Project envelope for a V2 Workflow."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'trashed')",
            name="ck_projects_status",
        ),
        CheckConstraint("project_version > 0", name="ck_projects_positive_version"),
    )

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cover_asset_id: Mapped[str | None] = mapped_column(Text)
    project_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(Text)


class WorkflowRow(Base):
    """Current semantic pointer and projection state for one V2 Workflow."""

    __tablename__ = "workflows"
    __table_args__ = (
        CheckConstraint("semantic_revision_no >= 0", name="ck_workflows_nonnegative_revision"),
        CheckConstraint("state_version > 0", name="ck_workflows_positive_state_version"),
        CheckConstraint(
            "projection_state IN ('clean', 'dirty')",
            name="ck_workflows_projection_state",
        ),
        UniqueConstraint("project_id", name="uq_workflows_project_id"),
    )

    workflow_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(Text)
    semantic_revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    projection_state: Mapped[str] = mapped_column(Text, nullable=False, default="dirty")
    projection_revision_no: Mapped[int | None] = mapped_column(Integer)
    projection_error_code: Mapped[str | None] = mapped_column(Text)
    projection_error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class WorkflowRevisionRow(Base):
    """Immutable canonical authoring document for one Workflow revision."""

    __tablename__ = "workflow_revisions"
    __table_args__ = (
        CheckConstraint("revision_no > 0", name="ck_workflow_revisions_positive_number"),
        CheckConstraint("state_version > 0", name="ck_workflow_revisions_positive_state_version"),
        UniqueConstraint("workflow_id", "revision_no", name="uq_workflow_revisions_number"),
        UniqueConstraint("workflow_id", "state_version", name="uq_workflow_revisions_state"),
        Index("ix_workflow_revisions_workflow_number", "workflow_id", "revision_no"),
        Index(
            "uq_workflow_revisions_workflow_source_execution",
            "workflow_id",
            "source_execution_id",
            unique=True,
            sqlite_where=text("source_execution_id IS NOT NULL"),
        ),
    )

    revision_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    change_source: Mapped[str] = mapped_column(Text, nullable=False)
    restored_from_revision_no: Mapped[int | None] = mapped_column(Integer)
    source_execution_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AssetCatalogRow(Base):
    """One durable recommended-catalog installation record."""

    __tablename__ = "asset_catalogs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('not_installed', 'downloading', 'verifying', 'installing', 'ready', 'failed')",
            name="ck_asset_catalogs_status",
        ),
        CheckConstraint("progress_current >= 0", name="ck_asset_catalogs_progress_current"),
        CheckConstraint("progress_total >= 0", name="ck_asset_catalogs_progress_total"),
        UniqueConstraint("catalog_key", "catalog_version", name="uq_asset_catalogs_key_version"),
    )

    catalog_id: Mapped[str] = mapped_column(Text, primary_key=True)
    catalog_key: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    archive_url: Mapped[str] = mapped_column(Text, nullable=False)
    archive_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    license_manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    installed_at: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AssetEntityRow(Base):
    """One recommended or user-owned reusable asset entity."""

    __tablename__ = "asset_entities"
    __table_args__ = (
        CheckConstraint("scope IN ('user', 'recommended')", name="ck_asset_entities_scope"),
        CheckConstraint(
            "entity_type IN ('product', 'character', 'scene', 'prop', 'generic')",
            name="ck_asset_entities_type",
        ),
        CheckConstraint(
            "library_category IN ('characters', 'scenes', 'props')",
            name="ck_asset_entities_category",
        ),
        CheckConstraint("status IN ('active', 'trashed')", name="ck_asset_entities_status"),
        Index("ix_asset_entities_scope_category", "scope", "library_category", "updated_at"),
    )

    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    library_category: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    catalog_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_catalogs.catalog_id"), nullable=True
    )
    derived_from_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_entities.entity_id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    deleted_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AssetRow(Base):
    """Logical asset identity; duplicate bytes intentionally remain distinct rows."""

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            "media_type IN ('image', 'video', 'audio', 'text')", name="ck_assets_media_type"
        ),
        CheckConstraint(
            "source_type IN ('recommended', 'upload', 'generated', 'derived')",
            name="ck_assets_source_type",
        ),
        CheckConstraint("status IN ('active', 'unavailable')", name="ck_assets_status"),
    )

    asset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AssetVersionRow(Base):
    """Immutable version metadata; media bytes remain in filesystem object storage."""

    __tablename__ = "asset_versions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="ck_asset_versions_positive_number"),
        CheckConstraint("size_bytes >= 0", name="ck_asset_versions_nonnegative_size"),
        CheckConstraint("status IN ('ready', 'unavailable')", name="ck_asset_versions_status"),
        UniqueConstraint("asset_id", "version_no", name="uq_asset_versions_number"),
        UniqueConstraint("asset_id", "version_id", name="uq_asset_versions_asset_version"),
        Index("ix_asset_versions_sha256", "sha256"),
    )

    version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.asset_id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    prompt: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    source_workflow_id: Mapped[str | None] = mapped_column(Text)
    source_node_id: Mapped[str | None] = mapped_column(Text)
    source_item_id: Mapped[str | None] = mapped_column(Text)
    source_slot_id: Mapped[str | None] = mapped_column(Text)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_versions.version_id"), nullable=True
    )
    quality_json: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ready")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AssetEntityMemberRow(Base):
    """Ordered reusable-entity membership pinned to an immutable version."""

    __tablename__ = "asset_entity_members"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_asset_entity_members_sort_order"),
        UniqueConstraint("entity_id", "sort_order", name="uq_asset_entity_members_order"),
        UniqueConstraint(
            "entity_id",
            "asset_id",
            "version_id",
            "semantic_type",
            name="uq_asset_entity_members_version_semantic",
        ),
        ForeignKeyConstraint(
            ["asset_id", "version_id"],
            ["asset_versions.asset_id", "asset_versions.version_id"],
        ),
        Index("ix_asset_entity_members_entity_order", "entity_id", "sort_order"),
    )

    member_id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("asset_entities.entity_id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.asset_id"), nullable=False)
    version_id: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AssetBindingRow(Base):
    """Version-pinned reference selection owned by a V2 Workflow slot."""

    __tablename__ = "asset_bindings"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_asset_bindings_sort_order"),
        CheckConstraint("status IN ('active', 'removed')", name="ck_asset_bindings_status"),
        ForeignKeyConstraint(
            ["asset_id", "version_id"],
            ["asset_versions.asset_id", "asset_versions.version_id"],
        ),
        Index(
            "ix_asset_bindings_active_target",
            "workflow_id",
            "target_slot_id",
            "sort_order",
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_asset_bindings_selection_group", "selection_group_id"),
    )

    binding_id: Mapped[str] = mapped_column(Text, primary_key=True)
    selection_group_id: Mapped[str] = mapped_column(Text, nullable=False)
    binding_type: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_node_id: Mapped[str | None] = mapped_column(Text)
    target_item_id: Mapped[str | None] = mapped_column(Text)
    target_slot_id: Mapped[str | None] = mapped_column(Text)
    source_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_entities.entity_id"), nullable=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.asset_id"), nullable=False)
    version_id: Mapped[str] = mapped_column(Text, nullable=False)
    reference_role: Mapped[str | None] = mapped_column(Text)
    use_as_prompt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    removed_at: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
