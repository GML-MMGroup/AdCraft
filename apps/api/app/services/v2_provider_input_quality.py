from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import (
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_provider_input import (
    V2ProviderInputAudit,
    V2ProviderInputBlueprint,
    V2QualityFlag,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_asset_store import V2AssetStoreService


class V2ProviderInputBlueprintRegistry:
    def __init__(self) -> None:
        self._blueprints = _build_blueprints()

    def get(self, slot_type: str) -> V2ProviderInputBlueprint:
        if slot_type.startswith("shot_cell_"):
            return self._blueprints["shot_cell_*"]
        if slot_type == "free_output":
            return self._blueprints["free_output"]
        blueprint = self._blueprints.get(slot_type)
        if blueprint is not None:
            return blueprint
        media_type = "video" if "video" in slot_type else "image"
        return V2ProviderInputBlueprint(
            blueprint_id=f"{slot_type.replace('_', '-')}-default-v1",
            slot_type=slot_type,
            media_type=media_type,  # type: ignore[arg-type]
            prompt_sections=["canonical provider prompt"],
            negative_constraints=["no watermark", "no unrelated content"],
            allowed_reference_roles=["style", "product", "character", "scene", "composition"],
            provider_params={"media_type": media_type},
        )


class V2ProviderInputEngineeringService:
    def __init__(
        self,
        data_dir: Path,
        *,
        registry: V2ProviderInputBlueprintRegistry | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._asset_store = V2AssetStoreService(data_dir)
        self._registry = registry or V2ProviderInputBlueprintRegistry()

    def apply(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        reference_asset_ids: list[str],
    ) -> tuple[dict[str, Any], V2ProviderInputAudit, list[V2QualityFlag]]:
        del item
        blueprint = self._registry.get(slot.slot_type)
        payload = dict(provider_payload)
        constraints = _ordered_unique(
            [
                *_constraint_list(payload.get("negative_constraints")),
                *_constraint_list(slot.negative_constraints),
                *blueprint.negative_constraints,
            ]
        )
        provider_params = {
            **blueprint.provider_params,
            **dict(slot.provider_params or {}),
            **dict(payload.get("provider_params") or {}),
        }
        provider_params["media_type"] = slot.media_type
        if slot.media_type in {"image", "video"}:
            provider_params.setdefault("aspect_ratio", workflow.aspect_ratio)
        if slot.media_type in {"audio", "video"}:
            provider_params.setdefault(
                "duration_seconds", slot.provider_params.get("duration_seconds")
            )
            provider_params["duration_seconds"] = (
                provider_params.get("duration_seconds")
                or slot.provider_params.get("duration")
                or workflow.duration_seconds
            )
        if slot.slot_type.startswith("shot_cell_"):
            provider_params.setdefault("shot_id", item_shot_id(slot))
            provider_params.setdefault("cell_id", slot.slot_type)
        if slot.slot_type == "shot_video_segment":
            provider_params.setdefault("shot_id", item_shot_id(slot))

        requested_ids = _ordered_unique(
            [
                *reference_asset_ids,
                *[
                    str(asset_id)
                    for asset_id in payload.get("reference_asset_ids", [])
                    if str(asset_id)
                ],
            ]
        )
        filtered_ids, roles, drops = self._filter_references(
            requested_ids,
            blueprint.allowed_reference_roles,
        )
        flags = _quality_flags(payload.get("quality_flags"))
        audit = V2ProviderInputAudit(
            blueprint_id=blueprint.blueprint_id,
            slot_type=slot.slot_type,
            media_type=slot.media_type if slot.media_type != "text" else blueprint.media_type,  # type: ignore[arg-type]
            negative_constraints=constraints,
            reference_roles=roles,
            provider_params=sanitize_context_for_llm_text(provider_params),
            prompt_hash=_prompt_hash(str(payload.get("provider_prompt") or "")),
        )
        audit_payload = audit.model_dump(mode="json")
        updated = {
            **payload,
            "negative_constraints": constraints,
            "provider_params": sanitize_context_for_llm_text(provider_params),
            "reference_asset_ids": filtered_ids,
            "provider_input_audit": audit_payload,
            "quality_flags": [flag.model_dump(mode="json") for flag in flags],
        }
        if drops:
            updated["provider_input_reference_drops"] = drops
        canonical = updated.get("canonical_provider_payload")
        if isinstance(canonical, dict):
            updated["canonical_provider_payload"] = {
                **canonical,
                "negative_constraints": constraints,
                "provider_params": sanitize_context_for_llm_text(provider_params),
                "reference_asset_ids": filtered_ids,
                "provider_input_audit": audit_payload,
                "quality_flags": [flag.model_dump(mode="json") for flag in flags],
            }
        return sanitize_context_for_llm_text(updated), audit, flags

    def _filter_references(
        self,
        asset_ids: list[str],
        allowed_roles: list[str],
    ) -> tuple[list[str], list[str], list[dict[str, str]]]:
        if not asset_ids:
            return [], [], []
        allowed = set(allowed_roles)
        kept: list[str] = []
        roles: list[str] = []
        drops: list[dict[str, str]] = []
        for asset_id in asset_ids:
            record = self._asset_store.find_asset_version(asset_id=asset_id)
            role = _role_for_asset(record)
            if not role or role in allowed:
                kept.append(asset_id)
                if role:
                    roles.append(role)
                continue
            drops.append(
                {
                    "asset_id": asset_id,
                    "role": role,
                    "reason": "reference_role_not_allowed_for_slot",
                }
            )
        return _ordered_unique(kept), _ordered_unique(roles), drops


def _build_blueprints() -> dict[str, V2ProviderInputBlueprint]:
    return {
        "product_main_image": V2ProviderInputBlueprint(
            blueprint_id="product-main-image-v1",
            slot_type="product_main_image",
            media_type="image",
            prompt_sections=["product identity", "product-only framing", "materials", "label"],
            negative_constraints=[
                "no people",
                "no unrelated product",
                "no hand sanitizer",
                "no detergent bottle",
                "no milk bottle",
                "no lifestyle scene as the main product asset",
                "no story action",
            ],
            allowed_reference_roles=["product", "style"],
            provider_params={"media_type": "image"},
        ),
        "product_multi_view_grid": V2ProviderInputBlueprint(
            blueprint_id="product-multi-view-grid-v1",
            slot_type="product_multi_view_grid",
            media_type="image",
            prompt_sections=["same product", "front side back views", "clean grid"],
            negative_constraints=[
                "no people",
                "no unrelated product",
                "no lifestyle scene",
                "no story action",
            ],
            allowed_reference_roles=["product", "style"],
            provider_params={"media_type": "image", "grid_intent": "multi_view"},
        ),
        "character_main_image": V2ProviderInputBlueprint(
            blueprint_id="character-main-image-v1",
            slot_type="character_main_image",
            media_type="image",
            prompt_sections=["single character identity", "wardrobe", "neutral presentation"],
            negative_constraints=[
                "no product",
                "no phone in hand",
                "no background scene",
                "no second character",
                "no story action",
            ],
            allowed_reference_roles=["character", "identity", "style"],
            provider_params={"media_type": "image"},
        ),
        "character_three_view": V2ProviderInputBlueprint(
            blueprint_id="character-three-view-v1",
            slot_type="character_three_view",
            media_type="image",
            prompt_sections=["same character", "front side back turnaround", "neutral pose"],
            negative_constraints=[
                "no product",
                "no phone in hand",
                "no background scene",
                "no second character",
                "no story action",
            ],
            allowed_reference_roles=["character", "identity"],
            provider_params={"media_type": "image", "grid_intent": "three_view"},
        ),
        "scene_main_image": V2ProviderInputBlueprint(
            blueprint_id="scene-main-image-v1",
            slot_type="scene_main_image",
            media_type="image",
            prompt_sections=["environment layout", "lighting", "materials", "time of day"],
            negative_constraints=[
                "no foreground people",
                "no named characters",
                "no product interaction",
                "no story action",
            ],
            allowed_reference_roles=["scene", "style"],
            provider_params={"media_type": "image"},
        ),
        "scene_multi_view_grid": V2ProviderInputBlueprint(
            blueprint_id="scene-multi-view-grid-v1",
            slot_type="scene_multi_view_grid",
            media_type="image",
            prompt_sections=["same environment", "multi angle reference", "consistent layout"],
            negative_constraints=[
                "no foreground people",
                "no named characters",
                "no product interaction",
                "no story action",
            ],
            allowed_reference_roles=["scene", "style"],
            provider_params={"media_type": "image", "grid_intent": "multi_view"},
        ),
        "shot_cell_*": V2ProviderInputBlueprint(
            blueprint_id="shot-cell-image-v1",
            slot_type="shot_cell_*",
            media_type="image",
            prompt_sections=[
                "product",
                "characters",
                "scene",
                "camera",
                "blocking",
                "story action",
            ],
            negative_constraints=[
                "no watermark",
                "no subtitles unless explicitly requested",
                "no unrelated products",
            ],
            allowed_reference_roles=["product", "character", "scene", "composition", "style"],
            provider_params={"media_type": "image"},
        ),
        "shot_video_segment": V2ProviderInputBlueprint(
            blueprint_id="shot-video-segment-v1",
            slot_type="shot_video_segment",
            media_type="video",
            prompt_sections=["selected shot cell assets", "motion", "duration"],
            negative_constraints=[
                "no background music if BGM is a separate node",
                "no subtitles unless explicitly requested",
                "no watermarks unless explicitly requested",
            ],
            allowed_reference_roles=["composition", "product", "character", "scene", "style"],
            provider_params={"media_type": "video"},
        ),
        "bgm_audio": V2ProviderInputBlueprint(
            blueprint_id="bgm-audio-v1",
            slot_type="bgm_audio",
            media_type="audio",
            prompt_sections=["music style", "mood", "tempo", "duration"],
            negative_constraints=[
                "no voiceover unless explicitly requested",
                "no lyrics unless explicitly requested",
                "no watermark",
            ],
            allowed_reference_roles=["audio"],
            provider_params={"media_type": "audio"},
        ),
        "final_video": V2ProviderInputBlueprint(
            blueprint_id="final-composition-v1",
            slot_type="final_video",
            media_type="video",
            prompt_sections=["timeline clips", "selected segments", "selected bgm"],
            negative_constraints=["no missing segments", "no synthetic fallback media"],
            allowed_reference_roles=["composition", "audio"],
            provider_params={"media_type": "video", "composition_mode": "timeline"},
        ),
        "free_output": V2ProviderInputBlueprint(
            blueprint_id="free-output-v1",
            slot_type="free_output",
            media_type="image",
            prompt_sections=["canonical provider prompt"],
            negative_constraints=["no watermark", "no unrelated content"],
            allowed_reference_roles=[
                "style",
                "product",
                "character",
                "scene",
                "composition",
                "audio",
            ],
            provider_params={"media_type": "image"},
        ),
    }


def _constraint_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace(";", "\n").splitlines() if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _quality_flags(value: Any) -> list[V2QualityFlag]:
    flags: list[V2QualityFlag] = []
    if not isinstance(value, list):
        return flags
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            flags.append(V2QualityFlag.model_validate(item))
        except Exception:
            continue
    return flags


def _role_for_asset(record: WorkflowAssetVersionV2 | None) -> str | None:
    if record is None:
        return None
    semantic_type = str(record.semantic_type or "").strip().lower()
    if semantic_type in {"style_reference"}:
        return "style"
    if semantic_type in {"audio_reference", "bgm", "bgm_audio", "free_audio"}:
        return "audio"
    if semantic_type.startswith("product") or semantic_type in {
        "product_reference",
        "product_main_image",
        "product_main",
        "product_multi_view_grid",
        "product_multi_view",
    }:
        return "product"
    if semantic_type.startswith("character") or semantic_type in {
        "character_reference",
        "character_main_image",
        "character_main",
        "character_three_view",
    }:
        return "character"
    if semantic_type.startswith("scene") or semantic_type in {
        "scene_reference",
        "scene_main_image",
        "scene_main",
        "scene_multi_view_grid",
        "scene_multi_view",
    }:
        return "scene"
    if semantic_type in {"shot_cell_image", "shot_video_segment", "final_video", "free_video"}:
        return "composition"
    return None


def item_shot_id(slot: WorkflowSlotV2) -> str:
    return slot.item_id


def _prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in (str(raw).strip() for raw in values) if value))
