from __future__ import annotations

from pathlib import Path

from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRepository
from app.persistence.schema import upgrade_v2_schema
from app.services.provider_credentials import ProviderCredentialRegistry
from app.services.provider_model_catalog import ProviderModelCatalogService


def test_cpa_gpt_image_2_syncs_as_an_image_model_using_the_cpa_binding(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    try:
        upgrade_v2_schema(database)
        repository = ProviderModelRepository(database)
        catalog = ProviderModelCatalogService(repository)

        catalog.reconcile_trusted_models("cliproxyapi", now="2026-08-29T00:00:00+00:00")

        model = repository.get_model("cliproxyapi:gpt-image-2")
        binding = ProviderCredentialRegistry().get("cliproxyapi").binding_for_capability("image")
    finally:
        database.dispose()

    assert model.capability == "image"
    assert model.capability_metadata["provider_protocol"] == "openai_image"
    assert binding.consumer == "llm"
    assert binding.dotenv_field == "LLM_API_KEY"
