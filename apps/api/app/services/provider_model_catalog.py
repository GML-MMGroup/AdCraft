"""Trusted model manifests and deterministic provider catalog synchronization."""

from __future__ import annotations

from dataclasses import dataclass
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
            "supports_reasoning_controls": False,
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
            "supported_parameters": ["aspect_ratio", "resolution", "duration_seconds"],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            "supported_resolutions": ["480p", "720p", "1080p"],
            "duration_range_seconds": [1, 15],
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
            },
            "provider_protocol": "fake",
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
        provider_available: Callable[[str], bool] | None = None,
    ) -> None:
        self._repository = repository
        configured_adapters = adapters or tuple(
            StaticProviderCatalogAdapter(provider_id)
            for provider_id in ("siliconflow", "volcengine_ark", "tianpuyue", "fake")
        )
        self._adapters = {adapter.provider_id: adapter for adapter in configured_adapters}
        self._provider_available = provider_available or (lambda _: False)

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
        available = self._provider_available(provider_id) or provider_id == "fake"
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
            models.append(_trusted_projection(manifest, available=available))
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
            availability=None if include_unavailable else "available",
        )
        if node_type == "script" or purpose == "agent":
            models = tuple(
                model for model in models if bool(model.capability_metadata.get("agent_compatible"))
            )
        return models

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
                model = self._repository.get_model(model_ref)
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
    return {
        "model_ref": manifest.model_ref,
        "provider_model_id": manifest.provider_model_id,
        "display_name": manifest.display_name,
        "capability": manifest.capability,
        "capability_metadata": dict(manifest.capability_metadata),
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
