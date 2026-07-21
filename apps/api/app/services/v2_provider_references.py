from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import WorkflowAssetVersionV2, WorkflowSlotV2
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_relative_path
from app.services.v2_provider_reference_input_delivery import (
    is_provider_compatible_public_url,
)


REFERENCE_POLICY_BEST_EFFORT = "best_effort"


@dataclass(frozen=True)
class V2ReferenceAdaptation:
    provider_payload: dict[str, Any]
    requested_reference_asset_ids: list[str]
    submitted_reference_asset_ids: list[str]
    dropped_reference_asset_ids: list[str]
    reference_usage_warnings: list[dict[str, Any]]
    provider_capability_snapshot: dict[str, Any]

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "reference_policy": REFERENCE_POLICY_BEST_EFFORT,
            "requested_reference_asset_ids": list(self.requested_reference_asset_ids),
            "submitted_reference_asset_ids": list(self.submitted_reference_asset_ids),
            "dropped_reference_asset_ids": list(self.dropped_reference_asset_ids),
            "reference_usage_warnings": list(self.reference_usage_warnings),
            "provider_capability_snapshot": dict(self.provider_capability_snapshot),
        }


def adapt_provider_references(
    *,
    data_dir: Path,
    slot: WorkflowSlotV2,
    provider: str,
    media_type: str,
    provider_payload: dict[str, Any],
    reference_asset_ids: list[str],
) -> V2ReferenceAdaptation:
    requested = _ordered_unique(
        [
            *reference_asset_ids,
            *[
                str(asset_id)
                for asset_id in provider_payload.get("reference_asset_ids", [])
                if str(asset_id)
            ],
        ]
    )
    required = _required_reference_asset_ids(provider_payload)
    requested = _prioritize_required_reference_asset_ids(requested, required)
    capability = provider_capability_snapshot(
        slot=slot,
        provider=provider,
        media_type=media_type,
    )
    asset_store = V2AssetStoreService(data_dir)
    eligible: list[str] = []
    warnings: list[dict[str, Any]] = []
    for asset_id in requested:
        record = asset_store.find_asset_version(asset_id=asset_id)
        warning = _reference_warning_for_record(
            data_dir=data_dir,
            asset_id=asset_id,
            record=record,
            capability=capability,
        )
        if warning is not None:
            warnings.append(warning)
            continue
        eligible.append(asset_id)

    max_references = capability.get("max_reference_assets")
    submitted = list(eligible)
    if isinstance(max_references, int) and max_references >= 0:
        submitted = eligible[:max_references]
        for asset_id in eligible[max_references:]:
            warnings.append(
                _warning(
                    "provider_reference_limit_trimmed",
                    asset_id,
                    f"provider accepts {max_references} references; reference was not submitted",
                )
            )
    dropped = [asset_id for asset_id in requested if asset_id not in submitted]
    payload = {
        **provider_payload,
        "reference_policy": REFERENCE_POLICY_BEST_EFFORT,
        "reference_asset_ids": submitted,
        "requested_reference_asset_ids": requested,
        "submitted_reference_asset_ids": submitted,
        "dropped_reference_asset_ids": dropped,
        "reference_usage_warnings": warnings,
        "provider_capability_snapshot": capability,
    }
    return V2ReferenceAdaptation(
        provider_payload=sanitize_context_for_llm_text(payload),
        requested_reference_asset_ids=requested,
        submitted_reference_asset_ids=submitted,
        dropped_reference_asset_ids=dropped,
        reference_usage_warnings=sanitize_context_for_llm_text(warnings),
        provider_capability_snapshot=sanitize_context_for_llm_text(capability),
    )


def provider_capability_snapshot(
    *,
    slot: WorkflowSlotV2,
    provider: str,
    media_type: str,
) -> dict[str, Any]:
    supported_media = _supported_reference_media_types(slot.slot_type, media_type)
    max_reference_assets = _max_reference_assets(slot, media_type)
    return {
        "provider": provider,
        "media_type": media_type,
        "supported_slot_types": _supported_slot_types(media_type),
        "supports_image_reference": "image" in supported_media,
        "supports_video_reference": "video" in supported_media,
        "supports_audio_reference": "audio" in supported_media,
        "supports_multi_image_reference": "image" in supported_media and max_reference_assets != 1,
        "max_reference_assets": max_reference_assets,
        "supported_reference_semantic_types": _supported_semantic_types(
            slot.slot_type,
            media_type,
        ),
        "supported_reference_media_types": supported_media,
        "sync_or_async": "sync" if provider.startswith("dev_placeholder") else "unknown",
        "output_media_type": media_type,
        "supports_identity_lock": False,
        "supports_style_reference": media_type in {"image", "video"},
        "supports_product_reference": media_type in {"image", "video"},
        "reference_confidence": "weak",
    }


def reference_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "reference_policy": payload.get("reference_policy", REFERENCE_POLICY_BEST_EFFORT),
        "requested_reference_asset_ids": list(payload.get("requested_reference_asset_ids") or []),
        "submitted_reference_asset_ids": list(payload.get("submitted_reference_asset_ids") or []),
        "dropped_reference_asset_ids": list(payload.get("dropped_reference_asset_ids") or []),
        "reference_usage_warnings": list(payload.get("reference_usage_warnings") or []),
        "provider_capability_snapshot": dict(payload.get("provider_capability_snapshot") or {}),
    }
    if isinstance(payload.get("reference_input_delivery"), dict):
        metadata["reference_input_delivery"] = sanitize_context_for_llm_text(
            payload["reference_input_delivery"]
        )
    return metadata


def _reference_warning_for_record(
    *,
    data_dir: Path,
    asset_id: str,
    record: WorkflowAssetVersionV2 | None,
    capability: dict[str, Any],
) -> dict[str, Any] | None:
    if record is None:
        return _warning(
            "provider_reference_metadata_missing",
            asset_id,
            "reference asset metadata was not found",
        )
    public_url = str(record.public_url or "").strip()
    if not public_url or not is_provider_compatible_public_url(public_url):
        validate_v2_relative_path(record.file_path, operation="v2-provider-reference-read")
        path = Path(record.file_path)
        absolute_path = path if path.is_absolute() else data_dir / path
        if not absolute_path.exists():
            return _warning(
                "provider_reference_missing_file",
                asset_id,
                "reference asset file was not found",
            )
    supported_media = set(capability.get("supported_reference_media_types") or [])
    if supported_media and record.media_type not in supported_media:
        return _warning(
            "provider_reference_type_dropped",
            asset_id,
            f"provider does not support {record.media_type} references",
        )
    supported_semantic = set(capability.get("supported_reference_semantic_types") or [])
    if (
        supported_semantic
        and record.semantic_type
        and record.semantic_type not in supported_semantic
    ):
        return _warning(
            "provider_reference_semantic_dropped",
            asset_id,
            f"provider does not support semantic type {record.semantic_type}",
        )
    return None


def _supported_slot_types(media_type: str) -> list[str]:
    if media_type == "image":
        return [
            "product_main_image",
            "product_multi_view_grid",
            "character_main_image",
            "character_three_view",
            "scene_main_image",
            "scene_multi_view_grid",
            "shot_cell_1",
            "shot_cell_2",
            "shot_cell_3",
            "shot_cell_4",
            "free_output",
        ]
    if media_type == "video":
        return ["shot_video_segment", "final_video", "free_output"]
    if media_type == "audio":
        return ["bgm_audio", "free_output"]
    return ["free_output"]


def _supported_reference_media_types(slot_type: str, media_type: str) -> list[str]:
    if slot_type == "final_video":
        return ["video", "audio"]
    if media_type == "audio":
        return ["audio"]
    if media_type == "video":
        return ["image", "video"]
    if media_type == "image":
        return ["image"]
    return []


def _supported_semantic_types(slot_type: str, media_type: str) -> list[str]:
    if slot_type == "final_video":
        return ["shot_video_segment", "bgm_audio", "free_video", "free_audio"]
    if media_type == "audio":
        return ["bgm_audio", "free_audio", "audio_reference"]
    if media_type == "video":
        return [
            "product_reference",
            "style_reference",
            "generic_reference",
            "character_reference",
            "scene_reference",
            "product_main_image",
            "product_main",
            "product_multi_view_grid",
            "product_multi_view",
            "character_main_image",
            "character_main",
            "character_three_view",
            "scene_main_image",
            "scene_main",
            "scene_multi_view_grid",
            "scene_multi_view",
            "shot_cell_image",
            "shot_video_segment",
            "free_image",
            "free_video",
        ]
    if media_type == "image":
        return [
            "product_reference",
            "style_reference",
            "generic_reference",
            "character_reference",
            "scene_reference",
            "product_main_image",
            "product_main",
            "product_multi_view_grid",
            "product_multi_view",
            "character_main_image",
            "character_main",
            "character_three_view",
            "scene_main_image",
            "scene_main",
            "scene_multi_view_grid",
            "scene_multi_view",
            "shot_cell_image",
            "free_image",
        ]
    return []


def _max_reference_assets(slot: WorkflowSlotV2, media_type: str) -> int:
    configured = slot.provider_params.get("max_reference_assets")
    if isinstance(configured, int) and configured >= 0:
        return configured
    if slot.slot_type == "final_video":
        return 64
    if media_type == "audio":
        return 1
    return 8


def _ordered_unique(values: list[str]) -> list[str]:
    normalized = [value for value in (str(value).strip() for value in values) if value]
    return list(dict.fromkeys(normalized))


def _required_reference_asset_ids(provider_payload: dict[str, Any]) -> list[str]:
    audit = provider_payload.get("reference_audit")
    values = audit.get("required_reference_asset_ids") if isinstance(audit, dict) else []
    if not isinstance(values, list):
        return []
    return _ordered_unique([value for value in values if isinstance(value, str) and value.strip()])


def _prioritize_required_reference_asset_ids(
    requested: list[str],
    required: list[str],
) -> list[str]:
    requested_set = set(requested)
    required_first = [asset_id for asset_id in required if asset_id in requested_set]
    return _ordered_unique(
        [*required_first, *[asset_id for asset_id in requested if asset_id not in required_first]]
    )


def _warning(code: str, asset_id: str, reason: str) -> dict[str, Any]:
    return {"code": code, "asset_id": asset_id, "reason": reason}
