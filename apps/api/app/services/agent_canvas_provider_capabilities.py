"""Catalog-backed provider capability filtering for Agent Canvas."""

from __future__ import annotations

from collections import Counter

from app.persistence.errors import V2PersistenceError
from app.persistence.provider_model_repository import ProviderModelRecord
from app.schemas.agent_canvas import CanvasNodeV2, ResolvedInputSnapshotV2
from app.schemas.agent_canvas_runtime import (
    BindingCapabilityDecisionV2,
    CanvasProviderModelCapabilityListV2,
    CanvasProviderModelCapabilityV2,
    EffectiveMediaParameterSnapshotV2,
)
from app.services.agent_canvas_parameter_policy import NON_PROVIDER_NODE_PARAMETER_KEYS
from app.services.provider_model_catalog import ProviderModelCatalogService


class ProviderCapabilityError(V2PersistenceError):
    """Stable capability error with bounded client remediation details."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(code, message, stage="agent_canvas_provider_capabilities")
        self.details = details


class ProviderCapabilityService:
    """Expose catalog models without credentials or provider secrets."""

    def __init__(self, catalog: ProviderModelCatalogService) -> None:
        self._catalog = catalog

    def list(
        self,
        *,
        output_type: str | None = None,
        input_types: frozenset[str] = frozenset(),
        include_unavailable: bool = False,
    ) -> CanvasProviderModelCapabilityListV2:
        items = tuple(
            item
            for item in self._items(include_unavailable=include_unavailable)
            if (output_type is None or item.output_type == output_type)
            and input_types.issubset(item.accepted_input_types)
            and (include_unavailable or item.available)
        )
        return CanvasProviderModelCapabilityListV2(items=items)

    def resolve(
        self,
        node: CanvasNodeV2,
        inputs: tuple[ResolvedInputSnapshotV2 | object, ...],
    ) -> CanvasProviderModelCapabilityV2:
        if node.node_type not in {"image", "video", "audio"}:
            raise ProviderCapabilityError(
                "node_not_runnable",
                "Node type does not use a media provider.",
            )
        input_types = _input_types(inputs)
        reference_counts = _reference_counts(inputs)
        capabilities = self._items(include_unavailable=True)
        violated_limit = _first_reference_limit_violation(reference_counts, capabilities, node)
        if violated_limit is not None:
            media_type, limit = violated_limit
            raise ProviderCapabilityError(
                "canvas_reference_limit_exceeded",
                "The node exceeds the configured provider reference limit.",
                node_id=node.node_id,
                media_type=media_type,
                limit=limit,
                count=reference_counts[media_type],
            )
        compatible = self.list(
            output_type=node.node_type,
            input_types=input_types,
        ).items
        compatible = tuple(
            item for item in compatible if _parameters_compatible(node, inputs, item)
        )
        selected = next((item for item in compatible if item.model_id == node.model_ref), None)
        if node.model_selection_mode == "explicit" and selected is None:
            raise ProviderCapabilityError(
                "model_capability_mismatch",
                "Selected model is incompatible with the node inputs.",
                node_id=node.node_id,
                selected_model_id=node.model_ref,
                required_input_types=sorted(input_types),
                compatible_model_ids=[item.model_id for item in compatible],
                switch_model_required=True,
            )
        if selected is not None:
            return selected
        if compatible:
            return compatible[0]
        raise ProviderCapabilityError(
            "model_capability_mismatch",
            "No configured provider model supports the node inputs.",
            node_id=node.node_id,
            selected_model_id=node.model_ref,
            required_input_types=sorted(input_types),
            compatible_model_ids=[],
            switch_model_required=True,
        )

    def validate_binding(
        self,
        target: CanvasNodeV2,
        *,
        required_input_types: frozenset[str],
        reference_count: int = 0,
        reference_counts: dict[str, int] | None = None,
    ) -> BindingCapabilityDecisionV2:
        compatible = self.list(
            output_type=target.node_type,
            input_types=required_input_types,
        ).items
        selected = next((item for item in compatible if item.model_id == target.model_ref), None)
        selected_compatible = (
            any(
                _reference_counts_compatible(item, reference_count, reference_counts)
                for item in compatible
            )
            if target.model_selection_mode == "default"
            else selected is not None
            and _reference_counts_compatible(selected, reference_count, reference_counts)
        )
        return BindingCapabilityDecisionV2(
            accepted=selected_compatible,
            target_node_id=target.node_id,
            selected_model_id=target.model_ref,
            required_input_types=required_input_types,
            compatible_model_ids=tuple(item.model_id for item in compatible),
            switch_model_required=not selected_compatible,
        )

    def effective_parameters(
        self,
        node: CanvasNodeV2,
        capability: CanvasProviderModelCapabilityV2,
        *,
        normalizations: tuple[str, ...] = (),
    ) -> EffectiveMediaParameterSnapshotV2:
        """Normalize the saved Node parameters once for a selected model."""

        requested = {
            key: value
            for key, value in node.parameters.items()
            if key not in NON_PROVIDER_NODE_PARAMETER_KEYS
        }
        effective = dict(requested)
        applied_normalizations: list[str] = list(normalizations)
        if node.node_type == "video":
            requested_duration = requested.get("duration_seconds", 5)
            duration = _positive_integer_duration(requested_duration)
            if capability.duration_range_seconds is not None:
                _, maximum = capability.duration_range_seconds
                maximum_duration = int(maximum)
                if duration > maximum_duration:
                    duration = maximum_duration
                    applied_normalizations.append("duration_clamped_to_provider_limit")
            effective["duration_seconds"] = duration
            requested_audio = bool(requested.get("generate_audio", False))
            if requested_audio and (
                "generate_audio" not in capability.supported_parameters
                or not capability.supports_native_audio
            ):
                effective["generate_audio"] = False
                applied_normalizations.append("generate_audio_omitted_for_model_capability")
            elif "generate_audio" in capability.supported_parameters:
                effective["generate_audio"] = requested_audio
            else:
                effective.pop("generate_audio", None)
        return EffectiveMediaParameterSnapshotV2(
            requested=requested,
            effective=effective,
            normalizations=tuple(applied_normalizations),
            provider=capability.provider,
            model_id=capability.model_id,
            capability_revision=capability.capability_revision,
        )

    def _items(self, *, include_unavailable: bool) -> tuple[CanvasProviderModelCapabilityV2, ...]:
        return tuple(
            _capability_from_record(record)
            for record in self._catalog.list_models(include_unavailable=include_unavailable)
            if record.capability in {"image", "video", "audio"}
        )


def _capability_from_record(record: ProviderModelRecord) -> CanvasProviderModelCapabilityV2:
    metadata = record.capability_metadata
    output_type = record.capability
    limits = _reference_limits(output_type, metadata)
    return CanvasProviderModelCapabilityV2(
        provider=record.provider_id,
        model_id=record.model_ref,
        output_type=output_type,
        accepted_input_types=frozenset(metadata.get("accepted_input_types", ["text"])),
        max_references=int(metadata.get("max_references", sum(limits.values()))),
        reference_limits=limits,
        supported_parameters=frozenset(metadata.get("supported_parameters", [])),
        default_parameters=dict(metadata.get("default_parameters", {})),
        supported_resolutions=tuple(metadata.get("supported_resolutions", ())),
        supported_aspect_ratios=tuple(metadata.get("supported_aspect_ratios", ())),
        pixel_bounds=_optional_pair(metadata.get("pixel_bounds")),
        duration_range_seconds=_optional_pair(metadata.get("duration_range_seconds")),
        available=record.availability == "available",
        unavailable_reason=record.unavailable_reason,
        supports_native_audio=bool(metadata.get("supports_native_audio", False)),
        capability_revision=record.catalog_revision,
    )


def _reference_limits(output_type: str, metadata: dict[str, object]) -> dict[str, int]:
    supplied = metadata.get("reference_limits")
    if isinstance(supplied, dict):
        return {str(key): int(value) for key, value in supplied.items()}
    if output_type == "image":
        return {"image": int(metadata.get("max_references", 8)), "video": 0, "audio": 0}
    if output_type == "video":
        return {"image": 9, "video": 3, "audio": 3}
    return {"image": 0, "video": 0, "audio": 0}


def _optional_pair(value: object) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    return int(value[0]), int(value[1])


def _input_types(inputs: tuple[object, ...]) -> frozenset[str]:
    result = {"text"}
    for item in inputs:
        media_type = getattr(item, "media_type", None)
        if media_type in {"image", "video", "audio"}:
            result.add(media_type)
    return frozenset(result)


def _parameters_compatible(
    node: CanvasNodeV2,
    inputs: tuple[object, ...],
    capability: CanvasProviderModelCapabilityV2,
) -> bool:
    reference_counts = _reference_counts(inputs)
    reference_count = sum(reference_counts.values())
    if not _reference_counts_compatible(capability, reference_count, reference_counts):
        return False
    provider_parameters = set(node.parameters).difference(NON_PROVIDER_NODE_PARAMETER_KEYS)
    if node.node_type == "video":
        provider_parameters.discard("generate_audio")
    if not provider_parameters.issubset(capability.supported_parameters):
        return False
    aspect_ratio = node.parameters.get("aspect_ratio")
    if aspect_ratio is not None and str(aspect_ratio) not in capability.supported_aspect_ratios:
        return False
    duration = node.parameters.get("duration_seconds")
    if duration is not None and capability.duration_range_seconds is not None:
        try:
            float(duration)
        except (TypeError, ValueError):
            return False
    size = node.parameters.get("size") or node.parameters.get("resolution")
    if size is not None and capability.pixel_bounds is not None:
        try:
            width_text, height_text = str(size).lower().split("x", 1)
            width, height = int(width_text), int(height_text)
        except (TypeError, ValueError):
            return False
        low, high = capability.pixel_bounds
        if min(width, height) < low or max(width, height) > high:
            return False
    return True


def _positive_integer_duration(value: object) -> int:
    if isinstance(value, bool):
        raise ProviderCapabilityError(
            "media_parameters_invalid",
            "Video duration must be a positive integer.",
        )
    try:
        duration = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ProviderCapabilityError(
            "media_parameters_invalid",
            "Video duration must be a positive integer.",
        ) from error
    if duration <= 0 or (duration != value and str(duration) != str(value)):
        raise ProviderCapabilityError(
            "media_parameters_invalid",
            "Video duration must be a positive integer.",
        )
    return duration


def _reference_counts(inputs: tuple[object, ...]) -> Counter[str]:
    return Counter(
        str(media_type)
        for item in inputs
        if (media_type := getattr(item, "media_type", None)) in {"image", "video", "audio"}
    )


def _reference_counts_compatible(
    capability: CanvasProviderModelCapabilityV2,
    reference_count: int,
    reference_counts: dict[str, int] | Counter[str] | None,
) -> bool:
    if reference_count > capability.max_references:
        return False
    return all(
        count <= capability.reference_limits.get(media_type, capability.max_references)
        for media_type, count in (reference_counts or {}).items()
    )


def _first_reference_limit_violation(
    reference_counts: Counter[str],
    capabilities: tuple[CanvasProviderModelCapabilityV2, ...],
    node: CanvasNodeV2,
) -> tuple[str, int] | None:
    candidates = tuple(
        item
        for item in capabilities
        if item.output_type == node.node_type
        and (node.model_selection_mode == "default" or item.model_id == node.model_ref)
    )
    if not candidates:
        return None
    for media_type in ("image", "video", "audio"):
        count = reference_counts[media_type]
        if count and all(
            count > item.reference_limits.get(media_type, item.max_references)
            for item in candidates
        ):
            return media_type, max(
                item.reference_limits.get(media_type, item.max_references) for item in candidates
            )
    return None
