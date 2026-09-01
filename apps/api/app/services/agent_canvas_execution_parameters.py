"""Normalize provider-neutral execution parameters for frozen Canvas attempts."""

from __future__ import annotations

from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas import ResolvedTextBindingInputV2
from app.schemas.agent_canvas_ad_media import BgmContentV2
from app.schemas.agent_canvas_runtime import CanvasProviderModelCapabilityV2
from app.schemas.agent_canvas_runtime import NodeRunBindingSnapshotV2
from app.schemas.agent_canvas_video_parameters import (
    CanvasParameterProvenanceV2,
    CompiledVideoParametersV2,
    VideoParameterCandidateV2,
    VideoParameterNormalizationV2,
)
from app.services.agent_canvas_ad_media import AdMediaRoleRegistry
from app.services.agent_canvas_parameter_policy import NON_PROVIDER_NODE_PARAMETER_KEYS


@dataclass(frozen=True, slots=True)
class ResolvedExecutionParameters:
    """Provider-neutral parameters derived once for an immutable execution."""

    parameters: dict[str, object]
    normalizations: tuple[str, ...] = ()


class AgentCanvasExecutionParameterResolver:
    """Derive BGM execution controls without mutating canonical authoring state."""

    def __init__(self, registry: AdMediaRoleRegistry | None = None) -> None:
        self._registry = registry or AdMediaRoleRegistry()

    def resolve(self, node: CanvasNodeV2) -> ResolvedExecutionParameters:
        parameters = dict(node.parameters)
        if node.node_type != "audio" or node.semantic_role != "bgm":
            return ResolvedExecutionParameters(parameters=parameters)

        content = self._registry.validate_structured_content(
            node.semantic_role,
            node.structured_content,
        )
        if not isinstance(content, BgmContentV2):
            raise _error("invalid_role_content", "BGM structured content is invalid.")

        if "duration_seconds" in parameters:
            parameters["duration_seconds"] = _positive_integer_duration(
                parameters["duration_seconds"]
            )
            return ResolvedExecutionParameters(parameters=parameters)

        parameters["duration_seconds"] = _positive_integer_duration(
            node.structured_content.get("duration_seconds", content.duration_seconds)
        )
        return ResolvedExecutionParameters(
            parameters=parameters,
            normalizations=("bgm_duration_derived_from_structured_content",),
        )

    def freeze_node(self, node: CanvasNodeV2) -> tuple[CanvasNodeV2, tuple[str, ...]]:
        """Return a copied node suitable for one immutable run attempt."""

        resolved = self.resolve(node)
        return node.model_copy(update={"parameters": resolved.parameters}), resolved.normalizations

    def resolve_video(
        self,
        node: CanvasNodeV2,
        *,
        candidates: tuple[VideoParameterCandidateV2, ...],
        trusted_parameters: dict[str, object] | None = None,
        direct_text_inputs: tuple[ResolvedTextBindingInputV2, ...],
        capability: CanvasProviderModelCapabilityV2,
        model_defaults: dict[str, object],
    ) -> CompiledVideoParametersV2:
        """Resolve validated Pi candidates through deterministic platform policy."""

        if node.node_type != "video":
            raise _error(
                "node_parameter_compilation_failed",
                "Video parameter compilation requires a Video Node.",
            )
        allowed_bindings = {
            (
                item.binding_id,
                item.source_node_id,
                item.source_node_revision,
            )
            for item in direct_text_inputs
        }
        candidates = tuple(
            _validated_candidate(candidate, capability, allowed_bindings)
            for candidate in candidates
        )
        manual_values, manual_provenance = _manual_parameters(node)
        authoring: dict[str, object] = dict(manual_values)
        requested: dict[str, object] = {}
        provenance: dict[str, CanvasParameterProvenanceV2] = dict(manual_provenance)
        for field, raw_value in (trusted_parameters or {}).items():
            if field in manual_values:
                continue
            value = _validated_platform_value(field, raw_value)
            item = node.parameter_provenance.get(field)
            if item is None:
                raise _error(
                    "node_parameter_compilation_failed",
                    "Trusted Video parameter authority requires durable provenance.",
                    details={"field": field, "reason": "trusted_provenance_missing"},
                )
            authoring[field] = value
            requested[field] = value
            provenance[field] = item.model_copy(
                update={"requested_value": value, "effective_value": value}
            )
        accepted: list[VideoParameterCandidateV2] = []
        rejected: list[VideoParameterCandidateV2] = []

        fields = (
            set(model_defaults)
            | {candidate.field for candidate in candidates}
            | set(manual_values)
            | set(trusted_parameters or {})
        )
        for field in sorted(fields):
            if field in manual_values:
                requested[field] = manual_values[field]
                rejected.extend(candidate for candidate in candidates if candidate.field == field)
                continue
            if field in (trusted_parameters or {}):
                rejected.extend(candidate for candidate in candidates if candidate.field == field)
                continue
            field_candidates = tuple(
                candidate for candidate in candidates if candidate.field == field
            )
            target_candidates = tuple(
                candidate
                for candidate in field_candidates
                if candidate.source_kind == "node_prompt"
            )
            binding_candidates = tuple(
                candidate for candidate in field_candidates if candidate.source_kind == "binding"
            )
            active = target_candidates or binding_candidates
            if active:
                winner = _one_compatible_value(field, active)
                accepted.append(winner)
                rejected.extend(
                    candidate for candidate in field_candidates if candidate is not winner
                )
                authoring[field] = winner.value
                requested[field] = winner.value
                provenance[field] = CanvasParameterProvenanceV2(
                    origin=winner.source_kind,
                    source_node_id=winner.source_node_id,
                    binding_id=winner.binding_id,
                    source_revision=winner.source_revision,
                    requested_value=winner.value,
                    effective_value=winner.value,
                )
                continue
            if field in model_defaults:
                value = _validated_platform_value(field, model_defaults[field])
                authoring[field] = value
                requested[field] = value
                provenance[field] = CanvasParameterProvenanceV2(
                    origin="role_default",
                    requested_value=value,
                    effective_value=value,
                )

        effective, normalizations = _normalize_video_parameters(
            requested,
            capability=capability,
        )
        for field, item in tuple(provenance.items()):
            normalization = next(
                (record for record in normalizations if record.field == field),
                None,
            )
            provenance[field] = item.model_copy(
                update={
                    "effective_value": effective[field],
                    "normalization_code": (
                        normalization.normalization_code if normalization is not None else None
                    ),
                }
            )
        return CompiledVideoParametersV2(
            authoring_parameters=authoring,
            requested_parameters=requested,
            effective_parameters=effective,
            parameter_provenance=provenance,
            accepted_candidates=tuple(accepted),
            rejected_lower_priority_candidates=tuple(rejected),
            normalizations=normalizations,
        )

    def resolve_direct_video(
        self,
        node: CanvasNodeV2,
        *,
        binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...],
        capability: CanvasProviderModelCapabilityV2,
        model_defaults: dict[str, object],
    ) -> CompiledVideoParametersV2:
        """Resolve a manual Video without interpreting any natural-language input."""

        if node.node_type != "video":
            raise _error(
                "manual_media_execution_mode_invalid",
                "Direct manual media parameters require a Video Node.",
            )
        try:
            manual_values, manual_provenance = _manual_parameters(node)
            binding_candidates = _direct_typed_binding_candidates(
                binding_snapshots,
                capability=capability,
            )
            binding_values = _direct_binding_values(binding_candidates)
            requested: dict[str, object] = dict(manual_values)
            provenance: dict[str, CanvasParameterProvenanceV2] = dict(manual_provenance)
            accepted: list[VideoParameterCandidateV2] = []
            for field, candidate in binding_values.items():
                if field in manual_values:
                    continue
                requested[field] = candidate.value
                provenance[field] = CanvasParameterProvenanceV2(
                    origin="binding",
                    source_node_id=candidate.source_node_id,
                    binding_id=candidate.binding_id,
                    source_revision=candidate.source_revision,
                    requested_value=candidate.value,
                    effective_value=candidate.value,
                )
                accepted.append(candidate)
            required_fields = capability.supported_parameters & {
                "duration_seconds",
                "resolution",
                "aspect_ratio",
                "generate_audio",
            }
            for field in sorted(required_fields - requested.keys()):
                if field not in model_defaults:
                    raise _error(
                        "manual_media_parameters_unavailable",
                        "The selected media model does not declare a required default.",
                        details={"field": field, "model_id": capability.model_id},
                    )
                value = _validated_platform_value(field, model_defaults[field])
                requested[field] = value
                provenance[field] = CanvasParameterProvenanceV2(
                    origin="model_default",
                    requested_value=value,
                    effective_value=value,
                )
            effective, normalizations = _normalize_video_parameters(
                requested,
                capability=capability,
            )
            for field, item in tuple(provenance.items()):
                normalization = next(
                    (record for record in normalizations if record.field == field),
                    None,
                )
                provenance[field] = item.model_copy(
                    update={
                        "effective_value": effective[field],
                        "normalization_code": (
                            normalization.normalization_code if normalization is not None else None
                        ),
                    }
                )
        except V2PersistenceError as error:
            if error.code in {
                "manual_media_parameters_unavailable",
                "manual_media_parameter_unsupported",
                "manual_media_execution_mode_invalid",
            }:
                raise
            if error.code in {
                "node_parameter_unsupported",
                "video_native_audio_unsupported",
                "node_parameter_compilation_failed",
            }:
                raise _error(
                    "manual_media_parameter_unsupported",
                    str(error),
                    details=error.details,
                ) from error
            raise
        return CompiledVideoParametersV2(
            authoring_parameters=dict(requested),
            requested_parameters=requested,
            effective_parameters=effective,
            parameter_provenance=provenance,
            accepted_candidates=tuple(accepted),
            parameter_source=_direct_parameter_source(provenance),
            normalizations=normalizations,
        )


def _positive_integer_duration(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(
            "model_parameter_unsupported",
            "BGM duration_seconds must be a positive integer.",
        )
    duration = int(value)
    if duration <= 0 or duration != value:
        raise _error(
            "model_parameter_unsupported",
            "BGM duration_seconds must be a positive integer.",
        )
    return duration


def _manual_parameters(
    node: CanvasNodeV2,
) -> tuple[dict[str, object], dict[str, CanvasParameterProvenanceV2]]:
    values: dict[str, object] = {}
    provenance: dict[str, CanvasParameterProvenanceV2] = {}
    for field, value in node.parameters.items():
        if field in NON_PROVIDER_NODE_PARAMETER_KEYS:
            continue
        item = node.parameter_provenance.get(field)
        if item is not None and item.origin != "manual":
            continue
        scalar = _validated_platform_value(field, value)
        values[field] = scalar
        provenance[field] = item or CanvasParameterProvenanceV2(
            origin="manual",
            requested_value=scalar,
            effective_value=scalar,
        )
    return values, provenance


def _direct_typed_binding_candidates(
    binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...],
    *,
    capability: CanvasProviderModelCapabilityV2,
) -> tuple[VideoParameterCandidateV2, ...]:
    candidates: list[VideoParameterCandidateV2] = []
    for binding in binding_snapshots:
        raw_parameters = binding.binding_metadata.get("typed_parameters")
        if raw_parameters is None:
            continue
        if (
            not isinstance(raw_parameters, dict)
            or binding.source_kind != "node_output"
            or binding.source_node_revision is None
        ):
            raise _error(
                "manual_media_parameter_unsupported",
                "Typed Video binding metadata has invalid source identity.",
                details={"binding_id": binding.binding_id},
            )
        for field, value in raw_parameters.items():
            if field not in capability.supported_parameters:
                raise _error(
                    "manual_media_parameter_unsupported",
                    "Typed binding parameter is not supported by the selected model.",
                    details={"binding_id": binding.binding_id, "field": field},
                )
            scalar = _validated_platform_value(field, value)
            candidates.append(
                VideoParameterCandidateV2(
                    field=field,
                    value=scalar,
                    source_kind="binding",
                    source_node_id=binding.source_id,
                    binding_id=binding.binding_id,
                    source_revision=binding.source_node_revision,
                )
            )
    return tuple(candidates)


def _direct_binding_values(
    candidates: tuple[VideoParameterCandidateV2, ...],
) -> dict[str, VideoParameterCandidateV2]:
    values: dict[str, VideoParameterCandidateV2] = {}
    for candidate in candidates:
        previous = values.get(candidate.field)
        if previous is not None and previous.value != candidate.value:
            raise _error(
                "manual_media_parameter_unsupported",
                "Typed binding parameters contain conflicting values.",
                details={"field": candidate.field},
            )
        values.setdefault(candidate.field, candidate)
    return values


def _direct_parameter_source(
    provenance: dict[str, CanvasParameterProvenanceV2],
) -> str:
    origins = {item.origin for item in provenance.values()}
    categories = {
        "manual" if origin == "manual" else "typed_binding" if origin == "binding" else "model_default"
        for origin in origins
    }
    return next(iter(categories)) if len(categories) == 1 else "mixed"


def _validated_candidate(
    candidate: VideoParameterCandidateV2,
    capability: CanvasProviderModelCapabilityV2,
    allowed_bindings: set[tuple[str, str, int]],
) -> VideoParameterCandidateV2:
    if candidate.field not in capability.supported_parameters:
        raise _error(
            "node_parameter_compilation_failed",
            "Agent returned a parameter absent from the selected model schema.",
            details={"field": candidate.field, "reason": "field_not_declared"},
        )
    if (
        candidate.source_kind == "binding"
        and (
            candidate.binding_id or "",
            candidate.source_node_id or "",
            candidate.source_revision or 0,
        )
        not in allowed_bindings
    ):
        raise _error(
            "node_parameter_compilation_failed",
            "Agent returned an unknown parameter source.",
            details={"field": candidate.field, "reason": "source_not_allowed"},
        )
    _validated_platform_value(candidate.field, candidate.value, agent_value=True)
    return candidate


def _validated_platform_value(
    field: str,
    value: object,
    *,
    agent_value: bool = False,
) -> int | float | str | bool:
    invalid_code = (
        "node_parameter_compilation_failed" if agent_value else "node_parameter_unsupported"
    )
    if field == "duration_seconds":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _error(invalid_code, "duration_seconds must be a positive integer.")
        duration = int(value)
        if duration <= 0 or duration != value:
            raise _error(invalid_code, "duration_seconds must be a positive integer.")
        return duration
    if field in {"resolution", "aspect_ratio"}:
        if not isinstance(value, str) or not value.strip():
            raise _error(invalid_code, f"{field} must be a non-empty string.")
        return value.strip()
    if field == "generate_audio":
        if not isinstance(value, bool):
            raise _error(invalid_code, "generate_audio must be a boolean.")
        return value
    raise _error(
        invalid_code,
        "Video parameter field is unsupported.",
        details={"field": field},
    )


def _one_compatible_value(
    field: str,
    candidates: tuple[VideoParameterCandidateV2, ...],
) -> VideoParameterCandidateV2:
    first = candidates[0]
    if any(candidate.value != first.value for candidate in candidates[1:]):
        raise _error(
            "node_parameter_conflict",
            "Equal-priority parameter sources contain incompatible values.",
            details={
                "field": field,
                "sources": [
                    {
                        "source_kind": candidate.source_kind,
                        "source_node_id": candidate.source_node_id,
                        "binding_id": candidate.binding_id,
                    }
                    for candidate in candidates
                ],
                "retryable": True,
            },
        )
    return first


def _normalize_video_parameters(
    requested: dict[str, object],
    *,
    capability: CanvasProviderModelCapabilityV2,
) -> tuple[dict[str, object], tuple[VideoParameterNormalizationV2, ...]]:
    effective: dict[str, object] = {}
    normalizations: list[VideoParameterNormalizationV2] = []
    for field, raw_value in requested.items():
        value = _validated_platform_value(field, raw_value)
        if field not in capability.supported_parameters:
            if field == "generate_audio" and value is False:
                effective[field] = False
                continue
            if field == "generate_audio" and value is True:
                raise _error(
                    "video_native_audio_unsupported",
                    "Selected model cannot generate native audio.",
                    details={
                        "field": field,
                        "reason": "capability_missing",
                        "retryable": True,
                    },
                )
            raise _error(
                "node_parameter_unsupported",
                "Selected model does not support an explicit Video parameter.",
                details={"field": field, "retryable": True},
            )
        if field == "duration_seconds":
            bounds = capability.duration_range_seconds
            if bounds is None:
                raise _error(
                    "node_parameter_unsupported",
                    "Selected model has incomplete duration capability metadata.",
                )
            minimum, maximum = bounds
            clamped = min(max(int(value), int(minimum)), int(maximum))
            if clamped != value:
                code = (
                    "duration_clamped_to_minimum"
                    if value < minimum
                    else "duration_clamped_to_maximum"
                )
                normalizations.append(
                    VideoParameterNormalizationV2(
                        field="duration_seconds",
                        requested_value=value,
                        effective_value=clamped,
                        normalization_code=code,
                    )
                )
            effective[field] = clamped
        elif field == "resolution":
            resolution = str(value)
            supported = capability.supported_resolutions
            if not supported:
                raise _error(
                    "node_parameter_unsupported",
                    "Selected model has incomplete resolution capability metadata.",
                )
            if resolution in supported:
                effective[field] = resolution
                continue
            downgraded = _downgraded_resolution(resolution, supported)
            normalizations.append(
                VideoParameterNormalizationV2(
                    field="resolution",
                    requested_value=resolution,
                    effective_value=downgraded,
                    normalization_code="resolution_reduced_to_supported",
                )
            )
            effective[field] = downgraded
        elif field == "aspect_ratio":
            if value not in capability.supported_aspect_ratios:
                raise _error(
                    "node_parameter_unsupported",
                    "Selected model does not support the requested aspect ratio.",
                    details={"field": field, "retryable": True},
                )
            effective[field] = value
        elif field == "generate_audio":
            if value is True and not capability.supports_native_audio:
                raise _error(
                    "video_native_audio_unsupported",
                    "Selected model cannot generate native audio.",
                    details={
                        "field": field,
                        "reason": "capability_disabled",
                        "retryable": True,
                    },
                )
            effective[field] = value
    return effective, tuple(normalizations)


def _downgraded_resolution(requested: str, supported: tuple[str, ...]) -> str:
    ranks = {
        "480p": 480,
        "720p": 720,
        "1080p": 1080,
        "1440p": 1440,
        "2k": 1440,
        "2160p": 2160,
        "4k": 2160,
    }
    requested_rank = _resolution_rank(requested, ranks)
    supported_ranked = sorted(
        ((_resolution_rank(item, ranks), item) for item in supported),
        key=lambda pair: pair[0] or -1,
    )
    if requested_rank is None or any(rank is None for rank, _ in supported_ranked):
        raise _error(
            "node_parameter_unsupported",
            "Requested resolution has no deterministic supported mapping.",
        )
    candidates = [
        item for rank, item in supported_ranked if rank is not None and rank <= requested_rank
    ]
    if not candidates:
        raise _error(
            "node_parameter_unsupported",
            "Requested resolution is below every supported resolution.",
        )
    return candidates[-1]


def _resolution_rank(value: str, ranks: dict[str, int]) -> int | None:
    normalized = value.casefold()
    named_rank = ranks.get(normalized)
    if named_rank is not None:
        return named_rank
    dimensions = normalized.split("x")
    if len(dimensions) != 2 or any(not item.isdigit() for item in dimensions):
        return None
    width, height = (int(item) for item in dimensions)
    if width <= 0 or height <= 0:
        return None
    return min(width, height)


def _error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_execution_parameters",
        details=details,
    )
