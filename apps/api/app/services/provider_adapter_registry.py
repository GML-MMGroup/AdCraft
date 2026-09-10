"""Trusted provider adapter claims for the canonical model catalog."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings
from app.persistence.provider_model_repository import ProviderModelRecord
from app.schemas.provider_models import ProviderAdapterProfileV1


class ProviderAdapter(Protocol):
    """Common adapter lifecycle behind the Python-owned provider executor."""

    def validate(self, request: Any, capability: str) -> Any: ...

    def compile(self, request: Any, resolution: Any) -> Any: ...

    def submit(self, request: Any) -> Any: ...

    def poll(self, submission: Any) -> Any: ...

    def download(self, status: Any) -> Any: ...

    def normalize(self, artifact: Any) -> Any: ...

    def request_fingerprint(self, request: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class ResolvedProviderAdapter:
    profile: ProviderAdapterProfileV1
    adapter: ProviderAdapter


class ProviderAdapterRegistry:
    """Resolve one trusted profile for one exact model/capability pair."""

    def __init__(self) -> None:
        self._claims: dict[tuple[str, str], ResolvedProviderAdapter] = {}

    def register(self, profile: ProviderAdapterProfileV1, adapter: ProviderAdapter) -> None:
        key = (profile.model_ref, profile.capability)
        if key in self._claims:
            raise ValueError("provider_adapter_registry_conflict")
        self._claims[key] = ResolvedProviderAdapter(profile=profile, adapter=adapter)

    def register_catalog_model(
        self,
        record: ProviderModelRecord,
        adapter: ProviderAdapter,
    ) -> None:
        """Register only a selectable built-in catalog claim."""

        if record.source != "built_in" or record.availability != "available":
            raise ValueError("model_adapter_unavailable")
        raw_profile = record.capability_metadata.get("adapter_profile")
        try:
            profile = ProviderAdapterProfileV1.model_validate(raw_profile)
        except Exception as error:
            raise ValueError("provider_adapter_profile_invalid") from error
        if profile.model_ref != record.model_ref or profile.capability != record.capability:
            raise ValueError("provider_adapter_profile_invalid")
        self.register(profile, adapter)

    def resolve(self, model_ref: str, capability: str) -> ResolvedProviderAdapter:
        resolved = self._claims.get((model_ref, capability))
        if resolved is None:
            raise ValueError("model_adapter_unavailable")
        status = resolved.profile.conformance_status
        if status == "revoked":
            raise ValueError("model_conformance_revoked")
        if status == "unverified":
            raise ValueError("model_conformance_required")
        return resolved

    def profiles(self) -> tuple[ProviderAdapterProfileV1, ...]:
        return tuple(item.profile for item in self._claims.values())

    @staticmethod
    def validate_profiles(profiles: tuple[ProviderAdapterProfileV1, ...]) -> None:
        seen: set[tuple[str, str]] = set()
        for profile in profiles:
            key = (profile.model_ref, profile.capability)
            if key in seen:
                raise ValueError("provider_adapter_registry_conflict")
            seen.add(key)


def build_trusted_provider_adapter_registry(
    models: Iterable[ProviderModelRecord],
    *,
    settings: Settings | None = None,
) -> ProviderAdapterRegistry:
    """Build the executable adapter registry from the current catalog snapshot."""

    registry = ProviderAdapterRegistry()
    for record in models:
        if record.source != "built_in" or record.availability != "available":
            continue
        raw_profile = record.capability_metadata.get("adapter_profile")
        if raw_profile is None:
            continue
        try:
            profile = ProviderAdapterProfileV1.model_validate(raw_profile)
        except Exception as error:
            raise ValueError("provider_adapter_profile_invalid") from error
        adapter = _adapter_for_profile(
            profile,
            provider_model_id=record.provider_model_id,
            settings=settings,
        )
        registry.register_catalog_model(record, adapter)
    registry.validate_profiles(registry.profiles())
    return registry


def _adapter_for_profile(
    profile: ProviderAdapterProfileV1,
    *,
    provider_model_id: str,
    settings: Settings | None,
) -> ProviderAdapter:
    from app.services.provider_native_adapters import (
        ArkMediaAdapter,
        MiniMaxVideoAdapter,
        OpenRouterImageAdapter,
        OpenRouterImageTransport,
    )

    if profile.transport_kind == "openrouter_images_native":
        return OpenRouterImageAdapter(
            transport=OpenRouterImageTransport(settings) if settings is not None else None
        )
    if profile.transport_kind == "minimax_video_native":
        return MiniMaxVideoAdapter(provider_model_id=provider_model_id)
    if profile.transport_kind in {"ark_image_native", "ark_video_native"}:
        return ArkMediaAdapter(profile)
    raise ValueError("provider_adapter_profile_invalid")
