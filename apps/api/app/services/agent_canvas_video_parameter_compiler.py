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
    VideoParameterCandidateV2,
    VideoParameterCompilationSnapshotV2,
    VideoParameterIntentV3,
    VideoParameterSourceSnapshotV2,
)
from app.schemas.agent_operation_contexts import (
    VideoParameterCapabilityContextV2,
    VideoParameterIntentContextV3,
    VideoParameterTextSourceV3,
)
from app.services.agent_canvas_execution_parameters import (
    AgentCanvasExecutionParameterResolver,
)
from app.services.agent_canvas_parameter_policy import NON_PROVIDER_NODE_PARAMETER_KEYS
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistry
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)


_CONTRACT_VERSION = "video_agent.compile_video_parameters.v3"
_PROMPT_DESCRIPTOR = "adcraft.video_agent.compile_video_parameters.v3"


@dataclass(frozen=True, slots=True)
class VideoParameterIntentGatewayResult:
    intent: VideoParameterIntentV3
    agent_run_id: str
    output_digest: str


class VideoParameterIntentGateway(Protocol):
    def extract(
        self,
        context: VideoParameterIntentContextV3,
    ) -> VideoParameterIntentGatewayResult: ...


class PiVideoParameterIntentGateway:
    """Invoke the registered bounded Video Agent structured operation."""

    def __init__(self, runtime: StructuredGenerationRuntime | None = None) -> None:
        self._runtime = runtime or StructuredGenerationRuntime()

    def extract(
        self,
        context: VideoParameterIntentContextV3,
    ) -> VideoParameterIntentGatewayResult:
        try:
            result = self._runtime.run(
                StructuredGenerationSpec(
                    stage_name="compile_video_parameters",
                    contract_name="VideoParameterIntentV3",
                    model_id="video-agent",
                    system_prompt=("Use the registered Video Agent parameter compilation prompt."),
                    input_payload=context.model_dump(mode="json"),
                    output_model=VideoParameterIntentV3,
                    trace_metadata={
                        "unresolved_fields": list(context.unresolved_fields),
                    },
                    validation_profile="video_parameter_intent_v3",
                    validation_context={
                        "unresolved_fields": list(context.unresolved_fields),
                        "source_refs": [source.source_ref for source in context.sources],
                    },
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
        context: VideoParameterIntentContextV3,
    ) -> VideoParameterIntentGatewayResult:
        intent = VideoParameterIntentV3(status="no_explicit_controls")
        return VideoParameterIntentGatewayResult(
            intent=intent,
            agent_run_id="fake_video_parameters",
            output_digest=_digest(intent.model_dump(mode="json")),
        )


@dataclass(frozen=True, slots=True)
class VideoParameterSemanticSourceV3:
    source_ref: str
    source_kind: str
    source_node_id: str
    source_revision: int
    binding_id: str | None
    text: str


@dataclass(frozen=True, slots=True)
class VideoParameterCompilationPlanV3:
    unresolved_fields: tuple[str, ...]
    sources: tuple[VideoParameterSemanticSourceV3, ...]
    trusted_parameters: dict[str, object]

    @property
    def semantic_extraction_required(self) -> bool:
        return bool(self.unresolved_fields and self.sources)


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
        plan = _compilation_plan(node, direct_text_inputs, capability)
        gateway_result: VideoParameterIntentGatewayResult | None = None
        candidates: tuple[VideoParameterCandidateV2, ...] = ()
        if plan.semantic_extraction_required:
            context = VideoParameterIntentContextV3(
                context_kind="video_parameter_intent_v3",
                unresolved_fields=cast(tuple, plan.unresolved_fields),
                sources=tuple(
                    VideoParameterTextSourceV3(source_ref=item.source_ref, text=item.text)
                    for item in plan.sources
                ),
                capability=_capability_context(capability, model_defaults),
            )
            gateway_result = self._gateway.extract(context)
            candidates = _map_intent(gateway_result.intent, plan)
        try:
            compiled = self._resolver.resolve_video(
                node,
                candidates=candidates,
                trusted_parameters=plan.trusted_parameters,
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
        if derived_parameters:
            node = self._authoring.replace_derived_video_parameters(
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


def _compilation_plan(
    node: CanvasNodeV2,
    direct_text_inputs: tuple[ResolvedTextBindingInputV2, ...],
    capability: CanvasProviderModelCapabilityV2,
) -> VideoParameterCompilationPlanV3:
    trusted_parameters = {
        field: cast(object, value)
        for field, value in node.parameters.items()
        if field not in NON_PROVIDER_NODE_PARAMETER_KEYS
        and field in capability.supported_parameters
        and _is_trusted_prompt_parameter(node, field, value)
    }
    resolved_fields = {
        field
        for field, value in node.parameters.items()
        if field not in NON_PROVIDER_NODE_PARAMETER_KEYS
        and field in capability.supported_parameters
        and _is_authoritative_parameter(node, field, value)
    }
    unresolved = tuple(sorted(set(capability.supported_parameters) - resolved_fields))
    sources: list[VideoParameterSemanticSourceV3] = []
    prompt = (node.generation_prompt or "").strip()
    if prompt and _target_prompt_is_semantic_source(node):
        sources.append(
            VideoParameterSemanticSourceV3(
                source_ref="source_1",
                source_kind="node_prompt",
                source_node_id=node.node_id,
                source_revision=node.revision,
                binding_id=None,
                text=prompt,
            )
        )
    for item in direct_text_inputs:
        if not item.content.strip():
            continue
        sources.append(
            VideoParameterSemanticSourceV3(
                source_ref=f"source_{len(sources) + 1}",
                source_kind="binding",
                source_node_id=item.source_node_id,
                source_revision=item.source_node_revision,
                binding_id=item.binding_id,
                text=item.content,
            )
        )
    return VideoParameterCompilationPlanV3(
        unresolved_fields=unresolved,
        sources=tuple(sources),
        trusted_parameters=trusted_parameters,
    )


def _is_authoritative_parameter(node: CanvasNodeV2, field: str, value: object) -> bool:
    provenance = node.parameter_provenance.get(field)
    if provenance is None or provenance.origin == "manual":
        return True
    return _is_trusted_prompt_parameter(node, field, value)


def _is_trusted_prompt_parameter(node: CanvasNodeV2, field: str, value: object) -> bool:
    provenance = node.parameter_provenance.get(field)
    if provenance is None or provenance.origin == "manual":
        return False
    return _prompt_preparation_is_current(node) and any(
        origin.name == field and origin.value == value
        for origin in node.prompt_preparation.parameter_origins
    )


def _prompt_preparation_is_current(node: CanvasNodeV2) -> bool:
    preparation = node.prompt_preparation
    if preparation.status != "ready" or preparation.role_variant is None:
        return False
    try:
        recipe = RolePromptRecipeRegistry().resolve(preparation.role_variant)
    except V2PersistenceError:
        return False
    prompt = (node.generation_prompt or "").strip()
    return (
        preparation.context_snapshot_id is not None
        and node.metadata.get("prompt_context_digest") == preparation.context_snapshot_id
        and preparation.recipe_id == recipe.recipe_id
        and preparation.recipe_version == recipe.recipe_version
        and preparation.recipe_digest == recipe.recipe_digest
        and preparation.prompt_digest == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    )


def _target_prompt_is_semantic_source(node: CanvasNodeV2) -> bool:
    if node.prompt_preparation.role_variant is None:
        return True
    return not _prompt_preparation_is_current(node)


def _map_intent(
    intent: VideoParameterIntentV3,
    plan: VideoParameterCompilationPlanV3,
) -> tuple[VideoParameterCandidateV2, ...]:
    source_map = {item.source_ref: item for item in plan.sources}
    candidates: list[VideoParameterCandidateV2] = []
    for candidate in intent.candidates:
        if candidate.field not in plan.unresolved_fields:
            raise _compilation_error(candidate.field, "field_already_resolved")
        source = source_map.get(candidate.source_ref)
        if source is None:
            raise _compilation_error(candidate.field, "source_ref_not_allowed")
        candidates.append(
            VideoParameterCandidateV2(
                field=candidate.field,
                value=candidate.value,
                source_kind=cast(object, source.source_kind),
                source_node_id=(source.source_node_id if source.source_kind == "binding" else None),
                binding_id=source.binding_id,
                source_revision=(
                    source.source_revision if source.source_kind == "binding" else None
                ),
            )
        )
    return tuple(candidates)


def _compilation_error(field: str, reason: str) -> V2PersistenceError:
    return V2PersistenceError(
        "node_parameter_compilation_failed",
        "Video parameter semantic result is outside the frozen compilation plan.",
        stage="parameter_compilation",
        details={"field": field, "reason": reason, "retryable": True},
    )


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
    gateway_result: VideoParameterIntentGatewayResult | None,
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
        "intent": (
            gateway_result.intent.model_dump(mode="json")
            if gateway_result is not None
            else "not_required"
        ),
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
        semantic_extraction="agent" if gateway_result is not None else "not_required",
        agent_run_id=gateway_result.agent_run_id if gateway_result is not None else None,
        contract_version=_CONTRACT_VERSION,
        prompt_descriptor=_PROMPT_DESCRIPTOR,
        output_digest=gateway_result.output_digest if gateway_result is not None else None,
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
