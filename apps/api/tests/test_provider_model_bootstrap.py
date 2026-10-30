"""Installation defaults honor exact configured identities without provider calls."""

from dataclasses import replace
import socket

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import insert

from app.api.dependencies import get_provider_model_catalog_service
from app.api.v1.endpoints import providers
from app.core.config import Settings
from app.persistence.database import create_v2_database
from app.persistence.models import Base, ModelDefaultRow
from app.persistence.provider_model_repository import ProviderModelRepository
from app.services.provider_model_bootstrap import ProviderModelBootstrapService
from app.services.provider_model_catalog import ProviderModelCatalogService


NOW = "2026-10-26T00:00:00+00:00"
GLM = "volcengine_ark:glm-5-2-260617"
PRO = "volcengine_ark:doubao-seed-2-1-pro-260628"
IMAGE = "volcengine_ark:doubao-seedream-5-0-pro-260628"
VIDEO = "volcengine_ark:doubao-seedance-2-5-260628"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Model bootstrap must not contact a provider")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)


@pytest.fixture
def repository(tmp_path):
    (tmp_path / "v2").mkdir()
    database = create_v2_database(tmp_path)
    Base.metadata.create_all(database.engine)
    yield ProviderModelRepository(database)
    database.dispose()


@pytest.fixture
def settings():
    return Settings(
        agent_runtime_mode="real",
        media_mode="real",
        llm_front_desk_model="",
        llm_team_model="",
        image_generation_model="",
        video_generation_model="",
        bgm_model=None,
        llm_api_key="test-placeholder",
        llm_base_url="https://ark.cn-beijing.volces.com/api/v3",
        image_generation_api_key="test-placeholder",
        image_generation_endpoint="https://ark.cn-beijing.volces.com/api/v3/images/generations",
        video_generation_api_key="test-placeholder",
        video_generation_endpoint="https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        bgm_api_key="test-placeholder",
    )


def bootstrap(repository, settings):
    return ProviderModelBootstrapService(settings, repository).bootstrap(now=NOW)


def defaults_client(repository):
    app = FastAPI()
    app.include_router(providers.router, prefix="/api/v1")
    catalog = ProviderModelCatalogService(repository)
    app.dependency_overrides[get_provider_model_catalog_service] = lambda: catalog
    app.dependency_overrides[providers._ensure_local_access] = lambda: None
    return TestClient(app)


def add_model(repository, provider_id, model_id, *, capability="image", display_name=None):
    repository.upsert_models(
        provider_id=provider_id,
        models=(
            {
                "model_ref": f"{provider_id}:{model_id}",
                "provider_model_id": model_id,
                "display_name": display_name or model_id,
                "capability": capability,
                "capability_metadata": {},
                "source": "configured",
                "availability": "available",
                "unavailable_reason": None,
            },
        ),
        updated_at=NOW,
    )


def test_configured_models_are_observed_through_defaults_api(repository, settings):
    configured = replace(
        settings,
        llm_front_desk_model="glm-5-2-260617",
        llm_team_model=PRO,
        image_generation_model=IMAGE,
        video_generation_model="doubao-seedance-2-5-260628",
        bgm_model="TemPolor i3.5",
        # Having another provider's key must not replace the configured text model.
        siliconflow_api_key="another-test-placeholder",
    )
    bootstrap(repository, configured)
    with defaults_client(repository) as client:
        response = client.get("/api/v1/model-defaults")
    assert response.status_code == 200
    assert response.json()["defaults"] == {
        "agent": GLM,
        "text": PRO,
        "image": IMAGE,
        "video": VIDEO,
        "audio": "tianpuyue:TemPolor-i3.5",
    }


def test_initial_settings_models_match_available_defaults_api(repository, settings):
    initial = Settings()
    fields = {
        "agent": "llm_front_desk_model",
        "text": "llm_team_model",
        "image": "image_generation_model",
        "video": "video_generation_model",
    }
    bootstrap(
        repository,
        replace(settings, **{field: getattr(initial, field) for field in fields.values()}),
    )
    with defaults_client(repository) as client:
        response = client.get("/api/v1/model-defaults")
    assert response.status_code == 200
    defaults = response.json()["defaults"]
    catalog = ProviderModelCatalogService(repository)
    for key, field in fields.items():
        model = catalog.get_model(defaults[key])
        assert model.availability == "available"
        assert getattr(initial, field) in {model.model_ref, model.provider_model_id}


@pytest.mark.parametrize("identifier", ["", "   ", "unknown-model", "doubao-seedance-2-0-fast"])
def test_missing_unknown_or_incomplete_identifiers_do_not_seed_defaults(
    repository, settings, identifier
):
    configured = replace(
        settings,
        llm_front_desk_model=identifier,
        llm_team_model=identifier,
        image_generation_model=identifier,
        video_generation_model=identifier,
        bgm_model=identifier,
    )
    result = bootstrap(repository, configured)
    assert result.seeded_defaults == ()
    assert repository.get_defaults() == {}


def test_unavailable_or_wrong_purpose_models_are_not_seeded(repository, settings):
    configured = replace(
        settings,
        llm_front_desk_model="doubao-seed-2-0-mini-260428",  # Retired, not an upgrade request.
        llm_team_model=IMAGE,
        image_generation_model=IMAGE,
        image_generation_api_key=None,
        video_generation_model=IMAGE,
    )
    bootstrap(repository, configured)
    assert repository.get_defaults() == {}


def test_saved_api_choices_and_revisions_survive_restart(repository, settings):
    bootstrap(repository, replace(settings, llm_front_desk_model=PRO, llm_team_model=PRO))
    with defaults_client(repository) as client:
        response = client.patch(
            "/api/v1/model-defaults",
            json={"defaults": {"agent": GLM, "text": GLM}, "thinking_modes": {"text": "disabled"}},
        )
        assert response.status_code == 200
        saved = response.json()
        bootstrap(repository, replace(settings, llm_front_desk_model=PRO, llm_team_model=PRO))
        assert client.get("/api/v1/model-defaults").json() == saved


def test_legacy_retired_choice_is_preserved_without_automatic_upgrade(repository, settings):
    bootstrap(repository, settings)
    retired = "volcengine_ark:doubao-seed-2-0-mini-260428"
    # Current API refuses a new retired choice. This models an existing installation.
    with repository._database.engine.begin() as connection:
        connection.execute(
            insert(ModelDefaultRow).values(
                default_key="agent",
                model_ref=retired,
                revision=7,
                updated_at=NOW,
                selection_mode="explicit",
                thinking_mode="disabled",
            )
        )
    original = repository.get_defaults()["agent"]
    bootstrap(repository, replace(settings, llm_front_desk_model=PRO))
    assert repository.get_defaults()["agent"] == original
    assert ProviderModelCatalogService(repository).get_model(retired).availability != "available"


def test_ambiguous_native_id_requires_qualified_reference(repository, settings):
    bootstrap(repository, settings)
    add_model(repository, "fake", "custom-image-current")
    add_model(repository, "volcengine_ark", "custom-image-current")
    bootstrap(repository, replace(settings, image_generation_model="custom-image-current"))
    assert "image" not in repository.get_defaults()
    bootstrap(
        repository,
        replace(settings, image_generation_model="volcengine_ark:custom-image-current"),
    )
    assert repository.get_defaults()["image"].model_ref == "volcengine_ark:custom-image-current"


def test_audio_display_name_is_scoped_to_configured_provider(repository, settings):
    bootstrap(repository, settings)
    add_model(repository, "fake", "other-audio", capability="audio", display_name="TemPolor i3")
    bootstrap(repository, replace(settings, bgm_provider="tianpuyue", bgm_model="TemPolor i3"))
    assert repository.get_defaults()["audio"].model_ref == "tianpuyue:TemPolor-i3"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("TemPolor-i3", "tianpuyue:TemPolor-i3"),
        ("fake:TemPolor-i3", "fake:TemPolor-i3"),
    ],
)
def test_audio_native_id_uses_provider_unless_explicitly_qualified(
    repository, settings, configured, expected
):
    bootstrap(repository, settings)
    add_model(repository, "fake", "TemPolor-i3", capability="audio")
    bootstrap(repository, replace(settings, bgm_provider="tianpuyue", bgm_model=configured))
    assert repository.get_defaults()["audio"].model_ref == expected


def test_audio_native_id_does_not_fall_back_to_another_provider(repository, settings):
    bootstrap(repository, settings)
    add_model(repository, "fake", "unrelated-audio", capability="audio")
    bootstrap(repository, replace(settings, bgm_provider="tianpuyue", bgm_model="unrelated-audio"))
    assert "audio" not in repository.get_defaults()


def test_fake_and_mock_modes_keep_deterministic_defaults(repository, settings):
    bootstrap(repository, replace(settings, agent_runtime_mode="fake", media_mode="mock"))
    assert {key: value.model_ref for key, value in repository.get_defaults().items()} == {
        "agent": "fake:deterministic-text",
        "text": "fake:deterministic-text",
        "image": "fake:deterministic-image",
        "video": "fake:deterministic-video",
        "audio": "fake:deterministic-audio",
    }
