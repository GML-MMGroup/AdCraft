"""Bounded Pi extraction and deterministic Video parameter compilation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Protocol, cast

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, ResolvedTextBindingInputV2
from app.schemas.agent_canvas_runtime import CanvasProviderModelCapabilityV2
from app.schemas.agent_canvas_video_parameters import (
    CompiledVideoParametersV2,
    VideoParameterCompilationSnapshotV2,
    VideoParameterIntentV2,
    VideoParameterSourceSnapshotV2,
)
from app.schemas.agent_operation_contexts import (
    VideoParameterCapabilityContextV2,
    VideoParameterIntentContextV2,
    VideoParameterTextSourceV2,
)
from app.services.agent_canvas_execution_parameters import (
    AgentCanvasExecutionParameterResolver,
)
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)


_CONTRACT_VERSION = "video_agent.compile_video_parameters.v1"
_PROMPT_DESCRIPTOR = "adcraft.video_agent.compile_video_parameters.v1"


@dataclass(frozen=True, slots=True)
class VideoParameterIntentGatewayResult:
    intent: VideoParameterIntentV2
    agent_run_id: str
    output_digest: str


class VideoParameterIntentGateway(Protocol):
    def extract(
        self,
        context: VideoParameterIntentContextV2,
    ) -> VideoParameterIntentGatewayResult: ...


class PiVideoParameterIntentGateway:
    """Invoke the registered bounded Video Agent structured operation."""

    def __init__(self, runtime: StructuredGenerationRuntime | None = None) -> None:
        self._runtime = runtime or StructuredGenerationRuntime()

    def extract(
        self,
        context: VideoParameterIntentContextV2,
    ) -> VideoParameterIntentGatewayResult:
        try:
            result = self._runtime.run(
                StructuredGenerationSpec(
                    stage_name="compile_video_parameters",
                    contract_name="VideoParameterIntentV2",
                    model_id="video-agent",
                    system_prompt=("Use the registered Video Agent parameter compilation prompt."),
                    input_payload=context.model_dump(mode="json"),
                    output_model=VideoParameterIntentV2,
                    trace_metadata={
                        "workflow_id": context.workflow_id,
                        "node_id": context.target_node_id,
                        "expected_target_revision": context.target_node_revision,
                    },
                    validation_profile="video_parameter_intent_v1",
                    agent_name="video_agent",
                    operation="compile_video_parameters",
                    tool_mode="structured_only",
                    agent_context=context,
                )
            )
        except StructuredGenerationRuntimeError as error:
            raise V2PersistenceError(
                "node_parameter_compilation_failed",
                "Video parameter intent extraction failed.",
                stage="parameter_compilation",
                details={"reason": error.code, "retryable": True},
            ) from error
        return VideoParameterIntentGatewayResult(
            intent=result.output,
            agent_run_id=str(result.trace_metadata.get("agent_run_id") or "agent_run_unknown"),
            output_digest=_digest(result.output.model_dump(mode="json")),
        )


class DeterministicVideoParameterIntentGateway:
    """Return an explicit no-intent result only in configured fake runtimes."""

    def extract(
        self,
        context: VideoParameterIntentContextV2,
    ) -> VideoParameterIntentGatewayResult:
        intent = VideoParameterIntentV2(status="no_explicit_controls")
        return VideoParameterIntentGatewayResult(
            intent=intent,
            agent_run_id=f"fake_video_parameters_{context.target_node_id}",
            output_digest=_digest(intent.model_dump(mode="json")),
        )


class AgentCanvasVideoParameterCompiler:
    """Compile direct textual controls and persist one immutable run snapshot."""

    def __init__(
        self,
        *,
        gateway: VideoParameterIntentGateway,
        authoring_repository: AgentCanvasWorkflowRepository,
        runtime_repository: AgentCanvasRuntimeRepository,
        resolver: AgentCanvasExecutionParameterResolver | None = None,
    ) -> None:
        self._gateway = gateway
        self._authoring = authoring_repository
        self._runtime = runtime_repository
        self._resolver = resolver or AgentCanvasExecutionParameterResolver()

    def compile(
        self,
        *,
        node: CanvasNodeV2,
        selected_model_ref: str,
        capability: CanvasProviderModelCapabilityV2,
        direct_text_inputs: tuple[ResolvedTextBindingInputV2, ...],
        execution_id: str,
        member_id: str,
        model_defaults: dict[str, object],
        now: datetime,
    ) -> CompiledVideoParametersV2:
        sources = _text_sources(node, direct_text_inputs)
        context = VideoParameterIntentContextV2(
            context_kind="video_parameter_intent",
            workflow_id=node.workflow_id,
            target_node_id=node.node_id,
            target_node_revision=node.revision,
            selected_model_ref=selected_model_ref,
            sources=sources,
            capability=_capability_context(capability, model_defaults),
        )
        gateway_result = self._gateway.extract(context)
        try:
            compiled = self._resolver.resolve_video(
                node,
                intent=gateway_result.intent,
                direct_text_inputs=direct_text_inputs,
                capability=capability,
                model_defaults=model_defaults,
            )
        except V2PersistenceError as error:
            if error.code not in {
                "node_parameter_compilation_failed",
                "node_parameter_conflict",
                "node_parameter_unsupported",
            }:
                raise
            raise V2PersistenceError(
                error.code,
                str(error),
                stage="parameter_compilation",
                details={**error.details, "retryable": True},
            ) from error
        derived_provenance = {
            field: provenance
            for field, provenance in compiled.parameter_provenance.items()
            if provenance.origin != "manual"
        }
        derived_parameters = {
            field: cast(object, compiled.authoring_parameters[field])
            for field in derived_provenance
        }
        self._authoring.replace_derived_video_parameters(
            node.workflow_id,
            node.node_id,
            expected_node_revision=node.revision,
            derived_parameters=derived_parameters,
            derived_provenance=derived_provenance,
            now=now,
        )
        snapshot = _snapshot(
            node=node,
            selected_model_ref=selected_model_ref,
            capability=capability,
            direct_text_inputs=direct_text_inputs,
            execution_id=execution_id,
            member_id=member_id,
            model_defaults=model_defaults,
            compiled=compiled,
            gateway_result=gateway_result,
            now=now,
        )
        self._runtime.put_parameter_compilation_snapshot(snapshot)
        return compiled.model_copy(
            update={"parameter_compilation_snapshot_id": snapshot.snapshot_id}
        )


def _text_sources(
    node: CanvasNodeV2,
    direct_text_inputs: tuple[ResolvedTextBindingInputV2, ...],
) -> tuple[VideoParameterTextSourceV2, ...]:
    sources: list[VideoParameterTextSourceV2] = []
    if node.generation_prompt and node.generation_prompt.strip():
        sources.append(
            VideoParameterTextSourceV2(
                source_kind="node_prompt",
                source_node_id=node.node_id,
                source_revision=node.revision,
                text=node.generation_prompt.strip(),
            )
        )
    sources.extend(
        VideoParameterTextSourceV2(
            source_kind="binding",
            source_node_id=item.source_node_id,
            source_revision=item.source_node_revision,
            binding_id=item.binding_id,
            text=item.content,
        )
        for item in direct_text_inputs
        if item.content.strip()
    )
    return tuple(sources)


def _capability_context(
    capability: CanvasProviderModelCapabilityV2,
    model_defaults: dict[str, object],
) -> VideoParameterCapabilityContextV2:
    duration = capability.duration_range_seconds
    return VideoParameterCapabilityContextV2(
        supported_parameters=tuple(sorted(capability.supported_parameters)),
        duration_seconds_min=duration[0] if duration else None,
        duration_seconds_max=duration[1] if duration else None,
        supported_resolutions=capability.supported_resolutions,
        supported_aspect_ratios=capability.supported_aspect_ratios,
        supports_native_audio=capability.supports_native_audio,
        default_parameters=cast(dict[str, object], model_defaults),
        capability_revision=capability.capability_revision,
    )


def _snapshot(
    *,
    node: CanvasNodeV2,
    selected_model_ref: str,
    capability: CanvasProviderModelCapabilityV2,
    direct_text_inputs: tuple[ResolvedTextBindingInputV2, ...],
    execution_id: str,
    member_id: str,
    model_defaults: dict[str, object],
    compiled: CompiledVideoParametersV2,
    gateway_result: VideoParameterIntentGatewayResult,
    now: datetime,
) -> VideoParameterCompilationSnapshotV2:
    sources: list[VideoParameterSourceSnapshotV2] = []
    if node.generation_prompt and node.generation_prompt.strip():
        sources.append(
            VideoParameterSourceSnapshotV2(
                source_kind="node_prompt",
                source_node_id=node.node_id,
                source_revision=node.revision,
                content_digest=_digest(node.generation_prompt.strip()),
            )
        )
    sources.extend(
        VideoParameterSourceSnapshotV2(
            source_kind="binding",
            source_node_id=item.source_node_id,
            source_revision=item.source_node_revision,
            binding_id=item.binding_id,
            content_digest=_digest(item.content),
        )
        for item in direct_text_inputs
    )
    manual = {
        field: value
        for field, value in node.parameters.items()
        if node.parameter_provenance.get(field) is None
        or node.parameter_provenance[field].origin == "manual"
    }
    payload = {
        "workflow_id": node.workflow_id,
        "execution_id": execution_id,
        "member_id": member_id,
        "node_id": node.node_id,
        "node_revision": node.revision,
        "model_ref": selected_model_ref,
        "capability_revision": capability.capability_revision,
        "source_snapshots": [item.model_dump(mode="json") for item in sources],
        "manual_parameters": manual,
        "model_defaults": model_defaults,
        "intent": gateway_result.intent.model_dump(mode="json"),
        "requested_parameters": compiled.requested_parameters,
        "effective_parameters": compiled.effective_parameters,
    }
    digest = _digest(payload)
    return VideoParameterCompilationSnapshotV2(
        snapshot_id=f"video_params_{digest[:24]}",
        snapshot_digest=digest,
        workflow_id=node.workflow_id,
        execution_id=execution_id,
        member_id=member_id,
        node_id=node.node_id,
        node_revision=node.revision,
        model_ref=selected_model_ref,
        capability_revision=capability.capability_revision,
        source_snapshots=tuple(sources),
        manual_parameters=cast(dict[str, object], manual),
        accepted_candidates=compiled.accepted_candidates,
        rejected_lower_priority_candidates=compiled.rejected_lower_priority_candidates,
        requested_parameters=compiled.requested_parameters,
        effective_parameters=compiled.effective_parameters,
        parameter_provenance=compiled.parameter_provenance,
        normalizations=compiled.normalizations,
        agent_run_id=gateway_result.agent_run_id,
        contract_version=_CONTRACT_VERSION,
        prompt_descriptor=_PROMPT_DESCRIPTOR,
        output_digest=gateway_result.output_digest,
        created_at=now,
    )


def _digest(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
