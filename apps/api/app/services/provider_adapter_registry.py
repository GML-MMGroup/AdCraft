"""Trusted provider adapter claims for the canonical model catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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
