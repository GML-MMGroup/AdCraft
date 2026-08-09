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
    transition_key: Mapped[str | None] = mapped_column(Text, unique=True)
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
    frame_rate: Mapped[float | None] = mapped_column(Float)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)
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


class AgentRunRow(Base):
    """Durable idempotency, lease, and terminal state for one Pi Agent run."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("last_event_seq >= 0", name="ck_agent_runs_nonnegative_event_seq"),
        UniqueConstraint("request_id", name="uq_agent_runs_request_id"),
        Index("ix_agent_runs_status_lease", "status", "lease_expires_at"),
    )

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    workflow_id: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    contract_name: Mapped[str | None] = mapped_column(Text)
    validation_profile: Mapped[str | None] = mapped_column(Text)
    validation_context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    deadline_at: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    lease_owner_id: Mapped[str | None] = mapped_column(Text)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_expires_at: Mapped[str | None] = mapped_column(Text)
    last_event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_target_revision: Mapped[int | None] = mapped_column(Integer)
    terminal_result_json: Mapped[str | None] = mapped_column(Text)
    tool_results_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    safe_error_code: Mapped[str | None] = mapped_column(Text)
    audit_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text)


class V2AgentConversationRow(Base):
    """Durable visible conversation state scoped to one V2 Workflow."""

    __tablename__ = "v2_agent_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_v2_agent_conversations_status",
        ),
        CheckConstraint(
            "last_message_sequence >= 0",
            name="ck_v2_agent_conversations_nonnegative_sequence",
        ),
        Index(
            "ix_v2_agent_conversations_workflow_updated",
            "workflow_id",
            "updated_at",
            "conversation_id",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.workflow_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rolling_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_message_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2AgentMessageRow(Base):
    """One visible user, assistant, or system conversation message."""

    __tablename__ = "v2_agent_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_v2_agent_messages_role",
        ),
        CheckConstraint("sequence_no > 0", name="ck_v2_agent_messages_positive_sequence"),
        UniqueConstraint(
            "conversation_id",
            "sequence_no",
            name="uq_v2_agent_messages_conversation_sequence",
        ),
        Index(
            "ix_v2_agent_messages_conversation_sequence",
            "conversation_id",
            "sequence_no",
        ),
    )

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("v2_agent_conversations.conversation_id"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2AgentActionRow(Base):
    """One idempotent visible action associated with a conversation request."""

    __tablename__ = "v2_agent_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_v2_agent_actions_status",
        ),
        UniqueConstraint(
            "conversation_id",
            "request_id",
            name="uq_v2_agent_actions_conversation_request",
        ),
        Index(
            "ix_v2_agent_actions_conversation_created",
            "conversation_id",
            "created_at",
            "action_id",
        ),
    )

    action_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("v2_agent_conversations.conversation_id"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    action_mode: Mapped[str] = mapped_column(Text, nullable=False)
    target_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    result_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasWorkflowRow(Base):
    """One canonical Agent Canvas workflow owned by a Project."""

    __tablename__ = "agent_canvas_workflows"
    __table_args__ = (
        CheckConstraint(
            "canvas_model = 'agent_canvas_v1'",
            name="ck_agent_canvas_workflows_model",
        ),
        CheckConstraint(
            "workflow_schema_version = 2",
            name="ck_agent_canvas_workflows_schema_version",
        ),
        CheckConstraint("revision > 0", name="ck_agent_canvas_workflows_revision"),
        CheckConstraint(
            "layout_revision > 0",
            name="ck_agent_canvas_workflows_layout_revision",
        ),
        UniqueConstraint("project_id", name="uq_agent_canvas_workflows_project"),
    )

    workflow_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    workflow_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    canvas_model: Mapped[str] = mapped_column(Text, nullable=False, default="agent_canvas_v1")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    layout_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasExecutionSettingsRow(Base):
    """Workflow-scoped media execution preference."""

    __tablename__ = "agent_canvas_execution_settings"
    __table_args__ = (
        CheckConstraint(
            "media_execution_mode IN ('manual', 'automatic')",
            name="ck_agent_canvas_execution_settings_mode",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_agent_canvas_execution_settings_revision",
        ),
    )

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), primary_key=True
    )
    media_execution_mode: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasAutomaticRunCommandRow(Base):
    """Durable post-publication request for canonical selected-node Run."""

    __tablename__ = "agent_canvas_automatic_run_commands"
    __table_args__ = (
        CheckConstraint(
            "command_kind = 'agent_auto_generate'",
            name="ck_agent_canvas_auto_run_command_kind",
        ),
        CheckConstraint(
            "state IN ('pending', 'claimed', 'submitted', 'failed')",
            name="ck_agent_canvas_auto_run_state",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_agent_canvas_auto_run_attempts",
        ),
        CheckConstraint(
            "lease_generation >= 0",
            name="ck_agent_canvas_auto_run_lease_generation",
        ),
        UniqueConstraint(
            "workflow_id",
            "source_action_id",
            "node_id",
            "command_kind",
            name="uq_agent_canvas_auto_run_identity",
        ),
        Index(
            "ix_agent_canvas_auto_run_due",
            "state",
            "next_attempt_at",
            "created_at",
        ),
    )

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    source_action_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"), nullable=False)
    command_kind: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_error_retryable: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentWorkingDocumentRow(Base):
    """One typed Agent-owned coordination document."""

    __tablename__ = "agent_working_documents"
    __table_args__ = (
        CheckConstraint(
            "document_kind IN ('anchor_registry', 'storyboard_production_plan')",
            name="ck_agent_working_documents_kind",
        ),
        CheckConstraint("revision > 0", name="ck_agent_working_documents_revision"),
        UniqueConstraint(
            "workflow_id",
            "guidance_session_id",
            "document_kind",
            name="uq_agent_working_documents_scope_kind",
        ),
        Index(
            "ix_agent_working_documents_workflow_updated",
            "workflow_id",
            "updated_at",
            "document_id",
        ),
    )

    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    guidance_session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_guidance_sessions.session_id"), nullable=False
    )
    document_kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_agent_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_agent_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentWorkingDocumentPatchReceiptRow(Base):
    """Idempotent result for one typed Agent document patch."""

    __tablename__ = "agent_working_document_patch_receipts"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "idempotency_key",
            name="uq_agent_working_document_patch_receipt_key",
        ),
        Index(
            "ix_agent_working_document_patch_receipts_document_created",
            "document_id",
            "created_at",
        ),
    )

    receipt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("agent_working_documents.document_id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    request_digest: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasNodeRow(Base):
    """One generic persisted canvas node."""

    __tablename__ = "agent_canvas_nodes"
    __table_args__ = (
        CheckConstraint(
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing')",
            name="ck_agent_canvas_nodes_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'working', 'ready', 'failed')",
            name="ck_agent_canvas_nodes_status",
        ),
        CheckConstraint("revision > 0", name="ck_agent_canvas_nodes_revision"),
        Index(
            "ix_agent_canvas_nodes_workflow_created",
            "workflow_id",
            "created_at",
            "node_id",
        ),
    )

    node_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    creative_role: Mapped[str] = mapped_column(Text, nullable=False)
    role_contract_version: Mapped[str] = mapped_column(
        Text, nullable=False, default="ad-media-role-v1"
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    summary_prompt: Mapped[str | None] = mapped_column(Text)
    generation_prompt: Mapped[str | None] = mapped_column(Text)
    structured_content_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_selection_mode: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    model_ref: Mapped[str | None] = mapped_column(Text)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    parameter_provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prompt_context_snapshot_id: Mapped[str | None] = mapped_column(Text)
    output_asset_id: Mapped[str | None] = mapped_column(Text)
    position_x: Mapped[float] = mapped_column(Float, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ProviderConnectionRow(Base):
    """Secret-safe installation metadata for one configured provider."""

    __tablename__ = "provider_connections"
    __table_args__ = (
        CheckConstraint(
            "connection_state IN ('configured', 'unconfigured', 'invalid')",
            name="ck_provider_connections_state",
        ),
        CheckConstraint(
            "credential_revision > 0",
            name="ck_provider_connections_positive_revision",
        ),
    )

    provider_id: Mapped[str] = mapped_column(Text, primary_key=True)
    connection_state: Mapped[str] = mapped_column(Text, nullable=False)
    credential_status_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    credential_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ProviderModelRow(Base):
    """One trusted, provider-visible model catalog record."""

    __tablename__ = "provider_models"
    __table_args__ = (
        CheckConstraint(
            "capability IN ('agent', 'text', 'image', 'video', 'audio')",
            name="ck_provider_models_capability",
        ),
        CheckConstraint(
            "availability IN ('available', 'unavailable', 'unauthorized', 'unsupported', 'deprecated')",
            name="ck_provider_models_availability",
        ),
        CheckConstraint("catalog_revision > 0", name="ck_provider_models_positive_revision"),
        Index("ix_provider_models_provider_capability", "provider_id", "capability"),
    )

    model_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("provider_connections.provider_id"), nullable=False
    )
    provider_model_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    capability: Mapped[str] = mapped_column(Text, nullable=False)
    capability_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    availability: Mapped[str] = mapped_column(Text, nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    catalog_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ModelDefaultRow(Base):
    """One installation-scoped default selected from the persisted model catalog."""

    __tablename__ = "model_defaults"
    __table_args__ = (
        CheckConstraint(
            "default_key IN ('agent', 'text', 'image', 'video', 'audio')",
            name="ck_model_defaults_key",
        ),
        CheckConstraint(
            "selection_mode IN ('automatic', 'explicit')",
            name="ck_model_defaults_selection_mode",
        ),
        CheckConstraint("revision > 0", name="ck_model_defaults_positive_revision"),
    )

    default_key: Mapped[str] = mapped_column(Text, primary_key=True)
    model_ref: Mapped[str] = mapped_column(ForeignKey("provider_models.model_ref"), nullable=False)
    selection_mode: Mapped[str] = mapped_column(Text, nullable=False, default="explicit")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ProviderModelSyncRunRow(Base):
    """A bounded audit entry for one provider catalog synchronization attempt."""

    __tablename__ = "provider_model_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_provider_model_sync_runs_status",
        ),
        Index("ix_provider_model_sync_runs_provider_created", "provider_id", "created_at"),
    )

    sync_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("provider_connections.provider_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_revision: Mapped[int | None] = mapped_column(Integer)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasDocumentRow(Base):
    """Typed Text or Script document attached to one canvas node."""

    __tablename__ = "agent_canvas_documents"
    __table_args__ = (
        CheckConstraint(
            "document_kind IN ('text', 'script', 'editing_manifest')",
            name="ck_agent_canvas_documents_kind",
        ),
        CheckConstraint("node_revision > 0", name="ck_agent_canvas_documents_revision"),
        UniqueConstraint("workflow_id", "node_id", name="uq_agent_canvas_documents_workflow_node"),
    )

    node_id: Mapped[str] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    document_kind: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    node_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasBindingRow(Base):
    """One real typed input binding on the Agent Canvas."""

    __tablename__ = "agent_canvas_bindings"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('node_output', 'image_asset')",
            name="ck_agent_canvas_bindings_source_kind",
        ),
        CheckConstraint(
            "input_role IN "
            "('text_context', 'image_reference', 'video_reference', 'audio_reference')",
            name="ck_agent_canvas_bindings_input_role",
        ),
        CheckConstraint("order_index >= 0", name="ck_agent_canvas_bindings_order"),
        Index(
            "ix_agent_canvas_bindings_target_order",
            "workflow_id",
            "target_node_id",
            "order_index",
            "binding_id",
        ),
    )

    binding_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_node_id: Mapped[str | None] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"))
    source_asset_id: Mapped[str | None] = mapped_column(Text)
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_nodes.node_id"), nullable=False
    )
    input_role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasPromptContextSnapshotRow(Base):
    """One immutable materialized Text/Script context bundle."""

    __tablename__ = "agent_canvas_prompt_context_snapshots"
    __table_args__ = (
        Index(
            "ix_agent_canvas_prompt_snapshots_target",
            "workflow_id",
            "target_node_id",
            "created_at",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_nodes.node_id"), nullable=False
    )
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str | None] = mapped_column(Text)
    target_asset_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    binding_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    creative_direction_snapshot_id: Mapped[str | None] = mapped_column(Text)
    skill_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    memory_digest: Mapped[str | None] = mapped_column(Text)
    upstream_summary_digest: Mapped[str | None] = mapped_column(Text)
    byte_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_digest: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasIdempotencyRow(Base):
    """Request fingerprint and replay payload for one Agent Canvas operation."""

    __tablename__ = "agent_canvas_idempotency"
    __table_args__ = (
        UniqueConstraint("operation", "idempotency_key", name="uq_agent_canvas_idempotency_key"),
    )

    record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasCommandPlanRow(Base):
    __tablename__ = "agent_canvas_command_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('pending_confirmation','applying','applied','rejected','superseded','failed')",
            name="ck_agent_canvas_command_plans_status",
        ),
        UniqueConstraint(
            "workflow_id",
            "idempotency_key",
            name="uq_agent_canvas_command_plan_idempotency",
        ),
        Index(
            "ix_agent_canvas_command_plans_workflow_status",
            "workflow_id",
            "status",
            "created_at",
        ),
    )

    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_conversations.conversation_id"), nullable=False
    )
    source_turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_chat_turns.turn_id"), nullable=False
    )
    context_snapshot_id: Mapped[str] = mapped_column(Text, nullable=False)
    base_workflow_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    operations_json: Mapped[str] = mapped_column(Text, nullable=False)
    operation_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False)
    confirmation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    continuation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    target_summary: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_plan_id: Mapped[str | None] = mapped_column(Text)
    replacement_plan_id: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasCommandOperationResultRow(Base):
    __tablename__ = "agent_canvas_command_operation_results"

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_command_plans.plan_id"), primary_key=True
    )
    operation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasActionReceiptRow(Base):
    __tablename__ = "agent_canvas_action_receipts"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "plan_id",
            name="uq_agent_canvas_action_receipt_plan",
        ),
    )

    receipt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("agent_canvas_command_plans.plan_id"))
    action_id: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[str | None] = mapped_column(Text)
    proposal_option_id: Mapped[str | None] = mapped_column(Text)
    proposal_action: Mapped[str | None] = mapped_column(Text)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasVariationDraftRow(Base):
    __tablename__ = "agent_canvas_variation_drafts"
    __table_args__ = (
        CheckConstraint(
            "variation_revision > 0",
            name="ck_agent_canvas_variation_revision",
        ),
    )

    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_nodes.node_id"), primary_key=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    source_node_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    generation_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_selection_mode: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    model_ref: Mapped[str | None] = mapped_column(Text)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    variation_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasConversationRow(Base):
    __tablename__ = "agent_canvas_conversations"

    conversation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False, unique=True
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasSkillRunRow(Base):
    __tablename__ = "agent_canvas_skill_runs"

    skill_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    skill_id: Mapped[str] = mapped_column(Text, nullable=False)
    skill_version: Mapped[str] = mapped_column(Text, nullable=False)
    source_skill_run_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    active_creative_direction_snapshot_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasCreativeDirectionSnapshotRow(Base):
    __tablename__ = "agent_canvas_creative_direction_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "skill_run_id",
            "version",
            name="uq_agent_canvas_creative_direction_version",
        ),
        Index(
            "ix_agent_canvas_creative_direction_workflow_created",
            "workflow_id",
            "created_at",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    skill_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_skill_runs.skill_run_id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_skill_id: Mapped[str | None] = mapped_column(Text)
    source_skill_version: Mapped[str | None] = mapped_column(Text)
    source_skill_digest: Mapped[str | None] = mapped_column(Text)
    global_direction_json: Mapped[str] = mapped_column(Text, nullable=False)
    role_projections_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(Text)
    source_proposal_id: Mapped[str | None] = mapped_column(Text)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasGuidanceSessionRow(Base):
    __tablename__ = "agent_canvas_guidance_sessions"

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    creative_goal_json: Mapped[str] = mapped_column(Text, nullable=False)
    element_decisions_json: Mapped[str] = mapped_column(Text, nullable=False)
    creative_authority_json: Mapped[str | None] = mapped_column(Text)
    current_checkpoint_json: Mapped[str | None] = mapped_column(Text)
    narrative_direction: Mapped[str | None] = mapped_column(Text)
    current_topic_id: Mapped[str | None] = mapped_column(Text)
    active_proposal_id: Mapped[str | None] = mapped_column(Text)
    active_style_skill_run_id: Mapped[str | None] = mapped_column(Text)
    completion_json: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasGuidanceTopicRow(Base):
    __tablename__ = "agent_canvas_guidance_topics"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_guidance_sessions.session_id"), primary_key=True
    )
    topic_id: Mapped[str] = mapped_column(Text, primary_key=True)
    topic_kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    capability_id: Mapped[str] = mapped_column(Text, nullable=False)
    related_node_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_proposal_id: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


# These mappings remain only until the adaptive-recipe callers are removed in the
# clean-cut checkpoint. Migration 20260804_01 removes their physical tables.
class AgentCanvasCreativeMemoryRow(Base):
    __tablename__ = "agent_canvas_creative_memory"

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), primary_key=True
    )
    creative_goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_format: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved_style_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved_node_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    open_questions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    deferred_topics_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rejection_notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    conversation_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_through_sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasChatEntryRow(Base):
    __tablename__ = "agent_canvas_chat_entries"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_no",
            name="uq_agent_canvas_chat_sequence",
        ),
    )

    entry_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_conversations.conversation_id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasChatTurnRow(Base):
    __tablename__ = "agent_canvas_chat_turns"

    turn_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_conversations.conversation_id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    turn_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    creation_mode_json: Mapped[str | None] = mapped_column(Text)
    guidance_session_revision: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasContinuationOutboxRow(Base):
    __tablename__ = "agent_canvas_continuation_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','leased','retry_wait','completed','failed','superseded')",
            name="ck_agent_canvas_continuation_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_agent_canvas_continuation_attempts",
        ),
        CheckConstraint(
            "lease_generation >= 0",
            name="ck_agent_canvas_continuation_lease_generation",
        ),
        CheckConstraint(
            "operation IN ('next_action','capability_command')",
            name="ck_agent_canvas_continuation_operation",
        ),
        UniqueConstraint(
            "continuation_turn_id",
            name="uq_agent_canvas_continuation_turn",
        ),
        UniqueConstraint(
            "conversation_id",
            "payload_digest",
            "operation",
            name="uq_agent_canvas_continuation_delivery",
        ),
        Index(
            "ix_agent_canvas_continuation_due",
            "status",
            "next_attempt_at",
            "created_at",
        ),
    )

    continuation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_conversations.conversation_id"), nullable=False
    )
    source_turn_id: Mapped[str] = mapped_column(Text, nullable=False)
    continuation_turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_chat_turns.turn_id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_digest: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasConceptProposalRow(Base):
    __tablename__ = "agent_canvas_concept_proposals"

    proposal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_chat_turns.turn_id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_kind: Mapped[str] = mapped_column(Text, nullable=False)
    capability_id: Mapped[str] = mapped_column(Text, nullable=False)
    video_skill_run_id: Mapped[str | None] = mapped_column(Text)
    topic_id: Mapped[str | None] = mapped_column(Text)
    target_node_id: Mapped[str | None] = mapped_column(Text)
    target_node_revision: Mapped[int | None] = mapped_column(Integer)
    proposal_purpose: Mapped[str | None] = mapped_column(Text)
    creative_direction_snapshot_id: Mapped[str | None] = mapped_column(Text)
    proposal_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    proposed_references_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_proposal_id: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    guidance_session_id: Mapped[str] = mapped_column(Text, nullable=False)
    guidance_session_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    materialization_id: Mapped[str | None] = mapped_column(Text)
    materialization_option_id: Mapped[str | None] = mapped_column(Text)
    materialization_turn_id: Mapped[str | None] = mapped_column(Text)
    materialization_attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    materialization_status: Mapped[str | None] = mapped_column(Text)
    materialization_retryable: Mapped[bool | None] = mapped_column(Boolean)
    materialization_error_code: Mapped[str | None] = mapped_column(Text)
    materialization_error_message: Mapped[str | None] = mapped_column(Text)
    materialization_created_at: Mapped[str | None] = mapped_column(Text)
    materialization_updated_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasConceptOptionRow(Base):
    __tablename__ = "agent_canvas_concept_options"

    option_id: Mapped[str] = mapped_column(Text, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_concept_proposals.proposal_id"), nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    key_decisions_json: Mapped[str] = mapped_column(Text, nullable=False)
    draft_seed_schema: Mapped[str | None] = mapped_column(Text)
    draft_seed_json: Mapped[str | None] = mapped_column(Text)
    draft_seed_digest: Mapped[str | None] = mapped_column(Text)


class AgentCanvasExpertActivityRow(Base):
    __tablename__ = "agent_canvas_expert_activities"

    activity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_chat_turns.turn_id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    capability_id: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasGuidedActionRow(Base):
    __tablename__ = "agent_canvas_guided_actions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','applying','applied','superseded','failed')",
            name="ck_agent_canvas_guided_actions_state",
        ),
        Index(
            "ix_agent_canvas_guided_actions_workflow_state",
            "workflow_id",
            "state",
            "created_at",
        ),
    )

    action_id: Mapped[str] = mapped_column(Text, primary_key=True)
    logical_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    creating_turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_chat_turns.turn_id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    expected_session_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action_json: Mapped[str] = mapped_column(Text, nullable=False)
    apply_idempotency_key: Mapped[str | None] = mapped_column(Text)
    apply_turn_id: Mapped[str | None] = mapped_column(ForeignKey("agent_canvas_chat_turns.turn_id"))
    receipt_id: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasOperationEnvelopeRow(Base):
    __tablename__ = "agent_canvas_operation_envelopes"

    envelope_id: Mapped[str] = mapped_column(Text, primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_chat_turns.turn_id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    envelope_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasExecutionRow(Base):
    """One durable scheduler execution for an Agent Canvas workflow."""

    __tablename__ = "agent_canvas_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('queued','running','waiting','completed','partial_completed',"
            "'failed','cancelled')",
            name="ck_agent_canvas_executions_status",
        ),
        Index(
            "ix_agent_canvas_executions_workflow_status",
            "workflow_id",
            "status",
            "created_at",
        ),
    )

    execution_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasExecutionMemberRow(Base):
    """One snapshotted node membership in a canvas execution."""

    __tablename__ = "agent_canvas_execution_members"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','waiting','blocked','running','succeeded','failed','cancelled')",
            name="ck_agent_canvas_execution_members_state",
        ),
        UniqueConstraint(
            "execution_id",
            "node_id",
            name="uq_agent_canvas_execution_member",
        ),
        Index(
            "ix_agent_canvas_execution_members_execution_state",
            "execution_id",
            "state",
        ),
    )

    member_id: Mapped[str] = mapped_column(Text, primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_executions.execution_id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"), nullable=False)
    member_order: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str | None] = mapped_column(Text)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_for_node_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provider_task_id: Mapped[str | None] = mapped_column(Text)
    run_intent_snapshot_id: Mapped[str | None] = mapped_column(Text)
    run_intent_snapshot_json: Mapped[str | None] = mapped_column(Text)
    run_intent_snapshot_digest: Mapped[str | None] = mapped_column(Text)
    resolved_input_manifest_id: Mapped[str | None] = mapped_column(Text)
    resolved_input_manifest_json: Mapped[str | None] = mapped_column(Text)
    resolved_input_manifest_digest: Mapped[str | None] = mapped_column(Text)
    effective_parameters_json: Mapped[str | None] = mapped_column(Text)
    parameter_compilation_snapshot_id: Mapped[str | None] = mapped_column(Text)
    omitted_optional_inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    prompt_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasVideoParameterCompilationSnapshotRow(Base):
    """One immutable Video parameter compilation result used by retries."""

    __tablename__ = "agent_canvas_video_parameter_compilation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "member_id",
            name="uq_agent_canvas_video_parameter_snapshot_member",
        ),
        Index(
            "ix_agent_canvas_video_parameter_snapshots_execution",
            "execution_id",
            "member_id",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_executions.execution_id"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_execution_members.member_id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_digest: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasNodeLeaseRow(Base):
    """Compare-and-set lease for one execution member."""

    __tablename__ = "agent_canvas_node_leases"
    __table_args__ = (
        UniqueConstraint("execution_id", "node_id", name="uq_agent_canvas_node_lease"),
        CheckConstraint("generation > 0", name="ck_agent_canvas_node_leases_generation"),
    )

    lease_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_executions.execution_id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    heartbeat_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasProviderTaskRow(Base):
    """Durable provider task kept inside one node execution attempt."""

    __tablename__ = "agent_canvas_provider_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted','waiting','recovering','succeeded','failed','cancelled')",
            name="ck_agent_canvas_provider_tasks_status",
        ),
        Index(
            "ix_agent_canvas_provider_tasks_due",
            "status",
            "next_poll_at",
        ),
    )

    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_executions.execution_id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    remote_task_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    next_poll_at: Mapped[str | None] = mapped_column(Text)
    recovery_deadline: Mapped[str] = mapped_column(Text, nullable=False)
    result_descriptor_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AgentCanvasEditingExportRow(Base):
    """One durable explicit Editing export attempt."""

    __tablename__ = "agent_canvas_editing_exports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','exporting','completed','failed','cancelled')",
            name="ck_agent_canvas_editing_exports_status",
        ),
        Index(
            "ix_agent_canvas_editing_exports_node_status",
            "workflow_id",
            "node_id",
            "status",
            "created_at",
        ),
        UniqueConstraint(
            "workflow_id",
            "node_id",
            "idempotency_key",
            name="uq_agent_canvas_editing_export_idempotency",
        ),
    )

    export_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("agent_canvas_workflows.workflow_id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("agent_canvas_nodes.node_id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    ready_video_node_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    skipped_inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    bgm_node_id: Mapped[str | None] = mapped_column(Text)
    output_asset_id: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
