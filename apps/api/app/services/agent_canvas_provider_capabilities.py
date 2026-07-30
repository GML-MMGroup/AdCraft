"""Configuration-backed provider capability filtering for Agent Canvas."""

from __future__ import annotations

from collections import Counter

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, ResolvedInputSnapshotV2
from app.schemas.agent_canvas_runtime import (
    BindingCapabilityDecisionV2,
    CanvasProviderModelCapabilityListV2,
    CanvasProviderModelCapabilityV2,
)


class ProviderCapabilityError(V2PersistenceError):
    """Stable capability error with bounded client remediation details."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(code, message, stage="agent_canvas_provider_capabilities")
        self.details = details


class ProviderCapabilityService:
    """Expose configured models without credentials or provider secrets."""

    def __init__(self, settings: Settings) -> None:
        self._items = _configured_capabilities(settings)

    def list(
        self,
        *,
        output_type: str | None = None,
        input_types: frozenset[str] = frozenset(),
        include_unavailable: bool = False,
    ) -> CanvasProviderModelCapabilityListV2:
        items = tuple(
            item
            for item in self._items
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
        violated_limit = _first_reference_limit_violation(reference_counts, self._items, node)
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
        selected = next(
            (item for item in compatible if item.model_id == node.model_id),
            None,
        )
        if node.model_id is not None and selected is None:
            raise ProviderCapabilityError(
                "node_model_incompatible",
                "Selected model is incompatible with the node inputs.",
                node_id=node.node_id,
                selected_model_id=node.model_id,
                required_input_types=sorted(input_types),
                compatible_model_ids=[item.model_id for item in compatible],
                switch_model_required=True,
            )
        if selected is not None:
            return selected
        if compatible:
            return compatible[0]
        raise ProviderCapabilityError(
            "node_model_incompatible",
            "No configured provider model supports the node inputs.",
            node_id=node.node_id,
            selected_model_id=node.model_id,
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
        selected = next((item for item in compatible if item.model_id == target.model_id), None)
        selected_compatible = (
            any(
                _reference_counts_compatible(item, reference_count, reference_counts)
                for item in compatible
            )
            if target.model_id is None
            else selected is not None
            and _reference_counts_compatible(selected, reference_count, reference_counts)
        )
        return BindingCapabilityDecisionV2(
            accepted=selected_compatible,
            target_node_id=target.node_id,
            selected_model_id=target.model_id,
            required_input_types=required_input_types,
            compatible_model_ids=tuple(item.model_id for item in compatible),
            switch_model_required=not selected_compatible,
        )


def _configured_capabilities(
    settings: Settings,
) -> tuple[CanvasProviderModelCapabilityV2, ...]:
    fake = settings.agent_runtime_mode == "fake" or settings.media_mode == "mock"
    image_available = fake or bool(
        settings.image_generation_api_key and settings.image_generation_endpoint
    )
    video_available = fake or bool(
        settings.video_generation_api_key and settings.video_generation_endpoint
    )
    audio_available = fake or bool(
        settings.bgm_api_key or (settings.bgm_access_key_id and settings.bgm_secret_access_key)
    )
    return (
        CanvasProviderModelCapabilityV2(
            provider="fake" if fake else "volcengine",
            model_id=settings.image_generation_model,
            output_type="image",
            accepted_input_types=frozenset({"text", "image"}),
            max_references=8,
            reference_limits={"image": 8, "video": 0, "audio": 0},
            supported_parameters=frozenset({"aspect_ratio", "size"}),
            supported_aspect_ratios=("1:1", "16:9", "9:16", "4:3", "3:4"),
            pixel_bounds=(512, 4096),
            available=image_available,
            unavailable_reason=None if image_available else "provider_not_configured",
        ),
        CanvasProviderModelCapabilityV2(
            provider="fake" if fake else "volcengine",
            model_id=settings.video_generation_model,
            output_type="video",
            accepted_input_types=frozenset({"text", "image", "video", "audio"}),
            max_references=15,
            reference_limits={"image": 9, "video": 3, "audio": 3},
            supported_parameters=frozenset(
                {"aspect_ratio", "resolution", "duration_seconds", "generate_audio"}
            ),
            supported_aspect_ratios=("16:9", "9:16", "1:1"),
            duration_range_seconds=(1, 15),
            available=video_available,
            unavailable_reason=None if video_available else "provider_not_configured",
            supports_native_audio=settings.video_generation_generate_audio,
        ),
        CanvasProviderModelCapabilityV2(
            provider="fake" if fake else settings.bgm_provider,
            model_id=settings.bgm_model or "configured-bgm",
            output_type="audio",
            accepted_input_types=frozenset({"text"}),
            max_references=0,
            reference_limits={"image": 0, "video": 0, "audio": 0},
            supported_parameters=frozenset({"duration_seconds"}),
            duration_range_seconds=(1, 600),
            available=audio_available,
            unavailable_reason=None if audio_available else "provider_not_configured",
        ),
    )


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
    if not set(node.parameters).issubset(capability.supported_parameters):
        return False
    aspect_ratio = node.parameters.get("aspect_ratio")
    if aspect_ratio is not None and str(aspect_ratio) not in capability.supported_aspect_ratios:
        return False
    duration = node.parameters.get("duration_seconds")
    if duration is not None and capability.duration_range_seconds is not None:
        try:
            value = float(duration)
        except (TypeError, ValueError):
            return False
        low, high = capability.duration_range_seconds
        if value < low:
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
        and (node.model_id is None or item.model_id == node.model_id)
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
