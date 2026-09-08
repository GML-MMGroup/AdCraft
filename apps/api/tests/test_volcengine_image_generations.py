from __future__ import annotations

from app.tools import volcengine_image_generations


def test_openai_image_edit_serializer_preserves_required_reference_order() -> None:
    body, audit = volcengine_image_generations.serialize_openai_image_edit_request(
        model="gpt-image-2",
        canonical_prompt="Preserve the supplied product identity.",
        size="1024x1024",
        references=[
            {
                "asset_id": "asset-main",
                "provider_input_value": "data:image/png;base64,cG5n",
            },
            {
                "asset_id": "asset-detail",
                "provider_input_value": "https://assets.example.com/detail.png",
            },
        ],
        required_reference_asset_ids=["asset-main", "asset-detail"],
    )

    assert body == {
        "model": "gpt-image-2",
        "prompt": "Preserve the supplied product identity.",
        "size": "1024x1024",
    }
    assert audit.request_schema == "openai-image-edits"
    assert audit.delivered_reference_asset_ids == ["asset-main", "asset-detail"]
    assert audit.serialized_reference_asset_ids == ["asset-main", "asset-detail"]
    assert audit.provider_request_field == "image"
    assert audit.provider_request_reference_count == 2
