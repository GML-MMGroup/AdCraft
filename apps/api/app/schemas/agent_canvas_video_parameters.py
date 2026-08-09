"""Strict provider-neutral contracts for Agent Canvas Video parameter compilation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


VideoParameterFieldV2 = Literal[
    "duration_seconds",
    "resolution",
    "aspect_ratio",
    "generate_audio",
]
VideoParameterOriginV2 = Literal[
    "manual",
    "node_prompt",
    "binding",
    "user_explicit",
    "structured_content",
    "guidance_default",
    "role_default",
    "provider_clamp",
]
VideoParameterScalarV2 = int | float | str | bool


class _VideoParameterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VideoParameterCandidateV2(_VideoParameterModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"source_kind": {"const": "binding"}},
                        "required": ["source_kind"],
                    },
                    "then": {
                        "required": [
                            "source_node_id",
                            "binding_id",
                            "source_revision",
                        ]
                    },
                    "else": {
                        "properties": {
                            "source_node_id": {"type": "null"},
                            "binding_id": {"type": "null"},
                            "source_revision": {"type": "null"},
                        }
                    },
                }
            ]
        },
    )
    field: VideoParameterFieldV2
    value: VideoParameterScalarV2
    source_kind: Literal["node_prompt", "binding"]
    source_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    binding_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_source_identity(self) -> "VideoParameterCandidateV2":
        if self.source_kind == "binding":
            if not self.source_node_id or not self.binding_id or self.source_revision is None:
                raise ValueError("Binding candidates require immutable source identity.")
        elif any(
            value is not None
            for value in (self.source_node_id, self.binding_id, self.source_revision)
        ):
            raise ValueError("Node prompt candidates cannot claim Binding identity.")
        return self


class VideoParameterIntentV2(_VideoParameterModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"status": {"const": "explicit_controls"}},
                        "required": ["status"],
                    },
                    "then": {"properties": {"candidates": {"minItems": 1}}},
                    "else": {"properties": {"candidates": {"maxItems": 0}}},
                }
            ]
        },
    )
    status: Literal["explicit_controls", "no_explicit_controls"]
    candidates: tuple[VideoParameterCandidateV2, ...] = Field(default=(), max_length=32)

    @field_validator("candidates", mode="before")
    @classmethod
    def normalize_json_candidates(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_status(self) -> "VideoParameterIntentV2":
        if self.status == "explicit_controls" and not self.candidates:
            raise ValueError("Explicit controls require at least one candidate.")
        if self.status == "no_explicit_controls" and self.candidates:
            raise ValueError("No-explicit-controls cannot include candidates.")
        return self


class CanvasParameterProvenanceV2(_VideoParameterModel):
    origin: VideoParameterOriginV2
    source_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    binding_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    requested_value: VideoParameterScalarV2
    effective_value: VideoParameterScalarV2
    normalization_code: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_origin_identity(self) -> "CanvasParameterProvenanceV2":
        if self.origin == "binding":
            if not self.source_node_id or not self.binding_id or self.source_revision is None:
                raise ValueError("Binding provenance requires immutable source identity.")
        elif any(
            value is not None
            for value in (self.source_node_id, self.binding_id, self.source_revision)
        ):
            raise ValueError("Only Binding provenance can include Binding source identity.")
        return self


class VideoParameterNormalizationV2(_VideoParameterModel):
    field: VideoParameterFieldV2
    requested_value: VideoParameterScalarV2
    effective_value: VideoParameterScalarV2
    normalization_code: Literal[
        "duration_clamped_to_minimum",
        "duration_clamped_to_maximum",
        "resolution_reduced_to_supported",
    ]


class VideoParameterSourceSnapshotV2(_VideoParameterModel):
    source_kind: Literal["node_prompt", "binding"]
    source_node_id: str
    source_revision: int = Field(ge=1)
    binding_id: str | None = None
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class VideoParameterCompilationSnapshotV2(_VideoParameterModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    model_ref: str = Field(min_length=3, max_length=320)
    capability_revision: int = Field(ge=1)
    source_snapshots: tuple[VideoParameterSourceSnapshotV2, ...] = ()
    manual_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    accepted_candidates: tuple[VideoParameterCandidateV2, ...] = ()
    rejected_lower_priority_candidates: tuple[VideoParameterCandidateV2, ...] = ()
    requested_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    effective_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    parameter_provenance: dict[str, CanvasParameterProvenanceV2] = Field(default_factory=dict)
    normalizations: tuple[VideoParameterNormalizationV2, ...] = ()
    agent_run_id: str = Field(min_length=1, max_length=160)
    contract_version: str = Field(min_length=1, max_length=80)
    prompt_descriptor: str = Field(min_length=1, max_length=320)
    output_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_secret_free(self) -> "VideoParameterCompilationSnapshotV2":
        if _contains_forbidden_transport(self.model_dump(mode="json")):
            raise ValueError("Video parameter snapshots cannot contain transport values.")
        return self


class CompiledVideoParametersV2(_VideoParameterModel):
    authoring_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    requested_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    effective_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    parameter_provenance: dict[str, CanvasParameterProvenanceV2] = Field(default_factory=dict)
    accepted_candidates: tuple[VideoParameterCandidateV2, ...] = ()
    rejected_lower_priority_candidates: tuple[VideoParameterCandidateV2, ...] = ()
    normalizations: tuple[VideoParameterNormalizationV2, ...] = ()
    parameter_compilation_snapshot_id: str | None = None

    @property
    def parameters(self) -> dict[str, JsonValue]:
        """Authoring parameters retained for compatibility with existing resolvers."""

        return self.authoring_parameters


def _contains_forbidden_transport(value: object, *, key: str | None = None) -> bool:
    if key and any(
        fragment in key.casefold()
        for fragment in ("api_key", "token", "secret", "credential", "authorization")
    ):
        return True
    if isinstance(value, str):
        normalized = value.strip().casefold()
        return normalized.startswith(("/", "file://", "data:")) or (
            normalized.startswith(("http://", "https://"))
            and ("signature=" in normalized or "x-amz-" in normalized)
        )
    if isinstance(value, dict):
        return any(
            _contains_forbidden_transport(item, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_transport(item) for item in value)
    return False
