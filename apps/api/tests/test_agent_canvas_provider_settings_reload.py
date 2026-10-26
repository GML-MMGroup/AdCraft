"""Background recovery preserves credentials saved after application startup."""

from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import main
from app.core.config import Settings
from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRepository
from app.persistence.schema import upgrade_v2_schema
from app.services.provider_credentials import (
    DotenvCredentialStore,
    ProviderConnectionService,
    ProviderCredentialRegistry,
    RuntimeSettingsReloader,
)
from app.services.provider_model_bootstrap import ProviderModelBootstrapService
from app.services.provider_model_catalog import ProviderModelCatalogService


IMAGE_MODEL = "volcengine_ark:doubao-seedream-5-0-pro-260628"
VIDEO_MODEL = "volcengine_ark:doubao-seedance-2-0-fast-260128"
RECOVERIES = (
    main._recover_agent_canvas_chat_turns,
    main._recover_agent_canvas_executions,
    main._recover_agent_canvas_continuations,
    main._recover_agent_canvas_prompt_preparations,
    main._recover_agent_canvas_guided_media_resumes,
    main._recover_agent_canvas_provider_tasks,
    main._recover_agent_canvas_editing_exports,
)
MANAGED_FIELDS = {
    "image_generation_api_key": "IMAGE_GENERATION_API_KEY",
    "video_generation_api_key": "VIDEO_GENERATION_API_KEY",
    "image_generation_endpoint": "IMAGE_GENERATION_ENDPOINT",
    "video_generation_endpoint": "VIDEO_GENERATION_ENDPOINT",
}


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    with patch.dict(os.environ):
        yield from _isolated_credentials(tmp_path, monkeypatch)


def _isolated_credentials(tmp_path, monkeypatch):
    # Every file and credential involved in this test is synthetic and isolated.
    for field in MANAGED_FIELDS.values():
        monkeypatch.delenv(field, raising=False)
    monkeypatch.setattr("app.services.provider_model_bootstrap.PROJECT_ROOT", tmp_path)
    startup = Settings(
        media_data_dir=tmp_path / "media",
        agent_runtime_mode="fake",
        media_mode="real",
        agent_canvas_prompt_preparation_concurrency=1,
    )
    (startup.media_data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(startup.media_data_dir)
    with patch.dict(os.environ):
        os.environ.pop("DATABASE_URL", None)
        upgrade_v2_schema(database)
    repository = ProviderModelRepository(database)
    ProviderModelBootstrapService(startup, repository).bootstrap(
        now=datetime.now(timezone.utc).isoformat()
    )

    def current():
        return replace(
            startup,
            **{field: os.environ.get(env) for field, env in MANAGED_FIELDS.items()},
        )

    service = ProviderConnectionService(
        registry=ProviderCredentialRegistry(),
        dotenv_store=DotenvCredentialStore(tmp_path, allowed_fields=set(MANAGED_FIELDS.values())),
        metadata_repository=repository,
        settings_loader=current,
        reloader=RuntimeSettingsReloader(settings_loader=current, cache_clear=lambda: None),
    )
    service.update(
        "volcengine_ark",
        api_keys={"image": "synthetic-image-first", "video": "synthetic-video-first"},
        base_urls={
            "image": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
            "video": "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        },
    )
    monkeypatch.setattr(main, "get_settings", current)
    try:
        yield startup, current, service, repository
    finally:
        database.dispose()


@pytest.mark.parametrize("recover", RECOVERIES, ids=lambda recover: recover.__name__)
def test_recovery_does_not_overwrite_saved_provider_metadata(credentials, recover):
    startup, _, _, repository = credentials
    saved = repository.get_connection("volcengine_ark")
    catalog = ProviderModelCatalogService(repository)
    assert catalog.get_model(IMAGE_MODEL).availability == "available"

    # Use the actual runtime factory and SQLite, with no active work/provider requests.
    recover(startup)

    assert repository.get_connection("volcengine_ark") == saved
    assert catalog.get_model(IMAGE_MODEL).availability == "available"
    assert catalog.get_model(VIDEO_MODEL).availability == "available"


def test_production_factory_reloads_saved_rotated_and_cleared_credentials(credentials, monkeypatch):
    startup, current, service, _ = credentials
    captured = {}

    def lifespan(settings, *, runtime_factory):
        captured["factory"] = runtime_factory
        return None

    monkeypatch.setattr(main, "_lifespan", lifespan)
    main.create_app()
    factory = captured["factory"]
    assert factory is not None
    builds = []

    def build(settings, *, bootstrap_model_policy=True):
        builds.append((settings, bootstrap_model_policy))
        return object()

    monkeypatch.setattr(main, "create_agent_canvas_runtime", build)
    factory(startup)
    service.update(
        "volcengine_ark",
        api_keys={"image": "synthetic-image-rotated", "video": "synthetic-video-rotated"},
        base_urls={"image": "https://ark.cn-beijing.volces.com/api/v3"},
    )
    rotated = current()
    factory(startup)
    service.update("volcengine_ark", api_keys={}, clear_capabilities=("image", "video"))
    cleared = current()
    factory(startup)

    assert len(builds) == 3
    assert builds[0][0].image_generation_api_key == "synthetic-image-first"
    assert builds[1] == (rotated, False)
    assert builds[2] == (cleared, False)
    assert builds[1][0].image_generation_endpoint == "https://ark.cn-beijing.volces.com/api/v3"
    assert builds[2][0].image_generation_api_key is None
    assert builds[2][0].video_generation_api_key is None
    assert all(settings.media_data_dir == startup.media_data_dir for settings, _ in builds)
    assert all(not bootstrap for _, bootstrap in builds)


def test_explicit_application_settings_keep_their_background_factory_contract(monkeypatch):
    explicit = Settings(media_data_dir=Path("synthetic-explicit-data"))
    captures = []

    def lifespan(settings, *, runtime_factory):
        captures.append((settings, runtime_factory))
        return None

    monkeypatch.setattr(main, "_lifespan", lifespan)
    main.create_app(settings=explicit)

    def custom_factory(settings):
        return object()

    main.create_app(settings=explicit, agent_canvas_runtime_factory=custom_factory)

    assert captures == [(explicit, None), (explicit, custom_factory)]
