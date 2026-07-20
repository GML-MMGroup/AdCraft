from app.schemas.asset_library import ProviderCapability


_CAPABILITIES: dict[str, ProviderCapability] = {
    "volcengine_image": ProviderCapability(
        provider="volcengine_image",
        media_type="image",
        supports_image_reference=True,
        supports_multi_image_reference=True,
        supports_video_reference=False,
        supports_audio_reference=False,
        supports_identity_lock=False,
        supports_style_reference=True,
        max_reference_assets=4,
        supported_reference_semantic_types=[
            "character_main",
            "character_face_id",
            "character_three_view",
            "product_reference",
            "product_image",
            "scene_main",
            "scene_multi_view",
            "style_reference",
            "storyboard_image",
        ],
        node_types=[
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
        ],
    ),
    "volcengine_video": ProviderCapability(
        provider="volcengine_video",
        media_type="video",
        supports_image_reference=True,
        supports_video_reference=True,
        supports_audio_reference=False,
        supports_identity_lock=False,
        supports_style_reference=False,
        max_reference_assets=2,
        supported_reference_semantic_types=[
            "storyboard_image",
            "storyboard_video",
            "character_main",
            "scene_main",
        ],
        node_types=["storyboard-video-generation"],
    ),
    "volcengine_audio": ProviderCapability(
        provider="volcengine_audio",
        media_type="audio",
        supports_audio_reference=True,
        supports_image_reference=False,
        supports_video_reference=False,
        supports_identity_lock=False,
        supports_style_reference=False,
        max_reference_assets=1,
        supported_reference_semantic_types=["bgm"],
        node_types=["bgm"],
    ),
    "mock_image": ProviderCapability(
        provider="mock_image",
        media_type="image",
        supports_image_reference=True,
        supports_multi_image_reference=True,
        supports_video_reference=False,
        supports_audio_reference=False,
        supports_identity_lock=False,
        supports_style_reference=True,
        max_reference_assets=4,
        supported_reference_semantic_types=[
            "character_main",
            "character_face_id",
            "character_three_view",
            "product_reference",
            "product_image",
            "scene_main",
            "scene_multi_view",
            "style_reference",
            "storyboard_image",
        ],
        node_types=[
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
        ],
    ),
    "mock_video": ProviderCapability(
        provider="mock_video",
        media_type="video",
        supports_image_reference=True,
        supports_video_reference=True,
        supports_audio_reference=False,
        supports_identity_lock=False,
        supports_style_reference=False,
        max_reference_assets=2,
        supported_reference_semantic_types=[
            "storyboard_image",
            "storyboard_video",
            "character_main",
            "scene_main",
        ],
        node_types=["storyboard-video-generation"],
    ),
    "mock_bgm": ProviderCapability(
        provider="mock_bgm",
        media_type="audio",
        supports_audio_reference=True,
        supports_image_reference=False,
        supports_video_reference=False,
        supports_identity_lock=False,
        supports_style_reference=False,
        max_reference_assets=1,
        supported_reference_semantic_types=["bgm"],
        node_types=["bgm"],
    ),
}


def get_provider_capability(provider: str, node_type: str | None = None) -> ProviderCapability:
    capability = _CAPABILITIES.get(provider)
    if capability is None:
        return ProviderCapability(
            provider=provider,
            media_type=_media_type_for_node(node_type or ""),
            max_reference_assets=0,
            node_types=[node_type] if node_type else [],
        )
    if node_type and capability.node_types and node_type not in capability.node_types:
        return capability.model_copy(update={"node_types": [*capability.node_types, node_type]})
    return capability


def list_provider_capabilities() -> list[ProviderCapability]:
    return list(_CAPABILITIES.values())


def provider_for_node(node_type: str, *, media_mode: str) -> str:
    if node_type in {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
    }:
        return "mock_image" if media_mode == "mock" else "volcengine_image"
    if node_type == "storyboard-video-generation":
        return "mock_video" if media_mode == "mock" else "volcengine_video"
    if node_type == "bgm":
        return "mock_bgm" if media_mode == "mock" else "volcengine_audio"
    return media_mode or "unknown"


def _media_type_for_node(node_type: str) -> str:
    if node_type in {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
    }:
        return "image"
    if node_type == "storyboard-video-generation":
        return "video"
    if node_type == "bgm":
        return "audio"
    return ""
