"""Private authority contracts for durable Agent Canvas Editing exports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_editing import (
    EditingExportRuntimeV2,
    EditingManifestV2,
    EditingSkippedInputV2,
)
from app.schemas.agent_canvas_runtime_authority import PreparedContentObjectV2


_SHA256 = r"^[a-f0-9]{64}$"
_FINGERPRINT = r"^sha256:[a-f0-9]{64}$"


class _EditingAuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionAssertionV2(_EditingAuthorityModel):
    asset_id: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=_SHA256)


class FencedLeaseTokenV2(_EditingAuthorityModel):
    resource_type: Literal["editing_export"]
    resource_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(min_length=1, max_length=160)
    generation: int = Field(ge=1)
    heartbeat_at: datetime
    expires_at: datetime


class EditingExportStartCommandV2(_EditingAuthorityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    expected_workflow_revision: int = Field(ge=1)
    node_id: str = Field(min_length=1, max_length=160)
    expected_node_revision: int = Field(ge=1)
    manifest_revision: int = Field(ge=1)
    manifest: EditingManifestV2
    renderer_digest: str = Field(pattern=_SHA256)
    resolved_input_digest: str = Field(pattern=_SHA256)
    fingerprint: str = Field(pattern=_FINGERPRINT)
    idempotency_key: str = Field(min_length=1, max_length=320)
    request_digest: str = Field(pattern=_SHA256)
    ready_video_node_ids: tuple[str, ...] = ()
    source_asset_assertions: tuple[RevisionAssertionV2, ...] = ()
    skipped_inputs: tuple[EditingSkippedInputV2, ...] = ()
    bgm_node_id: str | None = Field(default=None, max_length=160)
    verified_reusable_export_id: str | None = Field(default=None, max_length=160)
    created_at: datetime

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> "EditingExportStartCommandV2":
        if self.manifest_revision != self.manifest.manifest_revision:
            raise ValueError("Manifest identity must match the start command.")
        asset_ids = [item.asset_id for item in self.source_asset_assertions]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("Source Asset assertions must be unique.")
        return self


class EditingExportStartResultV2(_EditingAuthorityModel):
    export: EditingExportRuntimeV2
    disposition: Literal["created", "replayed", "completed_reuse"]
    event_cursor: int = Field(ge=0)


class EditingStagingMetadataV2(_EditingAuthorityModel):
    export_id: str = Field(min_length=1, max_length=160)
    fingerprint: str = Field(pattern=_FINGERPRINT)
    manifest_revision: int = Field(ge=1)
    renderer_digest: str = Field(pattern=_SHA256)
    writer_generation: int = Field(ge=1)
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(gt=0)


class EditingExportCommitCommandV2(_EditingAuthorityModel):
    export_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    logical_commit_key: str = Field(min_length=1, max_length=320)
    payload_digest: str = Field(pattern=_SHA256)
    fingerprint: str = Field(pattern=_FINGERPRINT)
    lease: FencedLeaseTokenV2
    outcome: Literal["completed", "failed", "cancelled"]
    prepared_object: PreparedContentObjectV2 | None = None
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    asset_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    node_content_patch: dict[str, JsonValue] = Field(default_factory=dict)
    error: CanvasNodeErrorV2 | None = None
    committed_at: datetime

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> "EditingExportCommitCommandV2":
        if self.lease.resource_id != self.export_id:
            raise ValueError("Lease identity must match the Editing Export.")
        if self.outcome == "completed":
            if self.prepared_object is None or self.asset_id is None or self.version_id is None:
                raise ValueError("A completed Editing Export requires prepared Asset output.")
            if self.prepared_object.media_type != "video":
                raise ValueError("Editing Export output must be video media.")
            if self.error is not None:
                raise ValueError("A completed Editing Export cannot include an error.")
        elif self.error is None:
            raise ValueError("A failed or cancelled Editing Export requires a safe error.")
        return self


class EditingExportCommitReceiptV2(_EditingAuthorityModel):
    commit_id: str = Field(min_length=1, max_length=160)
    export_id: str = Field(min_length=1, max_length=160)
    logical_commit_key: str = Field(min_length=1, max_length=320)
    payload_digest: str = Field(pattern=_SHA256)
    outcome: Literal["completed", "failed", "cancelled"]
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    node_revision: int = Field(ge=1)
    event_cursor: int = Field(ge=0)
    committed_at: datetime
