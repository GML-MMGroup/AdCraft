"""Node-type dispatch boundary for Agent Canvas runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_runtime import (
    AgentCanvasScriptOutput,
    AgentCanvasTextOutput,
    AgentRunCompletedPayload,
    AgentRunContext,
)
from app.schemas.agent_canvas import (
    CanvasNodeV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedNodeInputManifestV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.agent_canvas_ad_media import (
    AdReferenceBundleV2,
    CompiledProviderPromptV2,
)
from app.schemas.agent_canvas_runtime import (
    EffectiveMediaParameterSnapshotV2,
    ResolvedModelExecutionV1,
)
from app.schemas.workflow_v2 import V2ProviderResult
from app.schemas.seedance_inputs import (
    SeedanceDeliveredMediaInputV1,
    SeedanceInputManifestAuditV1,
    SeedanceInputManifestV1,
)
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2
from app.services.agent_canvas_seedance_inputs import AgentCanvasSeedanceInputCompiler
from app.services.durable_pi_run import DurablePiRunService
from app.services.agent_operation_policy import AgentRunRequestFactory
from app.services.agent_run_context_registry import validate_video_agent_operation_context
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient
from app.services.v2_provider_reference_input_delivery import (
    V2DeliveredProviderReference,
    V2ReferenceInputDeliveryFailure,
    V2ProviderReferenceDeliveryError,
    V2ProviderReferenceInputDeliveryService,
)
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)


@dataclass(frozen=True, slots=True)
class GeneratedMediaPayload:
    content: bytes
    mime_type: str
    filename: str
    metadata: dict[str, object] = field(default_factory=dict)


def _deadline_cap(timeout_seconds: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)


@dataclass(frozen=True, slots=True)
class NodeExecutionContext:
    execution_id: str
    node: CanvasNodeV2
    inputs: tuple[ResolvedInputSnapshotV2 | object, ...]
    model_id: str | None = None
    provider_id: str | None = None
    model_resolution: ResolvedModelExecutionV1 | None = None
    compiled_prompt: CompiledProviderPromptV2 | None = None
    reference_bundle: AdReferenceBundleV2 | None = None
    effective_parameters: EffectiveMediaParameterSnapshotV2 | None = None
    seedance_manifest: SeedanceInputManifestV1 | None = None
    seedance_input_audit: SeedanceInputManifestAuditV1 | None = None
    delivered_references: tuple[V2DeliveredProviderReference, ...] = ()
    input_manifest: ResolvedNodeInputManifestV2 | None = None
    optional_input_omissions: tuple[dict[str, str], ...] = ()
    world_setting: WorldSettingContextEnvelopeV2 | None = None


@dataclass(frozen=True, slots=True)
class NodeExecutionOutcome:
    structured_content: dict[str, object] | None = None
    media: GeneratedMediaPayload | None = None
    provider_task_id: str | None = None
    remote_task_id: str | None = None
    provider: str | None = None
    result_descriptor: dict[str, object] | None = None
    prompt_metadata: dict[str, object] | None = None
    submission_intent_id: str | None = None


NodeExecutor = Callable[[NodeExecutionContext], NodeExecutionOutcome]


def generated_asset_publication_metadata(
    context: NodeExecutionContext,
) -> dict[str, object]:
    """Project bounded immutable execution provenance into asset metadata."""

    prompt = (
        context.compiled_prompt.prompt
        if context.compiled_prompt is not None
        else _saved_prompt(context)
    )
    metadata: dict[str, object] = {
        "node_run_id": (
            context.input_manifest.node_run_id if context.input_manifest is not None else None
        ),
        "provider": context.provider_id,
        "model_id": context.model_id,
        "model_resolution": (
            context.model_resolution.model_dump(mode="json")
            if context.model_resolution is not None
            else None
        ),
        "prompt_digest": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_manifest_id": (
            context.input_manifest.manifest_id if context.input_manifest is not None else None
        ),
        "node_run_snapshot_id": (
            context.input_manifest.run_intent_snapshot_id
            if context.input_manifest is not None
            else None
        ),
        "compiled_prompt_digest": (
            context.compiled_prompt.prompt_digest if context.compiled_prompt is not None else None
        ),
        "prompt_registry_ref": (
            context.compiled_prompt.prompt_registry_ref
            if context.compiled_prompt is not None
            else None
        ),
        "prompt_registry_digest": (
            context.compiled_prompt.prompt_registry_digest
            if context.compiled_prompt is not None
            else None
        ),
        "source_asset_ids": (
            [item.asset_id for item in context.input_manifest.media_inputs]
            if context.input_manifest is not None
            else []
        ),
        "source_asset_version_ids": (
            list(context.input_manifest.delivered_asset_version_ids)
            if context.input_manifest is not None
            else []
        ),
        "requested_parameters": (
            context.effective_parameters.requested
            if context.effective_parameters is not None
            else context.node.parameters
        ),
        "effective_parameters": (
            context.effective_parameters.effective
            if context.effective_parameters is not None
            else context.node.parameters
        ),
        "parameter_compilation_snapshot_id": (
            context.effective_parameters.parameter_compilation_snapshot_id
            if context.effective_parameters is not None
            else None
        ),
        "normalizations": (
            [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in context.effective_parameters.normalizations
            ]
            if context.effective_parameters is not None
            else []
        ),
    }
    if context.world_setting is not None:
        metadata["world_setting_context"] = {
            "source_node_id": context.world_setting.source_node_id,
            "source_node_revision": context.world_setting.source_node_revision,
            "source_content_digest": context.world_setting.source_content_digest,
            "source_core_digest": context.world_setting.source_core_digest,
            "target_audience": context.world_setting.target_audience,
            "compiler_id": context.world_setting.compiler_id,
            "compiler_digest": context.world_setting.compiler_digest,
            "context_digest": context.world_setting.context_digest,
        }
    audit = context.seedance_input_audit
    if audit is not None:
        metadata.update(
            {
                "requested_duration_seconds": audit.requested_duration_seconds,
                "effective_duration_seconds": audit.effective_duration_seconds,
                "resolution": audit.resolution,
                "aspect_ratio": audit.aspect_ratio,
                "generate_audio": audit.generate_audio,
                "normalizations": list(audit.normalizations),
            }
        )
    elif context.node.parameters:
        for key in (
            "requested_duration_seconds",
            "effective_duration_seconds",
            "duration_seconds",
            "resolution",
            "aspect_ratio",
            "width",
            "height",
        ):
            if key in context.node.parameters:
                metadata[key] = context.node.parameters[key]
    if context.node.node_type == "video":
        audio_intent = {
            key: context.node.structured_content[key]
            for key in (
                "dialogue",
                "voice_style",
                "environment_sound",
                "action_effects",
                "background_music",
            )
            if key in context.node.structured_content
        }
        if audio_intent:
            metadata["audio_intent"] = audio_intent
    if context.node.creative_role == "character":
        metadata.update(
            {
                "character_asset_kind": context.node.structured_content.get("character_asset_kind"),
                "reference_rendering_mode": context.node.structured_content.get(
                    "reference_rendering_mode"
                ),
                "negative_boundary_digest": (
                    hashlib.sha256(
                        context.compiled_prompt.negative_prompt.encode("utf-8")
                    ).hexdigest()
                    if context.compiled_prompt is not None
                    else None
                ),
            }
        )
    return {key: value for key, value in metadata.items() if value is not None}


class _MinimalProviderExecutor(Protocol):
    def execute_minimal(
        self,
        *,
        workflow_id: str,
        slot_type: str,
        media_type: str,
        provider_payload: dict[str, Any],
    ) -> V2ProviderResult: ...


class _AgentCanvasSeedanceExecutor(Protocol):
    def execute_agent_canvas_seedance_video(
        self,
        *,
        workflow_id: str,
        node_id: str,
        manifest: SeedanceInputManifestV1,
        audit: SeedanceInputManifestAuditV1,
    ) -> V2ProviderResult: ...


class ScriptNodeExecutor:
    """Execute one saved Script draft through the isolated Pi Script Writer."""

    def __init__(self, durable_runner: DurablePiRunService, *, timeout_seconds: float) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        run_context = AgentRunContext(
            operation="execute_canvas_script",
            user_input=_saved_prompt(context),
            workflow_id=context.node.workflow_id,
            world_setting=context.world_setting,
            target=None,
            input_payload={"resolved_inputs": [_json_input(item) for item in context.inputs]},
        )
        validate_video_agent_operation_context("execute_canvas_script", run_context)
        request = AgentRunRequestFactory().build(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            agent_name="video_agent",
            operation="execute_canvas_script",
            deadline_cap=_deadline_cap(self._timeout_seconds),
            model_ref=_frozen_text_model_ref(context),
            context=run_context,
            contract_name="AgentCanvasScriptOutput",
            contract_schema=AgentCanvasScriptOutput.model_json_schema(),
            audit_metadata={"tool_mode": "structured_only"},
        )
        result = self._durable_runner.run(
            request,
            identity_fields={
                "workflow_id": context.node.workflow_id,
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "node_revision": context.node.revision,
                "agent_name": "video_agent",
                "operation": "execute_canvas_script",
            },
            model_ref=context.model_resolution.model_ref,
        )
        completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
        content = completed.value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _error(
                "script_provider_output_invalid",
                "Script Writer output did not include content.",
            )
        return NodeExecutionOutcome(structured_content=dict(completed.value))


class TextNodeExecutor:
    """Execute one saved Text draft through the bounded Quick Media Agent."""

    def __init__(self, durable_runner: DurablePiRunService, *, timeout_seconds: float) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        run_context = AgentRunContext(
            operation="execute_canvas_text",
            user_input=_saved_prompt(context),
            workflow_id=context.node.workflow_id,
            world_setting=context.world_setting,
            target=None,
            input_payload={"resolved_inputs": [_json_input(item) for item in context.inputs]},
        )
        validate_video_agent_operation_context("execute_canvas_text", run_context)
        request = AgentRunRequestFactory().build(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            agent_name="video_agent",
            operation="execute_canvas_text",
            deadline_cap=_deadline_cap(self._timeout_seconds),
            model_ref=_frozen_text_model_ref(context),
            context=run_context,
            contract_name="AgentCanvasTextOutput",
            contract_schema=AgentCanvasTextOutput.model_json_schema(),
            audit_metadata={"tool_mode": "structured_only"},
        )
        result = self._durable_runner.run(
            request,
            identity_fields={
                "workflow_id": context.node.workflow_id,
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "node_revision": context.node.revision,
                "agent_name": "video_agent",
                "operation": "execute_canvas_text",
            },
            model_ref=context.model_resolution.model_ref,
        )
        completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
        content = completed.value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _error(
                "text_provider_output_invalid",
                "Quick Media Agent output did not include content.",
            )
        return NodeExecutionOutcome(structured_content=dict(completed.value))


class MediaNodeExecutor:
    """Adapt node-native media requests to the existing provider boundary."""

    def __init__(
        self,
        provider: _MinimalProviderExecutor,
        *,
        data_dir: Path,
        settings: Settings | None = None,
        reference_delivery: V2ProviderReferenceInputDeliveryService | None = None,
        seedance_inputs: AgentCanvasSeedanceInputCompiler | None = None,
        submission_intents=None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = provider
        self._data_dir = data_dir.resolve()
        self._settings = settings or get_settings()
        self._reference_delivery = reference_delivery or V2ProviderReferenceInputDeliveryService(
            self._data_dir,
            settings=self._settings,
        )
        self._seedance_inputs = seedance_inputs or AgentCanvasSeedanceInputCompiler()
        self._submission_intents = submission_intents
        self._clock = clock

    def prepare(self, context: NodeExecutionContext) -> NodeExecutionContext:
        """Resolve provider-safe media before the scheduler starts provider work."""

        if context.node.node_type not in {"image", "video", "audio"}:
            return context
        _require_character_identity_master_input(context)
        media_inputs = tuple(
            item for item in context.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)
        )
        AgentCanvasRoleReferencePolicyService().require_derivative_runtime_inputs(
            context.node,
            media_inputs,
        )
        if context.node.node_type == "video" and context.seedance_manifest is not None:
            return context
        if context.node.node_type != "video" and context.delivered_references:
            return context
        delivery = None
        if media_inputs:
            if context.model_resolution is None:
                raise _error(
                    "model_resolution_missing",
                    "Media reference delivery requires a frozen model resolution.",
                )
            delivery = self._reference_delivery.deliver_canvas_inputs(
                model_resolution=context.model_resolution,
                inputs=media_inputs,
            )
            try:
                delivery.raise_for_canvas_failures()
            except V2ProviderReferenceDeliveryError as error:
                raise _error(
                    error.code,
                    str(error),
                    details={
                        "target_node_id": context.node.node_id,
                        "failures": [
                            _delivery_failure_identity(failure, media_inputs)
                            for failure in error.failures
                        ],
                    },
                ) from error
        delivered_references = tuple(delivery.references) if delivery is not None else ()
        optional_delivery_omissions = (
            tuple(
                {
                    "binding_id": failure.binding_id or "",
                    "source_node_id": failure.node_id or failure.slot_id,
                    "reason": failure.reason,
                }
                for failure in delivery.omitted_optional_inputs
            )
            if delivery is not None
            else ()
        )
        optional_input_omissions = (
            *context.optional_input_omissions,
            *optional_delivery_omissions,
        )
        if context.node.node_type != "video":
            return replace(
                context,
                delivered_references=delivered_references,
                optional_input_omissions=optional_input_omissions,
            )
        delivered_media = tuple(
            SeedanceDeliveredMediaInputV1(
                binding_id=reference.binding_id or f"asset_{reference.asset_id}",
                asset_id=reference.asset_id,
                media_type=reference.media_type,  # type: ignore[arg-type]
                input_role=reference.input_role,  # type: ignore[arg-type]
                source_semantic_role=reference.source_semantic_role,
                required=reference.required,
                display_order=reference.display_order,
                provider_input_type=reference.provider_input_type,
                provider_input_value=reference.provider_input_value,
                checksum=reference.checksum
                or _seedance_checksum(reference.asset_id, reference.version_id),
                byte_count=reference.byte_count,
            )
            for reference in delivered_references
        )
        try:
            if context.model_resolution is None or not context.model_id:
                raise _error(
                    "model_resolution_missing",
                    "Video execution requires a frozen model resolution.",
                )
            manifest, audit = self._seedance_inputs.compile(
                context.node,
                model_id=context.model_id,
                resolved_inputs=tuple(
                    item
                    for item in context.inputs
                    if isinstance(
                        item,
                        (ResolvedTextInputSnapshotV2, ResolvedMediaInputSnapshotV2),
                    )
                ),
                delivered_media=delivered_media,
                compiled_prompt=(
                    context.compiled_prompt.prompt if context.compiled_prompt is not None else None
                ),
                effective_parameters=context.effective_parameters,
            )
        except ValueError as error:
            code = str(error)
            if code != "v2_video_prompt_empty":
                code = "provider_inputs_unsupported"
            raise _error(code, str(error)) from error
        return replace(
            context,
            seedance_manifest=manifest,
            seedance_input_audit=audit,
            delivered_references=delivered_references,
            optional_input_omissions=optional_input_omissions,
        )

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        media_type = context.node.node_type
        if media_type not in {"image", "video", "audio"}:
            raise _error("node_not_runnable", "Node type cannot use a media executor.")
        if context.model_resolution is None:
            raise _error(
                "model_resolution_missing",
                "Media execution requires a frozen model resolution.",
            )
        if media_type == "video":
            return self._execute_seedance_video(self.prepare(context))
        effective_parameters = (
            context.effective_parameters.effective
            if context.effective_parameters is not None
            else context.node.parameters
        )
        if context.node.semantic_role == "bgm":
            _require_bgm_duration(effective_parameters)
        prompt = _saved_prompt(context)
        provider_payload: dict[str, Any] = {
            "provider_prompt": prompt,
            "prompt": prompt,
            "node_id": context.node.node_id,
            "semantic_role": context.node.semantic_role,
            "model_id": context.model_resolution.provider_model_id,
            **effective_parameters,
        }
        provider_payload.update(
            {
                "model_ref": context.model_resolution.model_ref,
                "provider_id": context.model_resolution.provider_id,
                "provider_model_id": context.model_resolution.provider_model_id,
            }
        )
        prepared = self.prepare(context)
        if prepared.delivered_references:
            provider_payload["reference_assets"] = [
                reference.provider_asset() for reference in prepared.delivered_references
            ]
            provider_payload["reference_asset_ids"] = [
                reference.asset_id for reference in prepared.delivered_references
            ]
        intent = self._prepare_submission_intent(context, provider_payload)
        if intent is not None and intent.provider_idempotency_token is not None:
            provider_payload["idempotency_token"] = intent.provider_idempotency_token
        try:
            result = self._provider.execute_minimal(
                workflow_id=context.node.workflow_id,
                slot_type=context.node.semantic_role,
                media_type=media_type,
                provider_payload=provider_payload,
            )
        except Exception as error:
            self._handle_submission_error(intent, error)
            raise
        if result.status == "completed":
            content = result.asset_bytes
            if content is None and result.local_file_path:
                content = self._read_provider_file(result.local_file_path)
            if content is None:
                raise _error(
                    "provider_output_missing",
                    "Provider result did not include media content.",
                )
            mime_type, filename = _generated_media_identity(media_type, content)
            if intent is not None:
                self._submission_intents.complete(intent, now=self._clock())
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type=mime_type,
                    filename=filename,
                    metadata={
                        "provider": result.provider,
                        "model_id": result.provider_model,
                        **dict(result.metadata),
                    },
                ),
                provider=result.provider,
                remote_task_id=result.remote_task_id,
                result_descriptor=dict(result.metadata),
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        if result.status == "waiting" and result.remote_task_id:
            task_digest = hashlib.sha256(
                f"{context.execution_id}:{context.node.node_id}:{result.remote_task_id}".encode()
            ).hexdigest()[:24]
            if intent is not None:
                intent = self._submission_intents.confirm_remote_task(
                    intent,
                    provider_task_id=f"task_{task_digest}",
                    remote_task_id=result.remote_task_id,
                    now=self._clock(),
                )
            return NodeExecutionOutcome(
                provider_task_id=f"task_{task_digest}",
                remote_task_id=result.remote_task_id,
                provider=result.provider,
                result_descriptor={
                    "media_type": media_type,
                    "provider": result.provider,
                    "provider_model": result.provider_model,
                    "provider_payload": result.provider_payload_snapshot,
                    **result.metadata,
                },
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        raise _error(
            result.error_code or "provider_generation_failed",
            result.error_message or "Provider generation failed.",
        )

    def _execute_seedance_video(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        manifest = context.seedance_manifest
        audit = context.seedance_input_audit
        if manifest is None or audit is None:
            raise _error(
                "provider_inputs_unsupported", "Seedance manifest preparation is required."
            )
        execute = getattr(self._provider, "execute_agent_canvas_seedance_video", None)
        if not callable(execute):
            raise _error(
                "provider_reference_delivery_unavailable",
                "The configured provider does not support Agent Canvas Seedance manifests.",
            )
        intent = self._prepare_submission_intent(
            context,
            {
                "manifest": manifest.model_dump(mode="json"),
                "audit": audit.model_dump(mode="json"),
            },
        )
        try:
            result = execute(
                workflow_id=context.node.workflow_id,
                node_id=context.node.node_id,
                manifest=manifest,
                audit=audit,
            )
        except Exception as error:
            self._handle_submission_error(intent, error)
            raise
        audit_payload = {"seedance_input_manifest": audit.model_dump(mode="json")}
        if result.status == "completed":
            content = result.asset_bytes
            if content is None and result.local_file_path:
                content = self._read_provider_file(result.local_file_path)
            if content is None:
                raise _error(
                    "provider_output_missing", "Provider result did not include media content."
                )
            if intent is not None:
                self._submission_intents.complete(intent, now=self._clock())
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type="video/mp4",
                    filename="video.mp4",
                    metadata={
                        "provider": result.provider,
                        "model_id": result.provider_model,
                        **dict(result.metadata),
                    },
                ),
                provider=result.provider,
                remote_task_id=result.remote_task_id,
                result_descriptor=dict(result.metadata),
                prompt_metadata=audit_payload,
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        if result.status == "waiting" and result.remote_task_id:
            task_digest = hashlib.sha256(
                f"{context.execution_id}:{context.node.node_id}:{result.remote_task_id}".encode()
            ).hexdigest()[:24]
            if intent is not None:
                intent = self._submission_intents.confirm_remote_task(
                    intent,
                    provider_task_id=f"task_{task_digest}",
                    remote_task_id=result.remote_task_id,
                    now=self._clock(),
                )
            return NodeExecutionOutcome(
                provider_task_id=f"task_{task_digest}",
                remote_task_id=result.remote_task_id,
                provider=result.provider,
                result_descriptor={
                    "media_type": "video",
                    "provider": result.provider,
                    "provider_model": result.provider_model,
                    "provider_payload": result.provider_payload_snapshot,
                    **result.metadata,
                },
                prompt_metadata=audit_payload,
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        raise _error(
            result.error_code or "provider_generation_failed",
            result.error_message or "Provider generation failed.",
        )

    def _prepare_submission_intent(self, context, request_payload):
        if self._submission_intents is None or context.model_resolution is None:
            return None
        return self._submission_intents.prepare(
            workflow_id=context.node.workflow_id,
            execution_id=context.execution_id,
            node_id=context.node.node_id,
            model_resolution=context.model_resolution,
            request_payload=request_payload,
            now=self._clock(),
        )

    def _handle_submission_error(self, intent, error: Exception) -> None:
        if intent is None or self._submission_intents is None:
            return
        updated = self._submission_intents.mark_outcome_unknown(intent, now=self._clock())
        if updated.state == "outcome_unknown":
            raise _error(
                "provider_submission_outcome_unknown",
                "Provider submission outcome cannot be recovered automatically.",
            ) from error

    def _read_provider_file(self, value: str) -> bytes:
        candidate = Path(value)
        path = candidate if candidate.is_absolute() else self._data_dir / candidate
        resolved = path.resolve()
        if not resolved.is_relative_to(self._data_dir) or not resolved.is_file():
            raise _error(
                "provider_output_invalid",
                "Provider output path is outside managed storage.",
            )
        return resolved.read_bytes()


def _require_bgm_duration(parameters: dict[str, object]) -> None:
    duration = parameters.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise _error(
            "model_parameter_unsupported",
            "BGM execution requires a positive integer duration_seconds.",
        )


def _generated_media_identity(media_type: str, content: bytes) -> tuple[str, str]:
    if media_type == "image" and content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "image.jpg"
    return {
        "image": ("image/png", "image.png"),
        "video": ("video/mp4", "video.mp4"),
        "audio": ("audio/mpeg", "audio.mp3"),
    }[media_type]


class NodeExecutionDispatcher:
    """Dispatch only runnable node types without prompt rewriting."""

    def __init__(
        self,
        *,
        text_executor: NodeExecutor | None = None,
        script_executor: NodeExecutor | None = None,
        image_executor: NodeExecutor | None = None,
        video_executor: NodeExecutor | None = None,
        audio_executor: NodeExecutor | None = None,
    ) -> None:
        self._executors = {
            "text": text_executor,
            "script": script_executor,
            "image": image_executor,
            "video": video_executor,
            "audio": audio_executor,
        }

    def execute(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        if context.node.node_type not in self._executors:
            raise _error("node_not_runnable", "Node type cannot be run.")
        executor = self._executors[context.node.node_type]
        if executor is None:
            raise _error(
                "node_executor_unavailable",
                "The configured node executor is unavailable.",
            )
        return executor(context)

    def prepare(self, context: NodeExecutionContext) -> NodeExecutionContext:
        executor = self._executors.get(context.node.node_type)
        prepare = getattr(executor, "prepare", None)
        return prepare(context) if callable(prepare) else context


def build_default_node_dispatcher(
    settings: Settings,
    *,
    provider_executor: _MinimalProviderExecutor | None = None,
    fake_media_bytes_override: Callable[[str], bytes | None] | None = None,
    submission_intents=None,
) -> NodeExecutionDispatcher:
    """Build deterministic fakes or configured node-native provider adapters."""

    if settings.agent_runtime_mode == "fake" or settings.media_mode == "mock":

        def fake_script(context: NodeExecutionContext) -> NodeExecutionOutcome:
            return NodeExecutionOutcome(
                structured_content={
                    "content": context.node.generation_prompt
                    or context.node.summary_prompt
                    or context.node.title
                }
            )

        def fake_text(context: NodeExecutionContext) -> NodeExecutionOutcome:
            return NodeExecutionOutcome(
                structured_content={
                    "content": context.node.generation_prompt
                    or context.node.summary_prompt
                    or context.node.title
                }
            )

        def fake_media(context: NodeExecutionContext) -> NodeExecutionOutcome:
            prompt = (
                context.compiled_prompt.prompt
                if context.compiled_prompt is not None
                else context.node.generation_prompt
            )
            now = datetime.now(timezone.utc)
            intent = (
                submission_intents.prepare(
                    workflow_id=context.node.workflow_id,
                    execution_id=context.execution_id,
                    node_id=context.node.node_id,
                    model_resolution=context.model_resolution,
                    request_payload={
                        "node_type": context.node.node_type,
                        "prompt": prompt,
                    },
                    now=now,
                )
                if submission_intents is not None and context.model_resolution is not None
                else None
            )
            seed = hashlib.sha256(
                (f"{context.node.node_type}:{prompt}:{context.model_id}").encode()
            ).digest()
            mime_type, filename, signature = {
                "image": ("image/png", "image.png", b"\x89PNG\r\n\x1a\n"),
                "video": ("video/mp4", "video.mp4", b"\x00\x00\x00\x18ftypmp42"),
                "audio": ("audio/mpeg", "audio.mp3", b"ID3\x04\x00\x00"),
            }[context.node.node_type]
            overridden_content = (
                fake_media_bytes_override(context.node.node_type)
                if fake_media_bytes_override is not None
                else None
            )
            content = overridden_content or signature + b"ADCRAFT_FAKE_MEDIA\n" + seed
            outcome = NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type=mime_type,
                    filename=filename,
                ),
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
            if intent is not None:
                submission_intents.complete(intent, now=now)
            return outcome

        fake_video = MediaNodeExecutor(
            provider_executor or _default_provider_executor(settings),
            data_dir=settings.media_data_dir,
            settings=settings,
            submission_intents=submission_intents,
        )

        return NodeExecutionDispatcher(
            text_executor=fake_text,
            script_executor=fake_script,
            image_executor=fake_media,
            video_executor=fake_video,
            audio_executor=fake_media,
        )

    media = MediaNodeExecutor(
        provider_executor or _default_provider_executor(settings),
        data_dir=settings.media_data_dir,
        settings=settings,
        submission_intents=submission_intents,
    )

    def unavailable(_: NodeExecutionContext) -> NodeExecutionOutcome:
        raise _error(
            "node_executor_unavailable",
            "Agent Canvas Script Writer runtime is not configured.",
        )

    return NodeExecutionDispatcher(
        text_executor=(
            TextNodeExecutor(
                DurablePiRunService(
                    settings=settings,
                    client=PiAgentRuntimeClient(
                        base_url=settings.agent_runtime_base_url,
                        internal_token=settings.agent_runtime_internal_token,
                        protocol_version=settings.agent_runtime_protocol_version,
                        connect_timeout_seconds=settings.agent_runtime_connect_timeout_seconds,
                        read_timeout_seconds=settings.agent_runtime_read_timeout_seconds,
                        run_timeout_seconds=settings.agent_runtime_run_timeout_seconds,
                        max_event_bytes=settings.agent_runtime_max_event_bytes,
                        max_stream_bytes=settings.agent_runtime_max_stream_bytes,
                    ),
                ),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        script_executor=(
            ScriptNodeExecutor(
                DurablePiRunService(
                    settings=settings,
                    client=PiAgentRuntimeClient(
                        base_url=settings.agent_runtime_base_url,
                        internal_token=settings.agent_runtime_internal_token,
                        protocol_version=settings.agent_runtime_protocol_version,
                        connect_timeout_seconds=settings.agent_runtime_connect_timeout_seconds,
                        read_timeout_seconds=settings.agent_runtime_read_timeout_seconds,
                        run_timeout_seconds=settings.agent_runtime_run_timeout_seconds,
                        max_event_bytes=settings.agent_runtime_max_event_bytes,
                        max_stream_bytes=settings.agent_runtime_max_stream_bytes,
                    ),
                ),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        image_executor=media,
        video_executor=media,
        audio_executor=media,
    )


def _default_provider_executor(settings: Settings) -> _MinimalProviderExecutor:
    from app.services.v2_provider_executor import V2ProviderExecutor

    return V2ProviderExecutor(settings=settings, data_dir=settings.media_data_dir)


def _frozen_text_model_ref(context: NodeExecutionContext) -> str:
    resolution = context.model_resolution
    if resolution is None:
        raise _error(
            "model_resolution_missing",
            "Text and Script Nodes require a frozen model resolution.",
        )
    if resolution.capability != "text":
        raise _error(
            "agent_model_incompatible",
            "Text and Script Nodes require a compatible text model.",
        )
    return resolution.model_ref


def _saved_prompt(context: NodeExecutionContext) -> str:
    prompt = (
        context.compiled_prompt.prompt
        if context.compiled_prompt is not None
        else context.node.generation_prompt
    )
    parts = [str(prompt or context.node.summary_prompt or context.node.title).strip()]
    text_inputs = sorted(
        (
            item
            for item in context.inputs
            if isinstance(item, ResolvedTextInputSnapshotV2) and item.content.strip()
        ),
        key=lambda item: (item.display_order, item.binding_id or ""),
    )
    if text_inputs:
        parts.append(
            "Bound text context:\n"
            + "\n".join(
                f"{index}. {item.content.strip()}"
                for index, item in enumerate(text_inputs, start=1)
            )
        )
    media_inputs = sorted(
        (item for item in context.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)),
        key=lambda item: (item.display_order, item.binding_id or ""),
    )
    if media_inputs:
        parts.append(
            "Bound media references:\n"
            + "\n".join(
                f"{index}. {item.media_type} {item.asset_id} ({item.input_role})"
                for index, item in enumerate(media_inputs, start=1)
            )
        )
    return "\n\n".join(parts)


def _json_input(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_node_execution",
        details=details,
    )


def _delivery_failure_identity(
    failure: V2ReferenceInputDeliveryFailure,
    inputs: tuple[ResolvedMediaInputSnapshotV2, ...],
) -> dict[str, object]:
    source = next(
        (item for item in inputs if item.asset_id == failure.asset_id),
        None,
    )
    return {
        "binding_id": failure.binding_id or (source.binding_id if source is not None else None),
        "source_node_id": (
            failure.node_id or (source.source_node_id if source is not None else None)
        ),
        "asset_id": failure.asset_id,
        "required": source.required if source is not None else True,
        "reason": failure.reason,
    }


def _require_character_identity_master_input(context: NodeExecutionContext) -> None:
    if not (
        context.node.node_type == "image"
        and context.node.creative_role == "character"
        and context.node.structured_content.get("character_asset_kind") == "turnaround"
    ):
        return
    candidates = tuple(
        item
        for item in context.inputs
        if isinstance(item, ResolvedMediaInputSnapshotV2)
        and item.source_kind == "node_output"
        and item.source_semantic_role == "character"
        and item.media_type == "image"
        and item.input_role == "image_reference"
        and item.required
        and item.binding_metadata.get("reference_purpose") == "identity_master"
        and item.binding_metadata.get("semantic_reference_role") == "subject_reference"
    )
    if len(candidates) != 1:
        raise _error(
            "character_identity_master_binding_invalid",
            "Character Turnaround requires exactly one Ready Character Main image Binding.",
            details={"target_node_id": context.node.node_id},
        )


def _seedance_checksum(asset_id: str, version_id: str | None) -> str:
    return hashlib.sha256(f"{asset_id}:{version_id or ''}".encode()).hexdigest()
