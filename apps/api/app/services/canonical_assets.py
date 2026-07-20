from collections.abc import Mapping
from pathlib import Path
from typing import Any


MEDIA_TYPES = {"image", "video", "audio"}

IMAGE_SEMANTICS = {
    "character_main",
    "character_face_id",
    "character_three_view",
    "character_concept",
    "scene_main",
    "scene_multi_view",
    "storyboard_image",
    "product_reference",
    "product_image",
    "style_reference",
}
VIDEO_SEMANTICS = {"storyboard_video", "final_video", "video_reference", "video_segment"}
AUDIO_SEMANTICS = {"bgm", "bgm_reference", "audio"}

DEFAULT_ENTITY_TYPE = "uploaded_reference"

DEFAULT_SEMANTIC_BY_MEDIA_ENTITY = {
    ("image", "product"): "product_reference",
    ("image", "character"): "character_main",
    ("image", "scene"): "scene_main",
    ("image", "style_reference"): "style_reference",
    ("image", "storyboard_shot"): "storyboard_image",
    ("image", "uploaded_reference"): "uploaded_reference",
    ("video", "storyboard_shot"): "storyboard_video",
    ("video", "video_clip"): "storyboard_video",
    ("video", "uploaded_reference"): "uploaded_reference",
    ("audio", "bgm"): "bgm",
    ("audio", "uploaded_reference"): "uploaded_reference",
}

DEFAULT_ROLE_BY_ENTITY_TYPE = {
    "product": "product_reference",
    "character": "character_reference",
    "scene": "scene_reference",
    "style_reference": "style_reference",
    "storyboard_shot": "storyboard_reference",
    "video_clip": "video_reference",
    "bgm": "bgm_reference",
    "uploaded_reference": "general_reference",
}

NODE_MEDIA_CAPABILITIES = {
    "product-generation": {"image"},
    "character-generation": {"image"},
    "scene-generation": {"image"},
    "storyboard": {"image"},
    "storyboard-video-generation": {"image", "video"},
    "bgm": {"audio"},
    "final-composition": {"image", "video", "audio"},
}


def canonical_media_type(asset: Mapping[str, Any]) -> str:
    for key in ("media_type", "asset_type", "type", "kind"):
        media_type = _media_type_from_value(asset.get(key))
        if media_type:
            return media_type
    media_type = _media_type_from_mime_type(asset.get("mime_type"))
    if media_type:
        return media_type
    for key in ("filename", "local_path", "public_url", "uri", "url"):
        media_type = _media_type_from_path(asset.get(key))
        if media_type:
            return media_type
    return ""


def canonical_entity_type(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("entity_type") or "").strip()
    if value:
        return value
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        value = str(metadata.get("entity_type") or metadata.get("semantic_entity_type") or "")
        if value.strip():
            return value.strip()
    return DEFAULT_ENTITY_TYPE


def canonical_semantic_type(
    asset: Mapping[str, Any],
    *,
    entity_type: str | None = None,
    media_type: str | None = None,
) -> str:
    resolved_media_type = media_type or canonical_media_type(asset)
    resolved_entity_type = entity_type or canonical_entity_type(asset)
    explicit = str(asset.get("semantic_type") or "").strip()
    if explicit and semantic_type_matches_media_entity(
        explicit,
        media_type=resolved_media_type,
        entity_type=resolved_entity_type,
    ):
        return explicit
    return (
        DEFAULT_SEMANTIC_BY_MEDIA_ENTITY.get((resolved_media_type, resolved_entity_type))
        or DEFAULT_SEMANTIC_BY_MEDIA_ENTITY.get((resolved_media_type, DEFAULT_ENTITY_TYPE))
        or DEFAULT_ENTITY_TYPE
    )


def canonical_reference_role(
    payload: Mapping[str, Any],
    *,
    entity_type: str | None = None,
    media_type: str | None = None,
) -> str:
    explicit = str(payload.get("role") or "").strip()
    if explicit:
        return explicit
    resolved_entity_type = entity_type or canonical_entity_type(payload)
    if resolved_entity_type == DEFAULT_ENTITY_TYPE:
        resolved_media_type = media_type or canonical_media_type(payload)
        if resolved_media_type == "video":
            return "video_reference"
        if resolved_media_type == "audio":
            return "bgm_reference"
    return DEFAULT_ROLE_BY_ENTITY_TYPE.get(resolved_entity_type, "general_reference")


def normalize_canonical_asset(
    asset: Mapping[str, Any],
    *,
    source_node_id: str | None = None,
    role: str | None = None,
    entity_type: str | None = None,
) -> dict[str, Any]:
    normalized = dict(asset)
    media_type = canonical_media_type(normalized)
    resolved_entity_type = entity_type or canonical_entity_type(normalized)
    normalized["media_type"] = media_type
    normalized["asset_type"] = media_type
    normalized["type"] = media_type
    normalized["kind"] = media_type
    normalized["entity_type"] = resolved_entity_type
    normalized["semantic_type"] = canonical_semantic_type(
        normalized,
        entity_type=resolved_entity_type,
        media_type=media_type,
    )
    normalized["role"] = role or canonical_reference_role(
        normalized,
        entity_type=resolved_entity_type,
        media_type=media_type,
    )
    normalized["use_as_prompt"] = bool(normalized.get("use_as_prompt", True))
    if source_node_id:
        normalized["source_node_id"] = source_node_id
        normalized.setdefault("source", source_node_id)
    metadata = normalized.get("metadata")
    if not isinstance(metadata, dict):
        normalized["metadata"] = {}
    return normalized


def node_accepts_media_type(node_id_or_type: str, media_type: str) -> bool:
    return media_type in NODE_MEDIA_CAPABILITIES.get(node_id_or_type, set())


def semantic_type_matches_media_entity(
    semantic_type: str,
    *,
    media_type: str,
    entity_type: str,
) -> bool:
    if semantic_type == "uploaded_reference":
        return media_type in MEDIA_TYPES
    if _media_type_from_value(semantic_type) != media_type:
        return False
    default = DEFAULT_SEMANTIC_BY_MEDIA_ENTITY.get((media_type, entity_type))
    if semantic_type == default:
        return True
    if entity_type == "product" and semantic_type in {"product_reference", "product_image"}:
        return media_type == "image"
    if entity_type == "character" and semantic_type in IMAGE_SEMANTICS:
        return semantic_type.startswith("character_")
    if entity_type == "scene" and semantic_type in IMAGE_SEMANTICS:
        return semantic_type.startswith("scene_")
    if entity_type == "storyboard_shot":
        return semantic_type in {"storyboard_image", "storyboard_video"}
    if entity_type == "video_clip":
        return semantic_type in {"storyboard_video", "final_video"}
    if entity_type == "style_reference":
        return semantic_type == "style_reference"
    if entity_type == "bgm":
        return semantic_type == "bgm"
    return False


def _media_type_from_value(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    if text in MEDIA_TYPES:
        return text
    if text in IMAGE_SEMANTICS or text.endswith("_image") or "image" in text:
        return "image"
    if text in VIDEO_SEMANTICS or text.endswith("_video") or "video" in text:
        return "video"
    if text in AUDIO_SEMANTICS or text.startswith("audio") or "bgm" in text:
        return "audio"
    return ""


def _media_type_from_mime_type(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text.startswith("image/"):
        return "image"
    if text.startswith("video/"):
        return "video"
    if text.startswith("audio/"):
        return "audio"
    return ""


def _media_type_from_path(value: Any) -> str:
    suffix = Path(str(value or "").split("?", 1)[0]).suffix.casefold()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".m4v", ".avi"}:
        return "video"
    if suffix in {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}:
        return "audio"
    return ""
