"""Internal contracts for V2 SQLite event persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class V2EventInsert(BaseModel):
    """Event fields accepted by the repository before it allocates a sequence."""

    workflow_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    project_id: str | None = None
    execution_id: str | None = None
    node_id: str | None = None
    binding_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    action_id: str | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    created_at: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class V2EventSourceStats(BaseModel):
    """Canonical source counts used to verify one workflow import."""

    workflow_id: str
    source_count: int = Field(ge=0)
    max_seq: int = Field(ge=0)


class V2EventMigrationReport(BaseModel):
    """Summary of one canonical V2 event import attempt."""

    migration_name: str
    source_file_count: int = Field(ge=0)
    source_event_count: int = Field(ge=0)
    inserted_event_count: int = Field(ge=0)
    idempotent_event_count: int = Field(ge=0)
    workflow_count: int = Field(ge=0)


class DataMigrationCompletion(BaseModel):
    """A completed migration marker that can share a caller transaction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    migration_name: str = Field(min_length=1)
    source_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    completed_at: str = Field(min_length=1)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class DatabaseBackupReport(BaseModel):
    """Immutable backup result required before the authoring schema upgrade."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_required", "created", "existing"]
    database_path: Path
    backup_path: Path | None = None
    manifest_path: Path | None = None
    source_sha256: str | None = None
    backup_sha256: str | None = None


class PersistenceBootstrapState(BaseModel):
    """Immutable state returned after successful V2 persistence bootstrap."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready"] = "ready"
    database_path: Path
    schema_revision: str
    database_backup_status: Literal["not_required", "created", "existing"] = "not_required"
    data_migration_name: str


class PersistenceBootstrapFailure(BaseModel):
    """Immutable safe state returned when V2 persistence bootstrap fails."""

    model_config = ConfigDict(frozen=True)

    status: Literal["failed"] = "failed"
    code: str
    message: str
    stage: str | None = None


class V2EventPayloadViolation(BaseModel):
    """A stable payload policy violation without raw payload content."""

    code: Literal[
        "v2_event_payload_embedded_media",
        "v2_event_payload_absolute_path",
        "v2_event_payload_too_large",
    ]
    path: str
