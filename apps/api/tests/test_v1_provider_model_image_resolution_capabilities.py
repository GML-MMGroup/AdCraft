from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.providers import _adapter_response_fields
from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.provider_models import (
    ImageResolutionCapabilitiesV1,
    ImageResolutionPixelBoundsV1,
    ProviderModelSummaryV2,
)
from app.services.provider_model_catalog import (
    GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO,
    ProviderModelCatalogService,
    _TRUSTED_MANIFESTS,
)


def _image_manifest_profiles() -> dict[str, dict]:
    return {
        manifest.model_ref: manifest.capability_metadata["adapter_profile"]
        for manifest in _TRUSTED_MANIFESTS
        if manifest.capability == "image" and "adapter_profile" in manifest.capability_metadata
    }


def test_seedream_models_declare_size_mode_with_pixel_bounds() -> None:
    profiles = _image_manifest_profiles()
    seedream_refs = [
        model_ref
        for model_ref in profiles
        if model_ref.startswith("volcengine_ark:doubao-seedream")
    ]
    assert len(seedream_refs) == 4
    for model_ref in seedream_refs:
        capabilities = profiles[model_ref]["image_resolution_capabilities"]
        assert capabilities["parameter_modes"] == ["size"]
        assert capabilities["size_options"] == [
            "2048x2048",
            "2560x1440",
            "1440x2560",
            "2304x1728",
            "1728x2304",
        ]
        assert capabilities["sizes_by_aspect_ratio"] == dict(GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO)
        assert capabilities["pixel_bounds"] == {"minimum": 512, "maximum": 4096}
        assert capabilities["default_parameters"] == {}


def test_openrouter_gpt_image_2_declares_resolution_with_aspect_ratio() -> None:
    profile = _image_manifest_profiles()["openrouter:openai/gpt-image-2"]
    capabilities = profile["image_resolution_capabilities"]
    assert capabilities["parameter_modes"] == ["resolution_with_aspect_ratio"]
    assert capabilities["resolution_options"] == ["1K", "2K", "4K"]
    assert capabilities["aspect_ratio_options"] == ["1:1", "16:9", "9:16", "4:3", "3:4"]
    assert capabilities["size_options"] == []
    descriptor_names = [descriptor["name"] for descriptor in profile["parameter_matrix"]["descriptors"]]
    assert "size" not in descriptor_names
    assert {"resolution", "aspect_ratio"}.issubset(set(descriptor_names))


def test_adapter_response_fields_passes_resolution_capabilities_through() -> None:
    metadata = {
        "adapter_profile": {
            "adapter_id": "ark-image-native",
            "image_resolution_capabilities": {
                "parameter_modes": ["size"],
                "size_options": ["2048x2048"],
                "pixel_bounds": {"minimum": 512, "maximum": 4096},
            },
        },
    }
    fields = _adapter_response_fields(metadata)
    assert fields["image_resolution_capabilities"] == {
        "parameter_modes": ["size"],
        "size_options": ["2048x2048"],
        "pixel_bounds": {"minimum": 512, "maximum": 4096},
    }


def test_size_mode_requires_size_options() -> None:
    with pytest.raises(ValidationError, match="image_resolution_size_options_required"):
        ImageResolutionCapabilitiesV1(parameter_modes=["size"])


def test_pair_mode_requires_resolution_and_aspect_ratio_options() -> None:
    with pytest.raises(ValidationError, match="image_resolution_pair_options_required"):
        ImageResolutionCapabilitiesV1(
            parameter_modes=["resolution_with_aspect_ratio"],
            resolution_options=["1K"],
        )


def test_size_mapping_values_must_exist_in_size_options() -> None:
    with pytest.raises(ValidationError, match="image_resolution_size_mapping_unknown"):
        ImageResolutionCapabilitiesV1(
            parameter_modes=["size"],
            size_options=["2048x2048"],
            sizes_by_aspect_ratio={"16:9": "2560x1440"},
        )


def test_pixel_bounds_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError, match="image_resolution_pixel_bounds_invalid"):
        ImageResolutionPixelBoundsV1(minimum=4096, maximum=512)


def test_image_model_catalog_response_carries_resolution_capabilities(
    v2_media_data_dir,
) -> None:
    database = create_v2_database(v2_media_data_dir)
    try:
        upgrade_v2_schema(database)
        service = ProviderModelCatalogService(ProviderModelRepository(database))
        service.sync("volcengine_ark", now="2026-09-16T00:00:00Z")
        service.sync("openrouter", now="2026-09-16T00:00:00Z")
        items = service.list_models(capability="image", include_unavailable=True)
    finally:
        database.dispose()

    summaries = {
        model.model_ref: ProviderModelSummaryV2(
            model_ref=model.model_ref,
            provider_id=model.provider_id,
            provider_model_id=model.provider_model_id,
            display_name=model.display_name,
            capability=model.capability,
            capability_metadata=model.capability_metadata,
            availability=model.availability,
            unavailable_reason=model.unavailable_reason,
            catalog_revision=model.catalog_revision,
            **_adapter_response_fields(model.capability_metadata),
        )
        for model in items
    }

    seedream = summaries["volcengine_ark:doubao-seedream-4-5-251128"]
    assert seedream.image_resolution_capabilities is not None
    assert seedream.image_resolution_capabilities.parameter_modes == ("size",)
    assert seedream.image_resolution_capabilities.pixel_bounds is not None
    assert seedream.image_resolution_capabilities.pixel_bounds.minimum == 512
    assert "2560x1440" in seedream.image_resolution_capabilities.size_options

    gpt_image = summaries["openrouter:openai/gpt-image-2"]
    assert gpt_image.image_resolution_capabilities is not None
    assert gpt_image.image_resolution_capabilities.parameter_modes == (
        "resolution_with_aspect_ratio",
    )
    assert gpt_image.image_resolution_capabilities.resolution_options == ("1K", "2K", "4K")
    assert [descriptor.name for descriptor in gpt_image.parameter_descriptors] == [
        "quality",
        "background",
        "output_format",
        "output_compression",
        "resolution",
        "aspect_ratio",
    ]
