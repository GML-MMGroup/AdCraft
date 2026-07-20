from __future__ import annotations

import re
from typing import Any

from app.services.script_beats import build_default_script_beats, ensure_script_beat_aliases
from app.services.workflow_asset_contract import extract_provider_output_assets

ALLOWED_NO_SCENE_REASONS = {
    "product_packshot",
    "title_card",
    "abstract_visual",
    "transition",
    "user_requested_scene_free_shot",
}

SCENE_FREE_SHOT_TYPES = {
    "product_packshot",
    "title_card",
    "abstract_visual",
    "transition",
}

SHOT_BINDING_ERROR_CODE = "shot_reference_binding_invalid"


def storyboard_binding_failure_output(error_details: dict[str, Any]) -> dict[str, Any]:
    rule = str(error_details.get("failed_rule") or SHOT_BINDING_ERROR_CODE)
    shot_id = str(error_details.get("shot_id") or "")
    return {
        "status": "failed",
        "error_code": SHOT_BINDING_ERROR_CODE,
        "error": f"{SHOT_BINDING_ERROR_CODE}: {rule}" + (f" for {shot_id}" if shot_id else ""),
        "error_details": error_details,
        "assets": [],
        "output_assets": [],
    }


def build_storyboard_binding_plan(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    provider_prompt: str = "",
) -> dict[str, Any]:
    assets = _known_assets(context, input_assets)
    scene_assets = normalize_scene_assets(context, assets)
    character_assets = normalize_character_assets(context, assets)
    product_assets = normalize_product_assets(context, assets)
    shots = _normalize_storyboard_shots(
        context,
        assets,
        scene_assets,
        character_assets,
        product_assets,
        provider_prompt,
    )
    error = validate_storyboard_shots(shots, scene_assets, character_assets, product_assets)
    return {
        "scene_assets": scene_assets,
        "character_assets": character_assets,
        "product_assets": product_assets,
        "shots": shots,
        "error": error,
    }


def build_storyboard_video_binding_plan(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    provider_prompt: str = "",
) -> dict[str, Any]:
    plan = build_storyboard_binding_plan(context, input_assets, provider_prompt)
    if plan.get("error"):
        return plan
    storyboard_assets = _storyboard_image_assets(context, input_assets)
    assets_by_id = {str(asset.get("asset_id") or ""): asset for asset in input_assets}
    shots: list[dict[str, Any]] = []
    for shot in plan["shots"]:
        order = _int_value(shot.get("order"), len(shots) + 1)
        storyboard_asset = _storyboard_asset_for_shot(storyboard_assets, shot, order)
        input_asset_ids = list(shot.get("input_asset_ids") or [])
        if storyboard_asset and storyboard_asset.get("asset_id"):
            input_asset_ids = _dedupe_strings([str(storyboard_asset["asset_id"]), *input_asset_ids])
            assets_by_id[str(storyboard_asset["asset_id"])] = storyboard_asset
        video_shot = {
            **shot,
            "item_id": str(shot.get("shot_id") or f"shot_{order:03d}"),
            "prompt": _first_text(
                shot,
                (
                    "storyboardVideoPrompt",
                    "videoPrompt",
                    "prompt",
                    "visual",
                    "storyboardImagePrompt",
                    "shotDescription",
                    "action",
                ),
            )
            or provider_prompt
            or f"Storyboard video segment for shot {order}.",
            "duration_seconds": _video_item_duration(
                shot.get("duration_seconds") or shot.get("durationSeconds")
            ),
            "input_asset_ids": input_asset_ids,
            "input_assets": [
                assets_by_id[asset_id] for asset_id in input_asset_ids if asset_id in assets_by_id
            ],
        }
        if storyboard_asset:
            video_shot["source_storyboard_image"] = storyboard_asset
            video_shot["storyboard_asset_id"] = storyboard_asset.get("asset_id")
        video_shot["metadata"] = _metadata_with_bindings(video_shot)
        shots.append(video_shot)
    plan["shots"] = shots
    return plan


def enrich_storyboard_context(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    plan = build_storyboard_binding_plan(
        context,
        input_assets,
        str(context.get("provider_prompt") or context.get("optimized_generation_prompt") or ""),
    )
    enriched = dict(context)
    enriched["scene_assets"] = plan["scene_assets"]
    enriched["character_assets"] = plan["character_assets"]
    enriched["product_assets"] = plan["product_assets"]
    enriched["shots"] = plan["shots"]
    enriched["media_items"] = storyboard_media_items_from_shots(plan["shots"])
    return enriched


def normalize_scene_assets(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    explicit = _first_list(
        context.get("scene_assets"),
        _nested_value(context, "scene_generation", "scene_assets"),
        _nested_value(context, "scene_generation", "structured_output", "scene_assets"),
        _nested_value(context, "scene_generation", "structured_output", "scenes"),
    )
    available = _assets_by_id(input_assets)
    source_items = explicit or _scene_assets_from_flat_assets(context, input_assets)
    normalized: list[dict[str, Any]] = []
    seen_scene_ids: set[str] = set()
    for index, item in enumerate(source_items, start=1):
        if not isinstance(item, dict):
            continue
        output_assets = _embedded_output_assets(item, available)
        asset_ids = _dedupe_strings(
            [
                *_list_of_strings(item.get("asset_ids") or item.get("assetIds")),
                *[str(asset.get("asset_id")) for asset in output_assets if asset.get("asset_id")],
            ]
        )
        if not output_assets and asset_ids:
            output_assets = [available[asset_id] for asset_id in asset_ids if asset_id in available]
        if not asset_ids and item.get("asset_id"):
            asset_ids = [str(item["asset_id"])]
            output_assets = [item]
        scene_id = _canonical_scene_id(item, output_assets, index)
        if not scene_id or scene_id in seen_scene_ids or not asset_ids:
            continue
        seen_scene_ids.add(scene_id)
        normalized.append(
            {
                "scene_id": scene_id,
                "display_name": str(
                    item.get("display_name")
                    or item.get("sceneName")
                    or item.get("scene_name")
                    or item.get("title")
                    or f"Scene {index}"
                ),
                "prompt": _first_text(
                    item,
                    ("prompt", "scenePrompt", "sceneDescription", "atmosphere", "role"),
                ),
                "asset_ids": asset_ids,
                "output_assets": output_assets,
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
    return normalized


def normalize_character_assets(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _normalize_entity_assets(
        context,
        input_assets,
        output_key="character_generation",
        id_keys=("character_id", "characterId", "roleId", "role_id", "entity_id"),
        role_values={"character_reference", "character_turnaround", "character"},
        semantic_prefix="character",
        entity_key="character_id",
        fallback_prefix="character",
    )


def normalize_product_assets(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _normalize_entity_assets(
        context,
        input_assets,
        output_key="product_generation",
        id_keys=("product_id", "productId", "entity_id", "item_id"),
        role_values={"product_reference", "product", "product_image"},
        semantic_prefix="product",
        entity_key="product_id",
        fallback_prefix="product",
    )


def validate_storyboard_shots(
    shots: list[dict[str, Any]],
    scene_assets: list[dict[str, Any]],
    character_assets: list[dict[str, Any]],
    product_assets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    seen_shot_ids: set[str] = set()
    reference_ids = _storyboard_reference_ids(scene_assets, character_assets, product_assets)
    for index, shot in enumerate(shots, start=1):
        error = _validate_storyboard_shot(shot, index, seen_shot_ids, reference_ids)
        if error is not None:
            return error
    return None


def _storyboard_reference_ids(
    scene_assets: list[dict[str, Any]],
    character_assets: list[dict[str, Any]],
    product_assets: list[dict[str, Any]],
) -> dict[str, set[str]]:
    return {
        "scene": {str(scene["scene_id"]) for scene in scene_assets if scene.get("scene_id")},
        "character": {
            str(asset["character_id"]) for asset in character_assets if asset.get("character_id")
        },
        "product": {
            str(asset["product_id"]) for asset in product_assets if asset.get("product_id")
        },
    }


def _validate_storyboard_shot(
    shot: dict[str, Any],
    index: int,
    seen_shot_ids: set[str],
    reference_ids: dict[str, set[str]],
) -> dict[str, Any] | None:
    shot_id = str(shot.get("shot_id") or "")
    if not shot_id:
        return _error("missing_shot_id", "", index=index)
    if shot_id in seen_shot_ids:
        return _error("duplicate_shot_id", shot_id)
    seen_shot_ids.add(shot_id)
    error = _validate_shot_scene_references(shot, shot_id, reference_ids["scene"])
    if error is not None:
        return error
    error = _validate_shot_entity_references(
        shot,
        shot_id,
        entity_key="character_ids",
        known_ids=reference_ids["character"],
        error_rule="unknown_character_reference",
        error_field="invalid_character_ids",
    )
    if error is not None:
        return error
    error = _validate_shot_entity_references(
        shot,
        shot_id,
        entity_key="product_reference_ids",
        known_ids=reference_ids["product"],
        error_rule="unknown_product_reference",
        error_field="invalid_product_reference_ids",
    )
    if error is not None:
        return error
    if _shot_requires_input_assets(shot):
        return _error("empty_input_asset_ids", shot_id)
    return None


def _validate_shot_scene_references(
    shot: dict[str, Any],
    shot_id: str,
    scene_ids: set[str],
) -> dict[str, Any] | None:
    scene_reference_ids = _list_of_strings(shot.get("scene_reference_ids"))
    primary_scene_id = str(shot.get("primary_scene_id") or "").strip()
    if scene_reference_ids:
        unknown = [scene_id for scene_id in scene_reference_ids if scene_id not in scene_ids]
        if unknown:
            return _error(
                "unknown_scene_reference",
                shot_id,
                invalid_scene_reference_ids=unknown,
            )
        if not primary_scene_id:
            return _error("missing_primary_scene_id", shot_id)
        if primary_scene_id not in scene_reference_ids:
            return _error(
                "primary_scene_id_not_in_scene_reference_ids",
                shot_id,
                invalid_scene_reference_ids=[primary_scene_id],
            )
        return None
    no_scene_reason = str(shot.get("no_scene_reason") or "").strip()
    if no_scene_reason not in ALLOWED_NO_SCENE_REASONS and not shot.get(
        "_allow_unbound_quality_warning"
    ):
        return _error("missing_scene_reference_or_no_scene_reason", shot_id)
    return None


def _validate_shot_entity_references(
    shot: dict[str, Any],
    shot_id: str,
    *,
    entity_key: str,
    known_ids: set[str],
    error_rule: str,
    error_field: str,
) -> dict[str, Any] | None:
    unknown = [
        entity_id
        for entity_id in _list_of_strings(shot.get(entity_key))
        if entity_id not in known_ids
    ]
    if not unknown:
        return None
    return _error(error_rule, shot_id, **{error_field: unknown})


def _shot_requires_input_assets(shot: dict[str, Any]) -> bool:
    return (
        not _list_of_strings(shot.get("input_asset_ids"))
        and str(shot.get("no_scene_reason") or "") not in ALLOWED_NO_SCENE_REASONS
        and not shot.get("_allow_unbound_quality_warning")
    )


def storyboard_media_items_from_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for index, shot in enumerate(shots, start=1):
        item = {
            "item_id": str(shot.get("shot_id") or f"shot_{index:03d}"),
            "item_type": "storyboard_image",
            "order": _int_value(shot.get("order"), index),
            "display_name": str(shot.get("display_name") or shot.get("shot") or f"Shot {index}"),
            "prompt": str(shot.get("prompt") or shot.get("visual") or ""),
            "input_asset_ids": _list_of_strings(shot.get("input_asset_ids")),
            "reference_mode": str(shot.get("reference_mode") or "strict"),
            "status": str(shot.get("status") or "waiting"),
            "primary_scene_id": shot.get("primary_scene_id"),
            "scene_reference_ids": _list_of_strings(shot.get("scene_reference_ids")),
            "character_ids": _list_of_strings(shot.get("character_ids")),
            "product_reference_ids": _list_of_strings(shot.get("product_reference_ids")),
            "style_reference_ids": _list_of_strings(shot.get("style_reference_ids")),
            "no_scene_reason": shot.get("no_scene_reason"),
            "output_assets": shot.get("output_assets")
            if isinstance(shot.get("output_assets"), list)
            else [],
            "metadata": shot.get("metadata") if isinstance(shot.get("metadata"), dict) else {},
        }
        items.append(item)
    return items


def apply_storyboard_bindings_to_output(
    output: dict[str, Any],
    plan: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    shots = list(plan.get("shots") or [])
    output = {
        **output,
        "scene_assets": plan.get("scene_assets") or [],
        "character_assets": plan.get("character_assets") or [],
        "product_assets": plan.get("product_assets") or [],
        "shots": shots,
    }
    assets = _annotate_assets_for_shots(_output_asset_list(output), shots, input_assets)
    output["assets"] = assets
    output["output_assets"] = assets
    output["media_items"] = _attach_output_assets_to_items(
        storyboard_media_items_from_shots(shots), assets
    )
    return output


def apply_storyboard_video_bindings_to_output(
    output: dict[str, Any],
    plan: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    shots = list(plan.get("shots") or [])
    output = {**output, "scene_prompts": shots}
    assets = _annotate_assets_for_shots(_output_asset_list(output), shots, input_assets)
    if assets:
        output["assets"] = assets
        output["output_assets"] = assets
    segments = output.get("segments")
    if isinstance(segments, list):
        output["segments"] = _annotate_assets_for_shots(
            [segment for segment in segments if isinstance(segment, dict)],
            shots,
            input_assets,
        )
    output["media_items"] = _attach_output_assets_to_items(
        _video_media_items_from_shots(shots), output.get("segments") or assets
    )
    return output


def shot_references_entity(item: dict[str, Any], entity_ids: set[str]) -> bool:
    values = {
        str(item.get("primary_scene_id") or ""),
        *map(str, item.get("scene_reference_ids") or []),
        *map(str, item.get("character_ids") or []),
        *map(str, item.get("product_reference_ids") or []),
    }
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        bindings = metadata.get("reference_bindings")
        if isinstance(bindings, dict):
            values.update(str(value) for value in bindings.values() if isinstance(value, str))
            for key in ("scene_reference_ids", "character_ids", "product_reference_ids"):
                raw = bindings.get(key)
                if isinstance(raw, list):
                    values.update(str(value) for value in raw)
    return bool(entity_ids.intersection(value for value in values if value))


def item_id_for_stale(item: dict[str, Any]) -> str:
    for key in ("item_id", "shot_id", "shotId", "entity_id", "segment_id", "segmentId"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def canonical_storyboard_shots_from_output(output: dict[str, Any]) -> list[dict[str, Any]]:
    structured = (
        output.get("structured_output") if isinstance(output.get("structured_output"), dict) else {}
    )
    for value in (output.get("shots"), structured.get("shots")):
        if isinstance(value, list) and value:
            return [shot for shot in value if isinstance(shot, dict)]
    items = _first_list(
        output.get("storyboardItems"),
        structured.get("storyboardItems"),
        output.get("scenes"),
    )
    return [
        _normalize_legacy_storyboard_source(item, index, [], [], [], {}, "")
        for index, item in enumerate(items, start=1)
        if isinstance(item, dict)
    ]


def _normalize_storyboard_shots(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    scene_assets: list[dict[str, Any]],
    character_assets: list[dict[str, Any]],
    product_assets: list[dict[str, Any]],
    provider_prompt: str,
) -> list[dict[str, Any]]:
    raw_sources = _storyboard_sources(context)
    if not raw_sources:
        raw_sources = _storyboard_sources_from_script(context)
    if not raw_sources:
        raw_sources = [
            {
                "order": 1,
                "prompt": provider_prompt or "Storyboard keyframe.",
                "shot_type": "custom",
                "_allow_unbound_quality_warning": True,
            }
        ]
    asset_by_id = _assets_by_id(input_assets)
    shots = []
    multiple = len(raw_sources) > 1
    for index, source in enumerate(raw_sources, start=1):
        if not isinstance(source, dict):
            continue
        shots.append(
            _normalize_legacy_storyboard_source(
                source,
                index,
                scene_assets,
                character_assets,
                product_assets,
                asset_by_id,
                "" if multiple else provider_prompt,
            )
        )
    return shots


def _normalize_legacy_storyboard_source(
    source: dict[str, Any],
    index: int,
    scene_assets: list[dict[str, Any]],
    character_assets: list[dict[str, Any]],
    product_assets: list[dict[str, Any]],
    asset_by_id: dict[str, dict[str, Any]],
    provider_prompt: str,
) -> dict[str, Any]:
    order = _int_value(source.get("order") or source.get("shotIndex") or source.get("scene"), index)
    shot_id = str(
        source.get("shot_id")
        or source.get("shotId")
        or source.get("item_id")
        or source.get("entity_id")
        or f"shot_{order:03d}"
    )
    prompt = (
        _first_text(
            source,
            (
                "prompt",
                "storyboardImagePrompt",
                "visual",
                "shotDescription",
                "action",
                "product_action",
            ),
        )
        or provider_prompt
        or f"Storyboard keyframe for shot {order}."
    )
    shot_type = str(source.get("shot_type") or source.get("shotType") or "").strip()
    no_scene_reason = str(
        source.get("no_scene_reason") or source.get("noSceneReason") or ""
    ).strip()
    if not shot_type:
        shot_type = no_scene_reason if no_scene_reason in SCENE_FREE_SHOT_TYPES else "lifestyle"
    scene_reference_ids = _canonical_scene_references(source, scene_assets, order)
    legacy_scene_id = str(source.get("scene_id") or source.get("sceneId") or "").strip()
    primary_scene_id = str(
        source.get("primary_scene_id") or source.get("primarySceneId") or ""
    ).strip()
    if primary_scene_id:
        primary_scene_id = (
            _scene_reference_to_scene_id(primary_scene_id, scene_assets) or primary_scene_id
        )
    if not primary_scene_id and scene_reference_ids:
        primary_scene_id = scene_reference_ids[0]
    if not scene_reference_ids and shot_type in SCENE_FREE_SHOT_TYPES and not no_scene_reason:
        no_scene_reason = shot_type
    if (
        not scene_reference_ids
        and not no_scene_reason
        and not scene_assets
        and not source.get("_allow_unbound_quality_warning")
    ):
        no_scene_reason = "user_requested_scene_free_shot"
    character_ids = _canonical_entity_ids(
        source,
        ("character_ids", "characterIds", "characters"),
        character_assets,
        "character_id",
    )
    product_reference_ids = _canonical_entity_ids(
        source,
        ("product_reference_ids", "productReferenceIds", "product_ids", "productIds"),
        product_assets,
        "product_id",
    )
    if not product_reference_ids and product_assets:
        product_reference_ids = [
            str(asset["product_id"]) for asset in product_assets if asset.get("product_id")
        ]
    explicit_input_ids = _list_of_strings(
        source.get("input_asset_ids") or source.get("inputAssetIds")
    )
    input_asset_ids = _derive_input_asset_ids(
        scene_reference_ids,
        character_ids,
        product_reference_ids,
        explicit_input_ids,
        scene_assets,
        character_assets,
        product_assets,
        asset_by_id,
    )
    shot = {
        **source,
        "shot_id": shot_id,
        "item_id": shot_id,
        "order": order,
        "shot_type": shot_type,
        "prompt": prompt,
        "primary_scene_id": primary_scene_id or None,
        "scene_reference_ids": scene_reference_ids,
        "character_ids": character_ids,
        "product_reference_ids": product_reference_ids,
        "style_reference_ids": _list_of_strings(
            source.get("style_reference_ids") or source.get("styleReferenceIds")
        ),
        "input_asset_ids": input_asset_ids,
        "input_assets": [
            asset_by_id[asset_id] for asset_id in input_asset_ids if asset_id in asset_by_id
        ],
        "shot": str(source.get("shot") or source.get("display_name") or f"Shot {order}"),
        "visual": prompt,
        "text": str(source.get("text") or source.get("spoken_or_on_screen_text") or ""),
        "duration_seconds": _int_value(
            source.get("duration_seconds") or source.get("durationSeconds"), 5
        ),
        "camera": str(source.get("camera") or source.get("cameraLanguage") or "stable composition"),
        "action": str(source.get("action") or source.get("product_action") or ""),
        "scene_id": legacy_scene_id
        or primary_scene_id
        or (scene_reference_ids[0] if scene_reference_ids else ""),
    }
    if no_scene_reason:
        shot["no_scene_reason"] = no_scene_reason
    shot["metadata"] = _metadata_with_bindings(shot)
    return shot


def _storyboard_sources(context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    storyboard = context.get("storyboard")
    if isinstance(storyboard, dict):
        structured = (
            storyboard.get("structured_output")
            if isinstance(storyboard.get("structured_output"), dict)
            else {}
        )
        candidates.extend(
            [
                storyboard.get("shots"),
                structured.get("shots"),
                storyboard.get("storyboardItems"),
                structured.get("storyboardItems"),
                storyboard.get("scenes"),
            ]
        )
    candidates.extend([context.get("shots"), context.get("storyboardItems"), context.get("scenes")])
    media_items = context.get("media_items")
    if isinstance(media_items, list):
        storyboard_items = [
            item
            for item in media_items
            if isinstance(item, dict) and str(item.get("item_type") or "") == "storyboard_image"
        ]
        if storyboard_items:
            candidates.insert(0, storyboard_items)
    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _storyboard_sources_from_script(context: dict[str, Any]) -> list[dict[str, Any]]:
    script = context.get("script")
    beats = []
    if isinstance(script, dict):
        normalized = ensure_script_beat_aliases(script)
        raw = normalized.get("shot_beats")
        if isinstance(raw, list):
            beats = [beat for beat in raw if isinstance(beat, dict)]
    fallback_beats = not beats
    if not beats:
        beats = build_default_script_beats(
            product_name="Product",
            desired_emotion="confident",
            duration_seconds=_duration_from_context(context),
        )
    return [
        {
            "order": beat.get("order") or index,
            "prompt": (
                f"{beat.get('scene_intent') or 'Storyboard beat'}: "
                f"{beat.get('visual_action') or ''}"
            ),
            "text": beat.get("spoken_or_on_screen_text") or "",
            "duration_seconds": beat.get("duration_seconds") or 5,
            "action": beat.get("product_action") or "",
            "shot_type": "lifestyle",
            "input_asset_ids": beat.get("input_asset_ids") or [],
            "scene_id": beat.get("scene_id"),
            "_allow_unbound_quality_warning": fallback_beats,
        }
        for index, beat in enumerate(beats, start=1)
    ]


def _canonical_scene_references(
    source: dict[str, Any],
    scene_assets: list[dict[str, Any]],
    order: int,
) -> list[str]:
    raw_refs = _list_of_strings(
        source.get("scene_reference_ids")
        or source.get("sceneReferenceIds")
        or source.get("scene_ids")
        or source.get("sceneIds")
    )
    legacy_scene = str(
        source.get("primary_scene_id")
        or source.get("primarySceneId")
        or source.get("scene_id")
        or source.get("sceneId")
        or ""
    ).strip()
    if legacy_scene:
        raw_refs.insert(0, legacy_scene)
    if not raw_refs and scene_assets:
        raw_refs.append(str(scene_assets[(order - 1) % len(scene_assets)]["scene_id"]))
    return _dedupe_strings(
        [
            scene_id
            for ref in raw_refs
            for scene_id in [_scene_reference_to_scene_id(ref, scene_assets)]
            if scene_id
        ]
    )


def _scene_reference_to_scene_id(ref: str, scene_assets: list[dict[str, Any]]) -> str | None:
    if not ref:
        return None
    if not scene_assets:
        return None
    for scene in scene_assets:
        scene_id = str(scene.get("scene_id") or "")
        if ref == scene_id or ref in _list_of_strings(scene.get("asset_ids")):
            return scene_id
    match = re.search(r"(\d+)$", ref)
    if match:
        order = int(match.group(1))
        if 1 <= order <= len(scene_assets):
            candidate = scene_assets[order - 1]
            if ref.startswith("scene-reference-") or ref.startswith("scene-"):
                return str(candidate.get("scene_id") or "") or None
    return ref


def _canonical_entity_ids(
    source: dict[str, Any],
    keys: tuple[str, ...],
    entity_assets: list[dict[str, Any]],
    entity_key: str,
) -> list[str]:
    raw_ids: list[str] = []
    for key in keys:
        raw_ids.extend(_list_of_strings(source.get(key)))
    normalized: list[str] = []
    for raw_id in raw_ids:
        normalized.append(
            _entity_reference_to_entity_id(raw_id, entity_assets, entity_key) or raw_id
        )
    return _dedupe_strings(normalized)


def _entity_reference_to_entity_id(
    ref: str,
    entity_assets: list[dict[str, Any]],
    entity_key: str,
) -> str | None:
    for asset in entity_assets:
        entity_id = str(asset.get(entity_key) or "")
        if ref == entity_id or ref == str(asset.get("asset_id") or ""):
            return entity_id
    return None


def _derive_input_asset_ids(
    scene_reference_ids: list[str],
    character_ids: list[str],
    product_reference_ids: list[str],
    explicit_input_ids: list[str],
    scene_assets: list[dict[str, Any]],
    character_assets: list[dict[str, Any]],
    product_assets: list[dict[str, Any]],
    asset_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    ids.extend(asset_id for asset_id in explicit_input_ids if asset_id in asset_by_id)
    for scene_id in scene_reference_ids:
        for scene in scene_assets:
            if scene.get("scene_id") == scene_id:
                ids.extend(_list_of_strings(scene.get("asset_ids")))
    ids.extend(_asset_ids_for_entity(character_assets, "character_id", character_ids))
    ids.extend(_asset_ids_for_entity(product_assets, "product_id", product_reference_ids))
    return _dedupe_strings(ids)


def _asset_ids_for_entity(
    assets: list[dict[str, Any]],
    entity_key: str,
    entity_ids: list[str],
) -> list[str]:
    wanted = set(entity_ids)
    return [
        str(asset.get("asset_id"))
        for asset in assets
        if asset.get("asset_id") and str(asset.get(entity_key) or "") in wanted
    ]


def _metadata_with_bindings(shot: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(shot.get("metadata")) if isinstance(shot.get("metadata"), dict) else {}
    metadata["reference_bindings"] = {
        "shot_id": shot.get("shot_id"),
        "primary_scene_id": shot.get("primary_scene_id"),
        "scene_reference_ids": _list_of_strings(shot.get("scene_reference_ids")),
        "character_ids": _list_of_strings(shot.get("character_ids")),
        "product_reference_ids": _list_of_strings(shot.get("product_reference_ids")),
        "style_reference_ids": _list_of_strings(shot.get("style_reference_ids")),
        "no_scene_reason": shot.get("no_scene_reason"),
        "input_asset_ids": _list_of_strings(shot.get("input_asset_ids")),
    }
    return metadata


def _annotate_assets_for_shots(
    assets: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    input_by_id = _assets_by_id(input_assets)
    annotated = []
    for index, asset in enumerate(assets, start=1):
        shot = _shot_for_asset(shots, asset, index)
        if shot is None:
            annotated.append(asset)
            continue
        input_asset_ids = _list_of_strings(shot.get("input_asset_ids"))
        metadata = dict(asset.get("metadata")) if isinstance(asset.get("metadata"), dict) else {}
        metadata.setdefault(
            "reference_bindings", _metadata_with_bindings(shot)["reference_bindings"]
        )
        annotated.append(
            {
                **asset,
                "entity_id": shot.get("shot_id"),
                "shot_id": shot.get("shot_id"),
                "item_id": shot.get("shot_id"),
                "primary_scene_id": shot.get("primary_scene_id"),
                "scene_id": shot.get("primary_scene_id") or asset.get("scene_id"),
                "scene_reference_ids": _list_of_strings(shot.get("scene_reference_ids")),
                "character_ids": _list_of_strings(shot.get("character_ids")),
                "product_reference_ids": _list_of_strings(shot.get("product_reference_ids")),
                "style_reference_ids": _list_of_strings(shot.get("style_reference_ids")),
                "no_scene_reason": shot.get("no_scene_reason"),
                "input_asset_ids": input_asset_ids,
                "input_assets": [
                    input_by_id[asset_id] for asset_id in input_asset_ids if asset_id in input_by_id
                ],
                "prompt": asset.get("prompt") or shot.get("prompt"),
                "metadata": metadata,
            }
        )
    return annotated


def _shot_for_asset(
    shots: list[dict[str, Any]],
    asset: dict[str, Any],
    fallback_index: int,
) -> dict[str, Any] | None:
    candidates = {
        str(asset.get("shot_id") or ""),
        str(asset.get("entity_id") or ""),
        str(asset.get("item_id") or ""),
    }
    for shot in shots:
        if str(shot.get("shot_id") or "") in candidates:
            return shot
    order = _int_value(asset.get("order") or asset.get("scene"), fallback_index)
    for shot in shots:
        if _int_value(shot.get("order"), 0) == order:
            return shot
    return shots[fallback_index - 1] if fallback_index - 1 < len(shots) else None


def _attach_output_assets_to_items(
    items: list[dict[str, Any]],
    assets: Any,
) -> list[dict[str, Any]]:
    asset_list = (
        [asset for asset in assets if isinstance(asset, dict)] if isinstance(assets, list) else []
    )
    for item in items:
        item_id = str(item.get("item_id") or "")
        item_assets = [
            asset
            for asset in asset_list
            if item_id
            in {
                str(asset.get("entity_id") or ""),
                str(asset.get("shot_id") or ""),
                str(asset.get("item_id") or ""),
            }
        ]
        if item_assets:
            item["output_assets"] = item_assets
            item["status"] = "ready"
    return items


def _video_media_items_from_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = storyboard_media_items_from_shots(shots)
    for item in items:
        item["item_type"] = "storyboard_video"
    return items


def _output_asset_list(output: dict[str, Any]) -> list[dict[str, Any]]:
    return extract_provider_output_assets(output)


def _known_assets(
    context: dict[str, Any], input_assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    assets = [asset for asset in input_assets if isinstance(asset, dict)]
    for value in context.values():
        assets.extend(_assets_from_value(value))
    return _dedupe_assets(assets)


def _assets_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        assets: list[dict[str, Any]] = []
        for item in value:
            assets.extend(_assets_from_value(item))
        return assets
    if not isinstance(value, dict):
        return []
    assets = []
    if value.get("asset_id") and (
        value.get("asset_type") or value.get("type") or value.get("local_path") or value.get("url")
    ):
        assets.append(value)
    assets.extend(extract_provider_output_assets(value))
    input_assets = value.get("input_assets")
    if isinstance(input_assets, (list, dict)):
        assets.extend(_assets_from_value(input_assets))
    structured = value.get("structured_output")
    if isinstance(structured, dict):
        assets.extend(_assets_from_value(structured))
    return assets


def _dedupe_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in assets:
        key = str(asset.get("asset_id") or asset.get("local_path") or asset.get("url") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(dict(asset))
    return deduped


def _scene_assets_from_flat_assets(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scene_output = context.get("scene_generation")
    candidates = []
    if isinstance(scene_output, dict):
        candidates.extend(extract_provider_output_assets(scene_output))
    candidates.extend(
        asset
        for asset in input_assets
        if _asset_role(asset) == "scene_reference"
        or str(asset.get("semantic_type") or "").startswith("scene")
    )
    return candidates


def _normalize_entity_assets(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    *,
    output_key: str,
    id_keys: tuple[str, ...],
    role_values: set[str],
    semantic_prefix: str,
    entity_key: str,
    fallback_prefix: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    output = context.get(output_key)
    if isinstance(output, dict):
        candidates.extend(extract_provider_output_assets(output))
    candidates.extend(input_assets)
    normalized = []
    seen: set[str] = set()
    for index, asset in enumerate(candidates, start=1):
        if not isinstance(asset, dict):
            continue
        role = _asset_role(asset)
        semantic = str(asset.get("semantic_type") or "")
        if role not in role_values and not semantic.startswith(semantic_prefix):
            continue
        entity_id = _first_entity_id(asset, id_keys) or f"{fallback_prefix}_{index:03d}"
        asset_id = str(asset.get("asset_id") or "")
        key = f"{entity_id}:{asset_id}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {**asset, entity_key: entity_id, "entity_id": asset.get("entity_id") or entity_id}
        )
    return normalized


def _embedded_output_assets(
    item: dict[str, Any],
    available: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output_assets = item.get("output_assets") or item.get("assets")
    if isinstance(output_assets, list):
        return [asset for asset in output_assets if isinstance(asset, dict)]
    asset_ids = _list_of_strings(item.get("asset_ids") or item.get("assetIds"))
    return [available[asset_id] for asset_id in asset_ids if asset_id in available]


def _canonical_scene_id(
    item: dict[str, Any],
    output_assets: list[dict[str, Any]],
    index: int,
) -> str:
    for source in (item, *(asset for asset in output_assets if isinstance(asset, dict))):
        for key in ("scene_id", "sceneId", "entity_id", "item_id"):
            value = source.get(key)
            if value not in (None, ""):
                return str(value)
    return f"scene_{index:03d}"


def _storyboard_image_assets(
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    storyboard = context.get("storyboard")
    assets = []
    if isinstance(storyboard, dict):
        assets.extend(extract_provider_output_assets(storyboard))
    assets.extend(
        asset
        for asset in input_assets
        if str(asset.get("semantic_type") or "") == "storyboard_image"
        or _asset_role(asset) == "storyboard"
    )
    return _dedupe_assets(assets)


def _storyboard_asset_for_shot(
    storyboard_assets: list[dict[str, Any]],
    shot: dict[str, Any],
    order: int,
) -> dict[str, Any] | None:
    shot_id = str(shot.get("shot_id") or "")
    for asset in storyboard_assets:
        if shot_id in {
            str(asset.get("shot_id") or ""),
            str(asset.get("entity_id") or ""),
            str(asset.get("item_id") or ""),
        }:
            return asset
    for asset in storyboard_assets:
        if _int_value(asset.get("order") or asset.get("scene"), 0) == order:
            return asset
    for asset in storyboard_assets:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id in {f"storyboard-image-{order}", f"storyboard_image_{order}"}:
            return asset
    if len(storyboard_assets) == 1 and order == 1:
        return storyboard_assets[0]
    return None


def _assets_by_id(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("asset_id")): asset for asset in assets if asset.get("asset_id")}


def _asset_role(asset: dict[str, Any]) -> str:
    return str(asset.get("role") or asset.get("asset_role") or "").strip()


def _first_entity_id(asset: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = asset.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return value
    return []


def _nested_value(source: dict[str, Any], *keys: str) -> Any:
    value: Any = source
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_text(source: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _duration_from_context(context: dict[str, Any]) -> int:
    try:
        return int(context.get("duration_seconds") or 30)
    except (TypeError, ValueError):
        return 30


def _video_item_duration(value: Any) -> int:
    duration = _int_value(value, 5)
    return 10 if duration > 5 else 5


def _error(rule: str, shot_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "error_code": SHOT_BINDING_ERROR_CODE,
        "shot_id": shot_id,
        "failed_rule": rule,
        **extra,
    }
