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
_ARK_MINI_TEXT_MODEL_REF = "volcengine_ark:doubao-seed-2-0-mini-260428"
_ARK_PRO_TEXT_MODEL_REF = "volcengine_ark:doubao-seed-2-1-pro-260628"


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
        catalog = ProviderModelCatalogService(self._repository)
        seeded_providers: list[str] = []
        for provider_id in (
            "siliconflow",
            "volcengine_ark",
            "tianpuyue",
            "openai",
            "minimax",
            "fake",
        ):
            had_models = bool(self._repository.list_models(provider_id=provider_id))
            catalog.reconcile_trusted_models(provider_id, now=now)
            if not had_models:
                seeded_providers.append(provider_id)

        existing = catalog.get_default_records()
        candidates = {
            key: model_ref
            for key, model_ref in self._recognized_defaults().items()
            if key not in existing
        }
        valid_candidates: dict[str, str] = {}
        for key, model_ref in candidates.items():
            try:
                model = self._repository.get_model(model_ref)
            except ValueError:
                continue
            if model.availability != "available":
                continue
            valid_candidates[key] = model_ref
        migrated_defaults: dict[str, str] = {}
        try:
            ark_pro = catalog.get_model(_ARK_PRO_TEXT_MODEL_REF)
        except ValueError:
            ark_pro = None
        if ark_pro is not None and ark_pro.availability == "available":
            migrated_defaults = {
                key: _ARK_PRO_TEXT_MODEL_REF
                for key in ("agent", "text")
                if existing.get(key) is not None
                and existing[key].model_ref == _ARK_MINI_TEXT_MODEL_REF
            }
        default_updates = {**migrated_defaults, **valid_candidates}
        if default_updates:
            catalog.set_defaults(default_updates, now=now)
        return ProviderModelBootstrapResult(
            seeded_providers=tuple(seeded_providers),
            seeded_defaults=tuple(valid_candidates),
        )

    def _recognized_defaults(self) -> dict[str, str]:
        text_ref = "fake:deterministic-text"
        if self._settings.agent_runtime_mode != "fake":
            text_ref = (
                "siliconflow:zai-org/GLM-5.2"
                if self._settings.siliconflow_api_key
                else _ARK_PRO_TEXT_MODEL_REF
            )
        if self._settings.media_mode == "mock":
            return {
                "agent": text_ref,
                "text": text_ref,
                "image": "fake:deterministic-image",
                "video": "fake:deterministic-video",
                "audio": "fake:deterministic-audio",
            }
        return {
            "agent": text_ref,
            "text": text_ref,
            "image": "volcengine_ark:doubao-seedream-5-0-lite-260128",
            "video": "volcengine_ark:doubao-seedance-2-0-fast-260128",
            "audio": "tianpuyue:TemPolor-i3",
        }
