"""Startup seeding for trusted provider catalog entries and installation defaults."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.core.config import PROJECT_ROOT, Settings
from app.persistence.provider_model_repository import ProviderModelRepository
from app.services.provider_credentials import (
    DotenvCredentialStore,
    ProviderConnectionService,
    ProviderCredentialRegistry,
)
from app.services.provider_model_catalog import ProviderModelCatalogService


_BOOTSTRAP_LOCK = Lock()


@dataclass(frozen=True)
class ProviderModelBootstrapResult:
    seeded_providers: tuple[str, ...]
    seeded_defaults: tuple[str, ...]


class ProviderModelBootstrapService:
    """Seed missing model policy without replacing existing catalog or defaults."""

    def __init__(self, settings: Settings, repository: ProviderModelRepository) -> None:
        self._settings = settings
        self._repository = repository

    def bootstrap(self, *, now: str) -> ProviderModelBootstrapResult:
        with _BOOTSTRAP_LOCK:
            return self._bootstrap(now=now)

    def _bootstrap(self, *, now: str) -> ProviderModelBootstrapResult:
        catalog = ProviderModelCatalogService(self._repository)
        catalog.ensure_no_retired_defaults()
        registry = ProviderCredentialRegistry()
        connection_service = ProviderConnectionService(
            registry=registry,
            dotenv_store=DotenvCredentialStore(
                PROJECT_ROOT,
                allowed_fields={
                    field
                    for provider_id in registry.provider_ids
                    for binding in registry.get(provider_id).bindings.values()
                    for field in (
                        binding.dotenv_field,
                        binding.endpoint_dotenv_field,
                    )
                    if field is not None
                },
            ),
            metadata_repository=self._repository,
            settings_loader=lambda: self._settings,
        )
        connection_service.synchronize_metadata(updated_at=now)
        catalog.reconcile_retired_models(now=now)
        seeded_providers: list[str] = []
        for provider_id in (
            "siliconflow",
            "volcengine_ark",
            "tianpuyue",
            "openrouter",
            "minimax",
            "teamorouter",
            "fake",
        ):
            had_models = bool(self._repository.list_models(provider_id=provider_id))
            catalog.reconcile_trusted_models(provider_id, now=now)
            if not had_models:
                seeded_providers.append(provider_id)

        existing = catalog.get_default_records()
        candidates = {
            key: model_ref
            for key, model_ref in self._recognized_defaults(catalog).items()
            if key not in existing
        }
        if candidates:
            catalog.set_defaults(candidates, now=now)
        return ProviderModelBootstrapResult(
            seeded_providers=tuple(seeded_providers),
            seeded_defaults=tuple(candidates),
        )

    def _recognized_defaults(self, catalog: ProviderModelCatalogService) -> dict[str, str]:
        configured = {
            "agent": self._settings.llm_front_desk_model,
            "text": self._settings.llm_team_model,
            "image": self._settings.image_generation_model,
            "video": self._settings.video_generation_model,
            "audio": self._settings.bgm_model,
        }
        if self._settings.agent_runtime_mode == "fake":
            configured.update(agent="fake:deterministic-text", text="fake:deterministic-text")
        if self._settings.media_mode == "mock":
            configured.update(
                image="fake:deterministic-image",
                video="fake:deterministic-video",
                audio="fake:deterministic-audio",
            )
        recognized: dict[str, str] = {}
        for key, value in configured.items():
            if not value or not value.strip():
                continue
            identifier = value.strip()
            models = catalog.list_models(purpose=key)
            matches = tuple(model for model in models if model.model_ref == identifier)
            if not matches:
                if key == "audio":
                    models = tuple(
                        model
                        for model in models
                        if model.provider_id == self._settings.bgm_provider
                    )
                matches = tuple(model for model in models if model.provider_model_id == identifier)
            if not matches and key == "audio":
                # Legacy BGM settings use the catalog's human-readable display name.
                matches = tuple(model for model in models if model.display_name == identifier)
            if len(matches) == 1:
                recognized[key] = matches[0].model_ref
        return recognized
