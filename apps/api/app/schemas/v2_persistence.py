"""Internal contracts for V2 SQLite event persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class V2EventInsert(BaseModel):
    """Event fields accepted by the repository before it allocates a sequence."""

    workflow_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    execution_id: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
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


class PersistenceBootstrapState(BaseModel):
    """Immutable state returned after successful V2 persistence bootstrap."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready"] = "ready"
    database_path: Path
    schema_revision: str
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
