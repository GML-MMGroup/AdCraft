from __future__ import annotations

from typing import Any, Protocol

from app.schemas.workflow_v2 import (
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_item_identity_specs import render_identity_slot_prompt


MULTIVIEW_TO_MAIN_SLOT_TYPES = {
    "product_multi_view_grid": "product_main_image",
    "character_three_view": "character_main_image",
    "scene_multi_view_grid": "scene_main_image",
}


class AssetLookup(Protocol):
    def asset_exists(self, asset_id: str) -> bool: ...

    def find_asset_version(
        self,
        *,
        slot_id: str | None = None,
        version_id: str | None = None,
        asset_id: str | None = None,
    ) -> WorkflowAssetVersionV2 | None: ...


def is_main_to_multiview_slot(slot_type: str) -> bool:
    return slot_type in MULTIVIEW_TO_MAIN_SLOT_TYPES


def main_slot_type_for_multiview(slot_type: str) -> str | None:
    return MULTIVIEW_TO_MAIN_SLOT_TYPES.get(slot_type)


def expected_main_slot_id(slot: WorkflowSlotV2) -> str | None:
    main_slot_type = main_slot_type_for_multiview(slot.slot_type)
    if main_slot_type is None:
        return None
    return f"{slot.item_id}:{main_slot_type}"


def matching_main_slot(item: WorkflowItemV2, slot: WorkflowSlotV2) -> WorkflowSlotV2 | None:
    main_slot_type = main_slot_type_for_multiview(slot.slot_type)
    if main_slot_type is None:
        return None
    return next(
        (
            candidate
            for candidate in item.slots
            if candidate.slot_type == main_slot_type and candidate.item_id == slot.item_id
        ),
        None,
    )


def dependency_slot_ids_for_multiview(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
) -> list[str]:
    source_slot_id = _source_slot_id(item, slot)
    if source_slot_id is None:
        return list(slot.dependency_slot_ids)
    return list(dict.fromkeys([source_slot_id, *slot.dependency_slot_ids]))


def main_reference_missing_metadata(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
) -> dict[str, Any]:
    return {
        "blocked_reason": "missing_selected_main_image",
        "missing_source_slot_id": _source_slot_id(item, slot) or expected_main_slot_id(slot),
        "required_main_slot_type": main_slot_type_for_multiview(slot.slot_type),
        "slot_type": slot.slot_type,
        "item_id": item.item_id,
    }


def selected_main_reference_context(
    *,
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    asset_store: AssetLookup,
) -> dict[str, Any] | None:
    source_slot = matching_main_slot(item, slot)
    if source_slot is None:
        return None
    if not source_slot.selected_asset_id or not source_slot.selected_version_id:
        return None
    if not asset_store.asset_exists(source_slot.selected_asset_id):
        return None
    record = asset_store.find_asset_version(
        asset_id=source_slot.selected_asset_id,
        version_id=source_slot.selected_version_id,
    ) or asset_store.find_asset_version(asset_id=source_slot.selected_asset_id)
    dependency_slot_ids = dependency_slot_ids_for_multiview(item, slot)
    consistency_contract = {
        "mode": "derive_from_selected_main",
        "source_slot_id": source_slot.slot_id,
        "source_asset_id": source_slot.selected_asset_id,
        "source_version_id": source_slot.selected_version_id,
        "item_id": item.item_id,
        "slot_type": slot.slot_type,
    }
    identity_contract, warnings = build_identity_contract(
        workflow=workflow,
        item=item,
        slot=slot,
        source_slot=source_slot,
        source_record=record,
    )
    return sanitize_context_for_llm_text(
        {
            "primary_reference_asset_id": source_slot.selected_asset_id,
            "primary_reference_version_id": source_slot.selected_version_id,
            "reference_asset_ids": [source_slot.selected_asset_id],
            "reference_version_ids": [source_slot.selected_version_id],
            "dependency_slot_ids": dependency_slot_ids,
            "consistency_contract": consistency_contract,
            "identity_contract": identity_contract,
            "source_slot": {
                "slot_id": source_slot.slot_id,
                "slot_type": source_slot.slot_type,
                "asset_id": source_slot.selected_asset_id,
                "version_id": source_slot.selected_version_id,
            },
            "source_asset_metadata": dict(record.metadata) if record is not None else {},
            "warnings": warnings,
        }
    )


def build_identity_contract(
    *,
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    source_slot: WorkflowSlotV2,
    source_record: WorkflowAssetVersionV2 | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    del slot
    record_metadata = dict(source_record.metadata) if source_record is not None else {}
    warnings: list[dict[str, Any]] = []
    if source_record is None:
        warnings.append(
            {
                "code": "identity_contract_built_from_prompt_only",
                "message": "Selected main asset metadata was unavailable; contract used item prompt metadata only.",
            }
        )
    entity_type = item.item_type
    contract = {
        "entity_type": entity_type,
        "item_id": item.item_id,
        "display_name": item.display_name,
        "style_family": _first_string(
            record_metadata,
            item.metadata,
            workflow.metadata,
            keys=("style_family", "visual_style", "art_style", "style_summary"),
        )
        or "unspecified",
        "subject_summary": _subject_summary(item, record_metadata),
        "visual_invariants": _visual_invariants(entity_type),
        "source_slot_id": source_slot.slot_id,
        "source_asset_id": source_slot.selected_asset_id,
        "source_version_id": source_slot.selected_version_id,
    }
    identity_spec = item.metadata.get("identity_spec")
    if isinstance(identity_spec, dict) and identity_spec:
        contract["identity_spec"] = identity_spec
        contract["identity_spec_prompt"] = render_identity_slot_prompt(
            item_type=entity_type,
            slot_type=source_slot.slot_type.replace("_main_image", "_multi_view_grid")
            if entity_type != "character"
            else "character_three_view",
            identity_spec=identity_spec,
            fallback_prompt=item.item_prompt or item.description or item.display_name,
        )
    wardrobe_summary = _first_string(
        record_metadata,
        item.metadata,
        keys=("wardrobe_summary", "outfit_summary", "clothing_summary"),
    )
    if wardrobe_summary:
        contract["wardrobe_summary"] = wardrobe_summary
    return sanitize_context_for_llm_text(contract), warnings


def compile_multiview_provider_prompt(
    *,
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    context: dict[str, Any],
) -> str | None:
    if not is_main_to_multiview_slot(slot.slot_type):
        return None
    primary_asset_id = str(context.get("primary_reference_asset_id") or "").strip()
    identity_contract = context.get("identity_contract")
    identity_contract = identity_contract if isinstance(identity_contract, dict) else {}
    style_summary = _trimmed_text(
        _global_style_summary(workflow, item, identity_contract),
        limit=120,
    )
    identity_spec_prompt = _identity_contract_summary(identity_contract)
    source_slot_id = str(context.get("consistency_contract", {}).get("source_slot_id") or "")
    common = [
        f"Primary reference: {primary_asset_id}.",
        f"Source: {source_slot_id}.",
        f"Identity contract: {identity_spec_prompt}." if identity_spec_prompt else "",
        f"Style summary: {style_summary}." if style_summary else "",
        "Use selected main image only. Ignore other prompts.",
    ]
    if slot.slot_type == "character_three_view":
        sections = [
            *common,
            "Generate same character three-view turnaround: front, side, back.",
            "Preserve face, hair, outfit, proportions, and style.",
            "Neutral background; no scene, product, props, extra characters, text/logos.",
        ]
    elif slot.slot_type == "scene_multi_view_grid":
        sections = [
            *common,
            "Generate a 2x2 four-view establishing environment/background grid of the same location.",
            "Preserve architecture, lighting, materials, palette, and time of day.",
            "Keep the scene empty by default.",
            "No people, character portraits, products, logos, text, or unrelated props unless requested.",
        ]
    else:
        sections = [
            *common,
            "Generate a 2x2 four-panel view grid of the same product.",
            "Preserve product identity, silhouette, material, color, and design details.",
            "Show front, side, back, and three-quarter angles.",
            "Clean neutral studio background; no people, scenes, props, text, or extra products.",
        ]
    return "\n".join(section for section in sections if section)


def _source_slot_id(item: WorkflowItemV2, slot: WorkflowSlotV2) -> str | None:
    source_slot = matching_main_slot(item, slot)
    if source_slot is not None:
        return source_slot.slot_id
    return expected_main_slot_id(slot)


def _subject_summary(item: WorkflowItemV2, record_metadata: dict[str, Any]) -> str:
    return (
        _first_string(
            record_metadata,
            item.metadata,
            keys=("subject_summary", "prompt_summary", "provider_prompt", "creative_brief"),
        )
        or item.item_prompt
        or item.description
        or item.display_name
    )


def _visual_invariants(entity_type: str) -> list[str]:
    if entity_type == "character":
        return [
            "same face",
            "same hairstyle",
            "same outfit",
            "same body proportions",
            "same art style",
        ]
    if entity_type == "scene":
        return [
            "same location",
            "same architectural layout",
            "same lighting design",
            "same time of day",
            "no people unless explicitly requested",
        ]
    return [
        "same product model",
        "same silhouette",
        "same color/material",
        "same branding if visible",
    ]


def _global_style_summary(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    identity_contract: dict[str, Any],
) -> str:
    value = _first_string(
        identity_contract,
        item.metadata,
        workflow.metadata,
        keys=("style_summary", "visual_style", "style_family", "art_style", "director_style"),
    )
    if not value or value.strip().lower() in {"unspecified", "none", "n/a", "unknown"}:
        return ""
    return value


def _identity_contract_summary(identity_contract: dict[str, Any]) -> str:
    spec = identity_contract.get("identity_spec")
    if not isinstance(spec, dict) or not spec:
        return _trimmed_text(str(identity_contract.get("identity_spec_prompt") or ""), limit=140)
    entity_type = str(identity_contract.get("entity_type") or "").strip()
    if entity_type == "character":
        return _join_field_summaries(
            spec,
            (
                ("age", "age_impression"),
                ("wardrobe", "wardrobe"),
                ("silhouette", "silhouette"),
                ("hairstyle", "hairstyle"),
            ),
        )
    if entity_type == "scene":
        return _join_field_summaries(
            spec,
            (
                ("location", "location_type"),
                ("time", "time_of_day"),
                ("lighting", "lighting"),
                ("weather", "weather_or_surface"),
                ("composition", "composition_zones"),
            ),
        )
    return _join_field_summaries(
        spec,
        (
            ("name", "product_name"),
            ("category", "product_category"),
            ("silhouette", "silhouette"),
            ("features", "recognizable_features"),
        ),
    )


def _join_field_summaries(
    payload: dict[str, Any],
    fields: tuple[tuple[str, str], ...],
) -> str:
    parts: list[str] = []
    for label, key in fields:
        value = _summary_value(payload.get(key))
        if value:
            parts.append(f"{label} {value}")
    return "; ".join(parts)


def _summary_value(value: Any) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item).strip() for item in value[:3] if str(item).strip())
    else:
        text = str(value or "").strip()
    return _trimmed_text(text, limit=120)


def _first_string(*payloads: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _trimmed_text(value: str | None, *, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."
