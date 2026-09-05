"""Closed, content-free metadata at the Canvas result publication boundary."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated, Any, Literal, Mapping, TYPE_CHECKING

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, StrictBool

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_errors import ActionableFailureV1
from app.schemas.agent_canvas_video_parameters import VideoParameterNormalizationV2
from app.schemas.seedance_inputs import StoryboardGridGroundingAuditV1
from app.services.agent_canvas_node_execution import (
    NodeExecutionContext,
    generated_asset_publication_metadata,
)

if TYPE_CHECKING:
    from app.services.agent_canvas_output_preparation import ResultPublicationContext


METADATA_INVALID_MESSAGE = "Generated media could not be published because its metadata is invalid."
PUBLICATION_FAILED_MESSAGE = "Generated media could not be published."


def _safe_identifier(value: str) -> str:
    if (
        value.startswith(("/", ".", "~"))
        or "://" in value
        or ".." in value
        or any(not (c.isascii() and (c.isalnum() or c in "_-.:/@")) for c in value)
    ):
        raise ValueError("Publication identifiers must be content-free.")
    return value


Identity = Annotated[str, Field(min_length=1, max_length=320), AfterValidator(_safe_identifier)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
AuditDigest = Annotated[str, Field(pattern=r"^(sha256:)?[a-f0-9]{64}$")]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Parameters(_Closed):
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    requested_duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    effective_duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    resolution: Identity | None = None
    aspect_ratio: Identity | None = None
    ratio: Identity | None = None
    size: Identity | int | None = None
    generate_audio: bool | None = None
    seed: int | None = None
    fps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    watermark: bool | None = None
    output_format: Identity | None = None
    audio_mode: Identity | None = None
    audio_codec: Identity | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)


class _PromptAudit(_Closed):
    canonical_provider_prompt_hash: AuditDigest
    actual_provider_prompt_hash: AuditDigest
    prompt_match: StrictBool
    prompt_source_contract: Identity | None = None
    prompt_contract_name: Identity | None = None
    prompt_contract_version: Identity | int | None = None
    slot_type: Identity | None = None
    node_id: Identity | None = None
    item_id: Identity | None = None
    slot_id: Identity | None = None
    legacy_prompt_fields_present: tuple[Identity, ...] = ()
    legacy_prompt_fields_used: tuple[Identity, ...] = ()
    conflicting_prompt_override_fields: tuple[Identity, ...] = ()


class _ModelIdentity(_Closed):
    model_ref: Identity
    provider_id: Identity
    provider_model_id: Identity
    capability: Literal["text", "image", "video", "audio"]
    provider_protocol: Identity
    catalog_revision: int = Field(ge=1)
    adapter_id: Identity | None = None
    transport_kind: Identity | None = None
    conformance_status: Identity | None = None
    capability_revision: Identity | None = None
    adapter_revision: Identity | None = None
    requested_parameter_fingerprint: Identity | None = None


class _WorldIdentity(_Closed):
    source_node_id: Identity
    source_node_revision: int = Field(ge=1)
    source_content_digest: Digest
    source_core_digest: Digest
    compiler_id: Identity
    compiler_digest: Digest
    context_digest: Digest


class _ReferenceAudit(_Closed):
    requested_reference_asset_ids: tuple[Identity, ...] = ()
    delivered_reference_asset_ids: tuple[Identity, ...] = ()
    serialized_reference_asset_ids: tuple[Identity, ...] = ()
    failed_reference_asset_ids: tuple[Identity, ...] = ()
    submitted_reference_asset_ids: tuple[Identity, ...] = ()
    dropped_reference_asset_ids: tuple[Identity, ...] = ()
    reference_asset_ids: tuple[Identity, ...] = ()
    input_asset_ids: tuple[Identity, ...] = ()
    requested_count: int | None = Field(default=None, ge=0)
    submitted_count: int | None = Field(default=None, ge=0)
    delivered_count: int | None = Field(default=None, ge=0)
    dropped_count: int | None = Field(default=None, ge=0)
    provider_request_field: Identity | None = None
    provider_request_reference_count: int | None = Field(default=None, ge=0)
    request_schema: Identity | None = None
    warnings: tuple[Identity, ...] = ()
    provider_input_types: tuple[Identity, ...] = ()
    omitted_payload: Literal[True] = True


class _ProviderFacts(_Parameters):
    provider: Identity | None = None
    model: Identity | None = None
    model_id: Identity | None = None
    status: Identity | None = None
    provider_status: Identity | None = None
    download_status: Identity | None = None
    download_attempted: bool | None = None
    provider_action: Identity | None = None
    query_action: Identity | None = None
    api_version: Identity | None = None
    generation_version: Identity | None = None
    request_id: Identity | None = None
    callback_id: Identity | None = None
    callback_enabled: bool | None = None
    model_duration_limit_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    provider_duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    audio_duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_content_type: Identity | None = None
    source_extension: Identity | None = None
    audio_quality: Identity | None = None
    progress: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    submitted_media_facts: _Parameters | None = None


class _GroundingAudit(StoryboardGridGroundingAuditV1):
    prompt_reference_labels: tuple[
        Annotated[str, Field(max_length=32, pattern=r"^Image [1-9][0-9]*$")], ...
    ] = ()


class _CanvasPublicationMetadataV1(_ProviderFacts):
    workflow_id: Identity
    node_id: Identity
    execution_id: Identity
    member_id: Identity | None = None
    node_run_id: Identity | None = None
    node_run_snapshot_id: Identity | None = None
    source_snapshot_digest: Digest | None = None
    input_manifest_id: Identity | None = None
    provider_task_id: Identity | None = None
    prompt_digest: Digest
    compiled_prompt_digest: Digest | None = None
    prompt_registry_ref: Identity | None = None
    prompt_registry_digest: Digest | None = None
    model_resolution: _ModelIdentity | None = None
    prompt_audit: _PromptAudit | None = None
    provider_asset: _ProviderFacts | None = None
    reference_wire_audit: _ReferenceAudit | None = None
    reference_input_delivery: _ReferenceAudit | None = None
    quality_flags: tuple[Identity, ...] = ()
    requested_parameters: _Parameters
    effective_parameters: _Parameters
    parameter_compilation_snapshot_id: Identity | None = None
    normalizations: tuple[Identity | VideoParameterNormalizationV2, ...] = ()
    source_asset_ids: tuple[Identity, ...] = ()
    source_asset_version_ids: tuple[Identity, ...] = ()
    execution_mode: Literal["manual_prompt_direct", "agent_assisted"]
    semantic_extraction: Literal["not_required", "agent"]
    world_setting_context: _WorldIdentity | None = None
    character_asset_kind: Identity | None = None
    reference_rendering_mode: Identity | None = None
    negative_boundary_digest: Digest | None = None
    occurrence_id: Identity | None = None
    character_pair_id: Identity | None = None
    character_phase: Identity | None = None
    storyboard_grid_grounding: _GroundingAudit | None = None


def publication_metadata_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_result_publication_metadata_invalid",
        METADATA_INVALID_MESSAGE,
        stage="node_result_publication",
        details={
            "actionable_failure": ActionableFailureV1(
                failure_class="deterministic",
                retry_scope="none",
                user_action="none",
                retryable=False,
            ).model_dump(mode="json")
        },
    )


def _select(model: type[BaseModel], value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Publication metadata requires a mapping.")
    return {key: value[key] for key in model.model_fields if key in value}


def _provider_facts(value: object) -> dict[str, Any]:
    selected = _select(_ProviderFacts, value)
    if selected.get("submitted_media_facts") is not None:
        selected["submitted_media_facts"] = _select(_Parameters, selected["submitted_media_facts"])
    return selected


def _prompt_audit(value: object) -> dict[str, Any]:
    selected = _select(_PromptAudit, value)
    assert isinstance(value, Mapping)
    for text_key, hash_key in (
        ("canonical_provider_prompt", "canonical_provider_prompt_hash"),
        ("actual_provider_request_prompt", "actual_provider_prompt_hash"),
    ):
        if text_key in value:
            text = value[text_key]
            if not isinstance(text, str) or not text:
                raise ValueError("Prompt integrity evidence is incomplete.")
            digest = sha256(text.encode("utf-8")).hexdigest()
            if hash_key in selected and selected[hash_key] not in (digest, f"sha256:{digest}"):
                raise ValueError("Prompt integrity evidence is inconsistent.")
            selected.setdefault(hash_key, digest)
    audit = _PromptAudit.model_validate(selected)
    if not audit.prompt_match or audit.canonical_provider_prompt_hash.removeprefix(
        "sha256:"
    ) != audit.actual_provider_prompt_hash.removeprefix("sha256:"):
        raise V2PersistenceError(
            "v2_provider_prompt_mismatch",
            "Provider prompt integrity validation failed.",
            stage="node_result_publication",
        )
    return audit.model_dump(mode="json", exclude_none=True)


def project_canvas_publication_metadata(
    context: NodeExecutionContext,
    publication: ResultPublicationContext | None,
    provider_metadata: Mapping[str, object],
) -> dict[str, Any]:
    """Project declared facts only; provider metadata cannot assign source authority."""
    try:
        frozen = generated_asset_publication_metadata(context)
        values = _provider_facts(provider_metadata)
        values.update(_select(_CanvasPublicationMetadataV1, frozen))
        values.update(
            workflow_id=context.node.workflow_id,
            node_id=context.node.node_id,
            execution_id=context.execution_id,
        )
        for key in ("occurrence_id", "character_pair_id", "character_phase"):
            if key in context.node.metadata:
                values[key] = context.node.metadata[key]
        if publication is not None:
            existing = values.get("node_run_snapshot_id")
            if existing is not None and existing != publication.source_snapshot_id:
                raise ValueError("Publication snapshot identity conflicts.")
            values.update(
                member_id=publication.member_id,
                node_run_snapshot_id=publication.source_snapshot_id,
                source_snapshot_digest=publication.source_snapshot_digest,
            )
        for key in ("requested_parameters", "effective_parameters"):
            values[key] = _select(_Parameters, values[key])
        for key, model in (
            ("model_resolution", _ModelIdentity),
            ("world_setting_context", _WorldIdentity),
        ):
            if key in values:
                values[key] = _select(model, values[key])
        if "provider_asset" in provider_metadata:
            values["provider_asset"] = _provider_facts(provider_metadata["provider_asset"])
        if "prompt_audit" in provider_metadata:
            values["prompt_audit"] = _prompt_audit(provider_metadata["prompt_audit"])
            expected_prompt_digest = values["prompt_digest"]
            if context.seedance_input_audit is not None:
                expected_prompt_digest = context.seedance_input_audit.prompt_hash
            if context.seedance_manifest is not None:
                manifest_digest = sha256(
                    context.seedance_manifest.prompt.encode("utf-8")
                ).hexdigest()
                if (
                    context.seedance_input_audit is None
                    or manifest_digest != expected_prompt_digest
                ):
                    raise ValueError("Provider manifest prompt evidence is inconsistent.")
            if (
                values["prompt_audit"]["canonical_provider_prompt_hash"].removeprefix("sha256:")
                != expected_prompt_digest
            ):
                raise ValueError("Prompt audit does not match the frozen execution.")
        for key in ("reference_wire_audit", "reference_input_delivery"):
            if key in provider_metadata:
                values[key] = _select(_ReferenceAudit, provider_metadata[key])
        if "quality_flags" in provider_metadata:
            values["quality_flags"] = provider_metadata["quality_flags"]
        result = _CanvasPublicationMetadataV1.model_validate(values).model_dump(
            mode="json", exclude_none=True
        )
        _validate_summary_bounds(result)
        return result
    except (ValidationError, ValueError, TypeError) as error:
        raise publication_metadata_error() from error


def _validate_summary_bounds(value: object) -> None:
    """Validate reused typed summaries too; never trim their identities or payloads."""
    if len(json.dumps(value, ensure_ascii=False)) > 131_072:
        raise ValueError("Publication metadata exceeds the existing envelope bound.")
    if isinstance(value, str):
        if len(value) > 8192:
            raise ValueError("Publication metadata exceeds the existing string bound.")
        _safe_identifier(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "prompt_reference_labels":
                # This one spaced wire label is validated by the closed grounding contract.
                continue
            _validate_summary_bounds(item)
    elif isinstance(value, list):
        for item in value:
            _validate_summary_bounds(item)
