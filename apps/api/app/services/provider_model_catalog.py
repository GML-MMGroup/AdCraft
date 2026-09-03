"""Trusted model manifests and deterministic provider catalog synchronization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from app.persistence.provider_model_repository import (
    ModelDefaultRecord,
    ProviderModelRecord,
    ProviderModelRepository,
)


class ProviderCatalogAdapter(Protocol):
    """Expose provider-visible IDs without granting application capabilities."""

    provider_id: str

    def discover_model_ids(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class TrustedModelManifest:
    provider_id: str
    provider_model_id: str
    display_name: str
    capability: str
    capability_metadata: Mapping[str, Any]
    adapter_profile: Mapping[str, Any] | None = None

    @property
    def model_ref(self) -> str:
        return f"{self.provider_id}:{self.provider_model_id}"


@dataclass(frozen=True)
class CatalogSyncResult:
    sync_run_id: str
    provider_id: str
    status: str
    catalog_revision: int | None


GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO: Mapping[str, str] = {
    "1:1": "2048x2048",
    "16:9": "2560x1440",
    "9:16": "1440x2560",
    "4:3": "2304x1728",
    "3:4": "1728x2304",
}


def _adapter_profile(
    *,
    model_ref: str,
    adapter_id: str,
    transport_kind: str,
    capability: str,
    request_mode: str,
    accepted_input_modes: tuple[str, ...],
    max_images: int,
    allowed_roles: tuple[str, ...],
    parameter_schema_id: str,
    result_protocol: str,
    supports_remote_task_lookup: bool,
    supports_provider_idempotency: bool,
    conformance_status: str,
    adapter_revision: str,
    capability_revision: str,
    release_tier: str = "optional",
    parameter_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "model_ref": model_ref,
        "adapter_id": adapter_id,
        "transport_kind": transport_kind,
        "capability": capability,
        "request_mode": request_mode,
        "accepted_input_modes": list(accepted_input_modes),
        "reference_policy": {
            "modes": [
                {
                    "mode": mode,
                    "max_references": max_images if mode != "text_only" else 0,
                    "allowed_roles": list(allowed_roles) if mode != "text_only" else [],
                }
                for mode in accepted_input_modes
            ],
            "max_images": max_images,
        },
        "parameter_schema_id": parameter_schema_id,
        "result_protocol": result_protocol,
        "supports_remote_task_lookup": supports_remote_task_lookup,
        "supports_provider_idempotency": supports_provider_idempotency,
        "release_tier": release_tier,
        "conformance_status": conformance_status,
        "adapter_revision": adapter_revision,
        "capability_revision": capability_revision,
    }
    if parameter_matrix is not None:
        profile["parameter_matrix"] = dict(parameter_matrix)
    return profile


def _parameter_matrix(
    *,
    schema_id: str,
    descriptors: tuple[Mapping[str, Any], ...],
    legal_combinations: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "schema_id": schema_id,
        "revision": f"{schema_id}-v1",
        "descriptors": [dict(descriptor) for descriptor in descriptors],
        "legal_combinations": [dict(combination) for combination in legal_combinations],
    }


def _image_profile(
    model_ref: str,
    *,
    adapter_id: str,
    transport_kind: str,
    conformance_status: str = "compatible",
    parameter_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _adapter_profile(
        model_ref=model_ref,
        adapter_id=adapter_id,
        transport_kind=transport_kind,
        capability="image",
        request_mode="image_generation",
        accepted_input_modes=("text_only", "native_reference_slots"),
        max_images=4,
        allowed_roles=("product_reference", "scene_reference", "character_reference"),
        parameter_schema_id="image-generation-v1",
        result_protocol="image_data",
        supports_remote_task_lookup=False,
        supports_provider_idempotency=False,
        conformance_status=conformance_status,
        adapter_revision=f"{adapter_id}-v1",
        capability_revision=f"{model_ref.replace(':', '-')}-v1",
        parameter_matrix=parameter_matrix,
    )


def _ark_video_profile(
    model_ref: str,
    *,
    release_tier: str = "optional",
) -> dict[str, Any]:
    return _adapter_profile(
        model_ref=model_ref,
        adapter_id="ark-video-native",
        transport_kind="ark_video_native",
        capability="video",
        request_mode="video_generation",
        accepted_input_modes=("text_only", "native_reference_slots"),
        max_images=15,
        allowed_roles=(
            "character_turnaround",
            "product_reference",
            "scene_reference",
            "storyboard",
        ),
        parameter_schema_id="ark-video-generation-v1",
        result_protocol="async_file",
        supports_remote_task_lookup=True,
        supports_provider_idempotency=False,
        conformance_status="compatible",
        adapter_revision="ark-video-native-v1",
        capability_revision=f"{model_ref.replace(':', '-')}-v1",
        release_tier=release_tier,
        parameter_matrix=_parameter_matrix(
            schema_id="ark-video-generation-v1",
            descriptors=(
                {
                    "name": "duration_seconds",
                    "value_type": "integer",
                    "minimum": 1,
                    "maximum": 15,
                    "default": 5,
                },
                {
                    "name": "resolution",
                    "value_type": "enum",
                    "allowed_values": ("480p", "720p", "1080p"),
                },
                {
                    "name": "aspect_ratio",
                    "value_type": "enum",
                    "allowed_values": ("16:9", "9:16", "1:1"),
                },
                {"name": "generate_audio", "value_type": "boolean", "default": False},
            ),
        ),
    )


def _minimax_video_profile(model_ref: str, provider_model_id: str) -> dict[str, Any]:
    return _adapter_profile(
        model_ref=model_ref,
        adapter_id="minimax-video-native",
        transport_kind="minimax_video_native",
        capability="video",
        request_mode="video_generation",
        accepted_input_modes=("text_only", "text_plus_single_first_frame_image"),
        max_images=1,
        allowed_roles=("storyboard", "scene_reference", "character_turnaround"),
        parameter_schema_id="minimax-hailuo-i2v-v1",
        result_protocol="async_file",
        supports_remote_task_lookup=True,
        supports_provider_idempotency=True,
        conformance_status="unverified",
        adapter_revision="minimax-video-native-v1",
        capability_revision=f"minimax-{provider_model_id}-i2v-v1",
        parameter_matrix=_parameter_matrix(
            schema_id="minimax-hailuo-i2v-v1",
            descriptors=(
                {
                    "name": "duration",
                    "value_type": "integer",
                    "minimum": 6,
                    "maximum": 10,
                },
                {
                    "name": "resolution",
                    "value_type": "enum",
                    "allowed_values": ("768P", "1080P"),
                },
                {
                    "name": "aspect_ratio",
                    "value_type": "enum",
                    "allowed_values": ("16:9", "9:16", "1:1"),
                },
                {"name": "generate_audio", "value_type": "boolean"},
            ),
            legal_combinations=(
                {"duration": 6, "resolution": "768P"},
                {"duration": 6, "resolution": "1080P"},
                {"duration": 10, "resolution": "768P"},
                {"duration": 10, "resolution": "1080P"},
            ),
        ),
    )


_OPENAI_IMAGE_PROFILE = _image_profile(
    "openai:gpt-image-2",
    adapter_id="openai-image-native",
    transport_kind="openai_images_native",
    conformance_status="unverified",
    parameter_matrix=_parameter_matrix(
        schema_id="openai-gpt-image-2-v1",
        descriptors=(
            {
                "name": "size",
                "value_type": "enum",
                "allowed_values": ("1024x1024", "1536x1024", "1024x1536", "auto"),
            },
            {
                "name": "quality",
                "value_type": "enum",
                "allowed_values": ("low", "medium", "high", "auto"),
            },
            {
                "name": "background",
                "value_type": "enum",
                "allowed_values": ("transparent", "opaque", "auto"),
            },
            {
                "name": "output_format",
                "value_type": "enum",
                "allowed_values": ("png", "jpeg", "webp"),
            },
        ),
    ),
)
_MINIMAX_VIDEO_PROFILES = {
    model_id: _minimax_video_profile(f"minimax:{model_id}", model_id)
    for model_id in (
        "MiniMax-Hailuo-2.3",
        "MiniMax-Hailuo-2.3-Fast",
        "MiniMax-Hailuo-02",
    )
}


def _video_capability_metadata(
    profile: Mapping[str, Any],
    *,
    duration_range_seconds: tuple[int, int] = (1, 15),
    max_references: int = 15,
    provider_protocol: str = "ark_video",
) -> dict[str, Any]:
    return {
        "accepted_input_types": ["text", "image", "video", "audio"],
        "max_references": max_references,
        "reference_limits": {"image": min(max_references, 9), "video": 3, "audio": 3},
        "supported_parameters": [
            "aspect_ratio",
            "resolution",
            "duration_seconds",
            "generate_audio",
        ],
        "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
        "supported_resolutions": ["480p", "720p", "1080p"],
        "duration_range_seconds": list(duration_range_seconds),
        "supports_native_audio": True,
        "provider_protocol": provider_protocol,
        "supports_provider_idempotency_token": False,
        "supports_remote_task_lookup": True,
        "adapter_profile": dict(profile),
    }


_TRUSTED_MANIFESTS = (
    TrustedModelManifest(
        provider_id="siliconflow",
        provider_model_id="zai-org/GLM-5.2",
        display_name="GLM-5.2",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "provider_protocol": "openai_compatible",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": True,
            "thinking_format": "zai",
            "reasoning_control": "enable_thinking",
            "structured_transport": "non_streaming_json_object",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seed-2-0-mini-260428",
        display_name="Doubao Seed 2.0 Mini",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "provider_protocol": "openai_compatible",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": False,
            "thinking_format": "none",
            "reasoning_control": "none",
            "structured_transport": "non_streaming_tool_call",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-5-0-lite-260128",
        display_name="Doubao Seedream 5.0 Lite",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 8,
            "reference_limits": {"image": 8, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "supported_aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "supported_sizes_by_aspect_ratio": dict(GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO),
            "pixel_bounds": [512, 4096],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-5-0-lite-260128",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-0-fast-260128",
        display_name="Doubao Seedance 2.0 Fast",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image", "video", "audio"],
            "max_references": 15,
            "reference_limits": {"image": 9, "video": 3, "audio": 3},
            "supported_parameters": [
                "aspect_ratio",
                "resolution",
                "duration_seconds",
                "generate_audio",
            ],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            "supported_resolutions": ["480p", "720p", "1080p"],
            "duration_range_seconds": [1, 15],
            "supports_native_audio": True,
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "generate_audio": False,
            },
            "provider_protocol": "ark_video",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
            "adapter_profile": _ark_video_profile(
                "volcengine_ark:doubao-seedance-2-0-fast-260128",
                release_tier="default",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-5-0-250128",
        display_name="Doubao Seedream 5.0 Pro",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-5-0-250128",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-4-5-251128",
        display_name="Doubao Seedream 4.5",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-4-5-251128",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-4-0-250828",
        display_name="Doubao Seedream 4.0",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-4-0-250828",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-0-260128",
        display_name="Doubao Seedance 2.0",
        capability="video",
        capability_metadata=_video_capability_metadata(
            _ark_video_profile("volcengine_ark:doubao-seedance-2-0-260128")
        ),
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-0-mini-260128",
        display_name="Doubao Seedance 2.0 Mini",
        capability="video",
        capability_metadata=_video_capability_metadata(
            _ark_video_profile("volcengine_ark:doubao-seedance-2-0-mini-260128")
        ),
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-5-260128",
        display_name="Doubao Seedance 2.5",
        capability="video",
        capability_metadata=_video_capability_metadata(
            _ark_video_profile("volcengine_ark:doubao-seedance-2-5-260128")
        ),
    ),
    TrustedModelManifest(
        provider_id="openai",
        provider_model_id="gpt-image-2",
        display_name="GPT Image 2",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": [
                "size",
                "quality",
                "background",
                "output_format",
                "moderation",
            ],
            "provider_protocol": "openai_images",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": dict(_OPENAI_IMAGE_PROFILE),
        },
    ),
    TrustedModelManifest(
        provider_id="minimax",
        provider_model_id="MiniMax-Hailuo-2.3",
        display_name="MiniMax Hailuo 2.3",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 1,
            "reference_limits": {"image": 1, "video": 0, "audio": 0},
            "supported_parameters": ["duration", "resolution", "aspect_ratio", "generate_audio"],
            "duration_seconds": [6, 10],
            "provider_protocol": "minimax_video_generation",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
            "adapter_profile": dict(_MINIMAX_VIDEO_PROFILES["MiniMax-Hailuo-2.3"]),
        },
    ),
    TrustedModelManifest(
        provider_id="minimax",
        provider_model_id="MiniMax-Hailuo-2.3-Fast",
        display_name="MiniMax Hailuo 2.3 Fast",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 1,
            "reference_limits": {"image": 1, "video": 0, "audio": 0},
            "supported_parameters": ["duration", "resolution", "aspect_ratio", "generate_audio"],
            "duration_seconds": [6, 10],
            "provider_protocol": "minimax_video_generation",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
            "adapter_profile": dict(_MINIMAX_VIDEO_PROFILES["MiniMax-Hailuo-2.3-Fast"]),
        },
    ),
    TrustedModelManifest(
        provider_id="minimax",
        provider_model_id="MiniMax-Hailuo-02",
        display_name="MiniMax Hailuo 02",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 1,
            "reference_limits": {"image": 1, "video": 0, "audio": 0},
            "supported_parameters": ["duration", "resolution", "aspect_ratio", "generate_audio"],
            "duration_seconds": [6, 10],
            "provider_protocol": "minimax_video_generation",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
            "adapter_profile": dict(_MINIMAX_VIDEO_PROFILES["MiniMax-Hailuo-02"]),
        },
    ),
    TrustedModelManifest(
        provider_id="tianpuyue",
        provider_model_id="TemPolor-i3",
        display_name="TemPolor i3",
        capability="audio",
        capability_metadata={
            "accepted_input_types": ["text"],
            "max_references": 0,
            "reference_limits": {"image": 0, "video": 0, "audio": 0},
            "supported_parameters": ["duration_seconds"],
            "duration_range_seconds": [1, 120],
            "automatic_tier_priority": 1,
            "provider_protocol": "tianpuyue_audio",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="tianpuyue",
        provider_model_id="TemPolor-i3.5",
        display_name="TemPolor i3.5",
        capability="audio",
        capability_metadata={
            "accepted_input_types": ["text"],
            "max_references": 0,
            "reference_limits": {"image": 0, "video": 0, "audio": 0},
            "supported_parameters": ["duration_seconds"],
            "duration_range_seconds": [1, 270],
            "automatic_tier_priority": 2,
            "provider_protocol": "tianpuyue_audio",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-text",
        display_name="Deterministic Text",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "provider_protocol": "fake",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": False,
            "thinking_format": "none",
            "reasoning_control": "none",
            "structured_transport": "non_streaming_tool_call",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-image",
        display_name="Deterministic Image",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 8,
            "reference_limits": {"image": 8, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "supported_aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "supported_sizes_by_aspect_ratio": dict(GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO),
            "pixel_bounds": [512, 4096],
            "provider_protocol": "fake",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-video",
        display_name="Deterministic Video",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image", "video", "audio"],
            "max_references": 15,
            "reference_limits": {"image": 9, "video": 3, "audio": 3},
            "supported_parameters": [
                "aspect_ratio",
                "resolution",
                "duration_seconds",
                "generate_audio",
            ],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            "supported_resolutions": ["480p", "720p", "1080p"],
            "duration_range_seconds": [1, 15],
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "generate_audio": False,
            },
            "supports_native_audio": True,
            "provider_protocol": "fake",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-audio",
        display_name="Deterministic Audio",
        capability="audio",
        capability_metadata={
            "accepted_input_types": ["text"],
            "max_references": 0,
            "reference_limits": {"image": 0, "video": 0, "audio": 0},
            "supported_parameters": ["duration_seconds"],
            "duration_range_seconds": [1, 600],
            "provider_protocol": "fake",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
        },
    ),
)


class StaticProviderCatalogAdapter:
    """Default deterministic adapter used until a provider implements discovery."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def discover_model_ids(self) -> tuple[str, ...]:
        return tuple(
            manifest.provider_model_id
            for manifest in _TRUSTED_MANIFESTS
            if manifest.provider_id == self.provider_id
        )


class ProviderModelCatalogService:
    """Own trusted model metadata, availability, query filtering, and defaults."""

    def __init__(
        self,
        repository: ProviderModelRepository,
        *,
        adapters: tuple[ProviderCatalogAdapter, ...] | None = None,
        capability_available: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._repository = repository
        configured_adapters = adapters or tuple(
            StaticProviderCatalogAdapter(provider_id)
            for provider_id in (
                "siliconflow",
                "volcengine_ark",
                "tianpuyue",
                "openai",
                "minimax",
                "fake",
            )
        )
        self._adapters = {adapter.provider_id: adapter for adapter in configured_adapters}
        self._capability_available = capability_available or self._repository_capability_available

    def sync(self, provider_id: str, *, now: str) -> CatalogSyncResult:
        sync_run_id = f"sync_{uuid4().hex}"
        try:
            visible_model_ids = self._visible_model_ids(provider_id)
        except Exception as exc:
            self._repository.record_sync_run(
                sync_run_id=sync_run_id,
                provider_id=provider_id,
                status="failed",
                catalog_revision=None,
                summary={"visible_model_count": 0},
                error_code="model_catalog_sync_failed",
                created_at=now,
            )
            raise ValueError("model_catalog_sync_failed") from exc

        models = self._project_models(provider_id, visible_model_ids)
        persisted = self._repository.upsert_models(
            provider_id=provider_id,
            models=models,
            updated_at=now,
        )
        revision = max((model.catalog_revision for model in persisted), default=None)
        self._repository.record_sync_run(
            sync_run_id=sync_run_id,
            provider_id=provider_id,
            status="succeeded",
            catalog_revision=revision,
            summary={"visible_model_count": len(visible_model_ids)},
            error_code=None,
            created_at=now,
        )
        return CatalogSyncResult(
            sync_run_id=sync_run_id,
            provider_id=provider_id,
            status="succeeded",
            catalog_revision=revision,
        )

    def reconcile_trusted_models(
        self,
        provider_id: str,
        *,
        now: str,
    ) -> tuple[ProviderModelRecord, ...]:
        """Converge code-owned model projections without touching user policy."""

        visible_model_ids = self._visible_model_ids(provider_id)
        projected = tuple(
            model
            for model in self._project_models(provider_id, visible_model_ids)
            if model["source"] == "built_in"
        )
        existing = {
            model.model_ref: model
            for model in self._repository.list_models(provider_id=provider_id)
        }
        changed = tuple(
            model
            for model in projected
            if _trusted_projection_changed(existing.get(str(model["model_ref"])), model)
        )
        if not changed:
            return ()
        return self._repository.upsert_models(
            provider_id=provider_id,
            models=changed,
            updated_at=now,
        )

    def _visible_model_ids(self, provider_id: str) -> set[str]:
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            raise ValueError("provider_not_supported")
        return set(adapter.discover_model_ids())

    def _project_models(
        self,
        provider_id: str,
        visible_model_ids: set[str],
    ) -> list[dict[str, Any]]:
        trusted = {
            manifest.provider_model_id: manifest
            for manifest in _TRUSTED_MANIFESTS
            if manifest.provider_id == provider_id
        }
        models: list[dict[str, Any]] = []
        for provider_model_id in sorted(visible_model_ids):
            manifest = trusted.get(provider_model_id)
            if manifest is None:
                models.append(
                    {
                        "model_ref": f"{provider_id}:{provider_model_id}",
                        "provider_model_id": provider_model_id,
                        "display_name": provider_model_id,
                        "capability": "text",
                        "capability_metadata": {},
                        "source": "discovered",
                        "availability": "unsupported",
                        "unavailable_reason": "model_not_supported",
                    }
                )
                continue
            models.append(
                _trusted_projection(
                    manifest,
                    available=self._capability_is_available(
                        manifest.provider_id,
                        manifest.capability,
                    ),
                )
            )
        previously_known = {
            model.provider_model_id
            for model in self._repository.list_models(provider_id=provider_id)
            if model.source == "built_in"
        }
        for provider_model_id in sorted(previously_known.difference(visible_model_ids)):
            manifest = trusted.get(provider_model_id)
            if manifest is None:
                continue
            models.append(
                _trusted_projection(
                    manifest,
                    available=False,
                    unavailable_reason="provider_model_not_visible",
                )
            )
        return models

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        capability: str | None = None,
        node_type: str | None = None,
        purpose: str | None = None,
        include_unavailable: bool = False,
    ) -> tuple[ProviderModelRecord, ...]:
        required_capability = _required_capability(
            node_type=node_type, purpose=purpose, capability=capability
        )
        if node_type == "editing":
            return ()
        models = self._repository.list_models(
            provider_id=provider_id,
            capability=required_capability,
            availability=None,
        )
        models = tuple(self._with_current_credential_availability(model) for model in models)
        if not include_unavailable:
            models = tuple(model for model in models if model.availability == "available")
        if node_type == "script" or purpose == "agent":
            models = tuple(
                model for model in models if bool(model.capability_metadata.get("agent_compatible"))
            )
        return models

    def get_model(self, model_ref: str) -> ProviderModelRecord:
        """Return one model with current capability credential availability."""

        return self._with_current_credential_availability(self._repository.get_model(model_ref))

    def set_defaults(
        self,
        defaults: Mapping[str, str],
        *,
        modes: Mapping[str, str] | None = None,
        now: str,
    ) -> dict[str, ModelDefaultRecord]:
        mode_updates = dict(modes or {})
        if not defaults and not mode_updates:
            raise ValueError("model_default_update_invalid")
        for default_key, model_ref in defaults.items():
            try:
                model = self.get_model(model_ref)
            except ValueError as exc:
                raise ValueError("model_not_found") from exc
            if model.availability != "available":
                raise ValueError("model_unavailable")
            if not _model_matches_default(default_key, model):
                raise ValueError("model_capability_mismatch")
        for default_key, selection_mode in mode_updates.items():
            if selection_mode not in {"automatic", "explicit"}:
                raise ValueError("model_default_mode_invalid")
            if selection_mode == "automatic" and default_key != "audio":
                raise ValueError("model_automatic_policy_unsupported")
        try:
            return self._repository.set_defaults(defaults, modes=mode_updates, updated_at=now)
        except ValueError as exc:
            if str(exc) == "model_default_capability_invalid":
                raise ValueError("model_capability_mismatch") from exc
            raise

    def get_defaults(self) -> dict[str, str]:
        return {key: record.model_ref for key, record in self._repository.get_defaults().items()}

    def get_default_records(self) -> dict[str, ModelDefaultRecord]:
        """Return the public default references with their monotonic revisions."""

        return self._repository.get_defaults()

    def _capability_is_available(self, provider_id: str, capability: str) -> bool:
        return provider_id == "fake" or self._capability_available(provider_id, capability)

    def _repository_capability_available(self, provider_id: str, capability: str) -> bool:
        try:
            connection = self._repository.get_connection(provider_id)
        except ValueError:
            return False
        status = connection.credential_status.get(capability)
        return isinstance(status, Mapping) and status.get("configured") is True

    def _with_current_credential_availability(
        self,
        model: ProviderModelRecord,
    ) -> ProviderModelRecord:
        if model.provider_id == "fake":
            return model
        credential_managed = model.availability == "available" or (
            model.availability == "unavailable"
            and model.unavailable_reason == "provider_credentials_missing"
        )
        if not credential_managed:
            return model
        available = self._capability_is_available(model.provider_id, model.capability)
        availability = "available" if available else "unavailable"
        unavailable_reason = None if available else "provider_credentials_missing"
        if model.availability == availability and model.unavailable_reason == unavailable_reason:
            return model
        return replace(
            model,
            availability=availability,
            unavailable_reason=unavailable_reason,
        )


def _required_capability(
    *,
    node_type: str | None,
    purpose: str | None,
    capability: str | None,
) -> str | None:
    if capability is not None:
        return capability
    if node_type in {"text", "script"}:
        return "text"
    if node_type in {"image", "video", "audio"}:
        return node_type
    if purpose in {"agent", "text", "image", "video", "audio"}:
        return "text" if purpose == "agent" else purpose
    return None


def _model_matches_default(default_key: str, model: ProviderModelRecord) -> bool:
    if default_key == "agent":
        return model.capability == "text" and bool(
            model.capability_metadata.get("agent_compatible")
        )
    return model.capability == default_key


def _trusted_projection(
    manifest: TrustedModelManifest,
    *,
    available: bool,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    capability_metadata = dict(manifest.capability_metadata)
    if manifest.adapter_profile is not None:
        capability_metadata["adapter_profile"] = dict(manifest.adapter_profile)
    return {
        "model_ref": manifest.model_ref,
        "provider_model_id": manifest.provider_model_id,
        "display_name": manifest.display_name,
        "capability": manifest.capability,
        "capability_metadata": capability_metadata,
        "source": "built_in",
        "availability": "available" if available else "unavailable",
        "unavailable_reason": (
            None if available else unavailable_reason or "provider_credentials_missing"
        ),
    }


def _trusted_projection_changed(
    existing: ProviderModelRecord | None,
    projected: Mapping[str, Any],
) -> bool:
    if existing is None:
        return True
    if existing.source != "built_in":
        return False
    return any(
        current != projected[key]
        for key, current in (
            ("display_name", existing.display_name),
            ("capability", existing.capability),
            ("capability_metadata", existing.capability_metadata),
            ("availability", existing.availability),
            ("unavailable_reason", existing.unavailable_reason),
        )
    )
