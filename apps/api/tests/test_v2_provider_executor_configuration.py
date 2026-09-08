import pytest

from app.core.config import Settings
from app.services.v2_provider_executor import V2ProviderExecutor
from app.tools.real_media_provider import RealMediaProvider


def test_v2_image_provider_does_not_require_unrelated_video_configuration(tmp_path) -> None:
    settings = Settings(
        media_mode="real",
        media_data_dir=tmp_path,
        image_generation_api_key="image-test-key",
        image_generation_endpoint="http://image-provider.test/v1/images/generations",
        image_generation_model="gpt-image-2",
        image_generation_size="1024x1024",
        skip_audio_agents=True,
    )

    provider = V2ProviderExecutor(settings=settings)._media_provider_for("image")

    assert isinstance(provider, RealMediaProvider)


def test_v2_gpt_image_uses_openai_image_payload_at_1024_square(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        media_mode="real",
        media_data_dir=tmp_path,
        image_generation_api_key="image-test-key",
        image_generation_endpoint="http://image-provider.test/v1/images/generations",
        image_generation_model="gpt-image-2",
        image_generation_size="1024x1024",
        skip_audio_agents=True,
    )
    provider = V2ProviderExecutor(settings=settings)._media_provider_for("image")
    submitted: dict[str, object] = {}
    monkeypatch.setattr(
        provider,
        "_submit_image_generation_request",
        lambda body: submitted.update(body) or {
            "data": [
                {
                    "b64_json": (
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4"
                        "z8DwHwAFgAI/ScL5jAAAAABJRU5ErkJggg=="
                    )
                }
            ]
        },
    )

    provider.generate_v2_canonical_image(
        {
            "prompt": "A clean studio product photograph.",
            "slot_type": "product_main_image",
            "slot_id": "product-1:image",
            "semantic_type": "product",
        },
        "workflow-1",
    )

    assert submitted == {
        "model": "gpt-image-2",
        "prompt": "A clean studio product photograph.",
        "size": "1024x1024",
    }


def test_v2_gpt_image_uses_multipart_edits_only_when_references_are_present(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        media_mode="real",
        media_data_dir=tmp_path,
        image_generation_api_key="image-test-key",
        image_generation_endpoint="http://image-provider.test/v1/images/generations",
        image_generation_model="gpt-image-2",
        image_generation_size="1024x1024",
        skip_audio_agents=True,
    )
    provider = V2ProviderExecutor(settings=settings)._media_provider_for("image")
    submitted: dict[str, object] = {}
    monkeypatch.setattr(
        provider,
        "_submit_openai_image_edit_request",
        lambda body, references: submitted.update({"body": body, "references": references}) or {
            "data": [
                {
                    "b64_json": (
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4"
                        "z8DwHwAFgAI/ScL5jAAAAABJRU5ErkJggg=="
                    )
                }
            ]
        },
        raising=False,
    )

    provider.generate_v2_canonical_image(
        {
            "prompt": "Preserve the supplied product identity in a multi-view sheet.",
            "slot_type": "product_multiview_image",
            "slot_id": "product-1:multi-view",
            "semantic_type": "product",
            "reference_assets": [
                {
                    "asset_id": "asset-main",
                    "provider_input_value": "data:image/png;base64,iVBORw0KGgo=",
                }
            ],
            "submitted_reference_asset_ids": ["asset-main"],
        },
        "workflow-1",
    )

    assert submitted == {
        "body": {
            "model": "gpt-image-2",
            "prompt": "Preserve the supplied product identity in a multi-view sheet.",
            "size": "1024x1024",
        },
        "references": [
            {
                "asset_id": "asset-main",
                "provider_input_value": "data:image/png;base64,iVBORw0KGgo=",
            }
        ],
    }
