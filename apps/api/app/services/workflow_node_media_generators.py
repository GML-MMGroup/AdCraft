"""V1 workflow-node media generation compatibility helpers.

V2 runtime must not import or call these prompt builders. V2 media prompts flow
through V2ProviderExecutor and canonical provider_payload.provider_prompt.
"""

import re
from typing import Any

from app.services.script_beats import build_default_script_beats, ensure_script_beat_aliases
from app.services.workflow_node_media_items import (
    character_media_items as _character_media_items,
    product_media_items as _product_media_items,
    scene_media_items as _scene_media_items,
)
from app.services.workflow_node_output_contract import (
    extract_output_assets as _extract_output_assets,
    with_structured_output_and_assets as _with_structured_output_and_assets,
)
from app.services.workflow_provider_runtime import (
    accepted_reference_assets as _accepted_reference_assets,
)
from app.services.workflow_shot_bindings import (
    apply_storyboard_bindings_to_output,
    apply_storyboard_video_bindings_to_output,
    build_storyboard_binding_plan,
    build_storyboard_video_binding_plan,
    normalize_scene_assets,
)


def _generate_character_media_output(
    provider: Any,
    context: dict[str, Any],
    workflow_id: str,
) -> dict[str, Any]:
    character_design = {
        **_character_design_from_provider_prompt(
            str(context.get("provider_prompt") or ""),
            context,
        ),
        "reference_assets": _accepted_reference_assets(context),
    }
    media_items = _character_media_items(character_design, context)
    output = provider.generate_character_turnaround_images(character_design, workflow_id)
    return _with_media_items(output, media_items)


def _generate_product_media_output(
    provider: Any,
    context: dict[str, Any],
    workflow_id: str,
) -> dict[str, Any]:
    product_design = _product_design_from_provider_prompt(
        str(context.get("provider_prompt") or ""),
        context,
    )
    missing_reference = _product_reference_missing_output(product_design)
    if missing_reference is not None:
        return missing_reference
    media_items = _product_media_items(product_design, context)
    output = provider.generate_product_images(product_design, workflow_id)
    return _with_media_items(output, media_items)


def _product_reference_missing_output(
    product_design: dict[str, Any],
    fallback_reference_asset_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    reference_assets = product_design.get("reference_assets")
    available_asset_ids = (
        {
            str(asset.get("asset_id"))
            for asset in reference_assets
            if isinstance(asset, dict) and asset.get("asset_id")
        }
        if isinstance(reference_assets, list)
        else set()
    )
    available_asset_ids.update(fallback_reference_asset_ids or set())
    products = product_design.get("products")
    if not isinstance(products, list):
        return None
    missing_products = []
    for product in products:
        if not isinstance(product, dict):
            continue
        metadata = product.get("metadata") if isinstance(product.get("metadata"), dict) else {}
        if not metadata.get("product_reference_required"):
            continue
        requested_ids = (
            {
                str(asset_id)
                for asset_id in product.get("input_asset_ids", [])
                if str(asset_id).strip()
            }
            if isinstance(product.get("input_asset_ids"), list)
            else set()
        )
        if not requested_ids or not requested_ids.intersection(available_asset_ids):
            missing_products.append(
                str(product.get("item_id") or product.get("display_name") or "product")
            )
    if not missing_products:
        return None
    return {
        "status": "failed",
        "error_code": "product_reference_missing",
        "error": "product_reference_missing: product reference image is required.",
        "products": product_design.get("products", []),
        "missing_product_items": missing_products,
        "assets": [],
        "output_assets": [],
    }


def _product_reference_asset_ids_from_context(context: dict[str, Any]) -> set[str]:
    asset_ids: set[str] = set()
    for key in (
        "accepted_reference_assets",
        "reference_assets",
        "asset_references",
        "display_input_assets",
        "resolved_input_assets",
        "materialized_assets",
    ):
        value = context.get(key)
        if not isinstance(value, list):
            continue
        for asset in value:
            if not isinstance(asset, dict):
                continue
            role = asset.get("role") or asset.get("asset_role")
            semantic_type = asset.get("semantic_type")
            if role != "product_reference" and semantic_type != "product_reference":
                continue
            asset_id = asset.get("asset_id")
            if asset_id:
                asset_ids.add(str(asset_id))
    return asset_ids


def _product_design_from_provider_prompt(
    provider_prompt: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    reference_assets = _accepted_reference_assets(context)
    source_products = _product_sources_from_context(context)
    if not source_products:
        source_products = [
            {
                "item_id": "product-1",
                "display_name": _product_display_name_from_context(context),
                "prompt": provider_prompt,
                "input_asset_ids": _product_reference_asset_ids(reference_assets),
                "metadata": {
                    "product_reference_required": bool(reference_assets),
                    "product_identity_locked": bool(reference_assets),
                    "commercial_design_source": "director_context",
                },
            }
        ]
    multiple = len(source_products) > 1
    products = [
        _normalized_product_source(product, index, provider_prompt, reference_assets, multiple)
        for index, product in enumerate(source_products, start=1)
    ]
    return {
        "products": products,
        "reference_assets": reference_assets,
        "commercial_design": _product_commercial_design_context(context),
    }


def _product_commercial_design_context(context: dict[str, Any]) -> dict[str, Any]:
    commercial_design = context.get("commercial_design")
    if isinstance(commercial_design, dict):
        return commercial_design
    director = context.get("director_context_summary")
    if isinstance(director, dict) and isinstance(director.get("commercial_design"), dict):
        return dict(director["commercial_design"])
    return {}


def _product_sources_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    media_items = _context_media_items(context, "product_image")
    if media_items:
        return media_items
    for key in ("product_generation", "product_output"):
        value = context.get(key)
        products = value.get("products") if isinstance(value, dict) else None
        if isinstance(products, list) and products:
            return [product for product in products if isinstance(product, dict)]
    products = context.get("products")
    if isinstance(products, list) and products:
        return [product for product in products if isinstance(product, dict)]
    return []


def _normalized_product_source(
    product: dict[str, Any],
    index: int,
    provider_prompt: str,
    reference_assets: list[dict[str, Any]],
    multiple: bool,
) -> dict[str, Any]:
    item_id = str(
        product.get("item_id")
        or product.get("product_id")
        or product.get("entity_id")
        or f"product-{index}"
    )
    prompt = _first_text(
        product,
        (
            "prompt",
            "productPrompt",
            "description",
        ),
    )
    if not prompt:
        prompt = "" if multiple else provider_prompt
    input_asset_ids = _list_of_strings(product.get("input_asset_ids"))
    if not input_asset_ids:
        input_asset_ids = _product_reference_asset_ids(reference_assets)
    metadata = product.get("metadata") if isinstance(product.get("metadata"), dict) else {}
    reference_required = bool(input_asset_ids or reference_assets)
    return {
        **product,
        "item_id": item_id,
        "item_type": "product_image",
        "order": _int_value(product.get("order"), index),
        "display_name": str(product.get("display_name") or f"Product image {index}"),
        "prompt": prompt,
        "input_asset_ids": input_asset_ids,
        "reference_mode": str(product.get("reference_mode") or "strict"),
        "status": str(product.get("status") or "waiting"),
        "metadata": {
            **metadata,
            "product_reference_required": bool(
                metadata.get("product_reference_required", reference_required)
            ),
            "product_identity_locked": bool(
                metadata.get("product_identity_locked", reference_required)
            ),
            "commercial_design_source": metadata.get(
                "commercial_design_source", "director_context"
            ),
        },
    }


def _product_reference_asset_ids(reference_assets: list[dict[str, Any]]) -> list[str]:
    return _dedupe_asset_ids(
        [
            str(asset.get("asset_id"))
            for asset in reference_assets
            if asset.get("role") == "product_reference" and asset.get("asset_id")
        ]
    )


def _product_display_name_from_context(context: dict[str, Any]) -> str:
    director = context.get("director_context_summary")
    ad_request = director.get("ad_request") if isinstance(director, dict) else None
    if isinstance(ad_request, dict) and ad_request.get("product_name"):
        return f"{ad_request['product_name']} hero image"
    return "Primary product hero image"


def _generate_scene_media_output(
    provider: Any,
    context: dict[str, Any],
    workflow_id: str,
) -> dict[str, Any]:
    scene_design = {
        **_scene_design_from_provider_prompt(
            str(context.get("provider_prompt") or ""),
            context,
        ),
        "reference_assets": _accepted_reference_assets(context),
    }
    media_items = _scene_media_items(scene_design, context)
    output = provider.generate_scene_reference_images(scene_design, workflow_id)
    output = _with_media_items(output, media_items)
    scene_assets = normalize_scene_assets(
        {"scene_generation": output},
        _extract_output_assets(output),
    )
    if scene_assets:
        output["scene_assets"] = scene_assets
    return output


def _generate_storyboard_media_output(
    provider: Any,
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    workflow_id: str,
    binding_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding_plan = binding_plan or build_storyboard_binding_plan(
        context,
        input_assets,
        str(context.get("provider_prompt") or ""),
    )
    storyboard_scenes = list(binding_plan.get("shots") or [])
    output = provider.generate_storyboard_images(
        storyboard_scenes,
        workflow_id,
        input_assets=input_assets,
        context=_storyboard_provider_context(
            context,
            {"reference_assets": _accepted_reference_assets(context)},
        ),
    )
    return apply_storyboard_bindings_to_output(output, binding_plan, input_assets)


def _generate_storyboard_video_media_output(
    provider: Any,
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    workflow_id: str,
    binding_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding_plan = binding_plan or build_storyboard_video_binding_plan(
        context,
        input_assets,
        str(context.get("provider_prompt") or ""),
    )
    storyboard_video_prompt = _storyboard_video_prompt_from_binding_plan(
        str(context.get("provider_prompt") or ""),
        context,
        input_assets,
        binding_plan,
    )
    output = provider.generate_storyboard_video(storyboard_video_prompt, workflow_id)
    return apply_storyboard_video_bindings_to_output(output, binding_plan, input_assets)


def _with_media_items(
    output: dict[str, Any],
    media_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not media_items:
        return output
    return {**output, "media_items": media_items}


def _character_design_from_provider_prompt(
    provider_prompt: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    source_characters = _character_sources_from_context(context)
    if not source_characters:
        source_characters = [
            {
                "name": "Main Character",
                "role": "Primary ad talent",
                "appearance": provider_prompt,
                "personality": "Approachable, expressive, and brand-aligned.",
            }
        ]
    multiple = len(source_characters) > 1
    characters = [
        _normalized_character_source(character, index, provider_prompt, multiple)
        for index, character in enumerate(source_characters, start=1)
    ]
    return {"characters": characters}


def _character_sources_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    media_items = _context_media_items(context, "character")
    if media_items:
        return media_items
    for key in ("character_design", "characters_output"):
        value = context.get(key)
        characters = value.get("characters") if isinstance(value, dict) else None
        if isinstance(characters, list) and characters:
            return [character for character in characters if isinstance(character, dict)]
    characters = context.get("characters")
    if isinstance(characters, list) and characters:
        return [character for character in characters if isinstance(character, dict)]
    return []


def _normalized_character_source(
    character: dict[str, Any],
    index: int,
    provider_prompt: str,
    multiple: bool,
) -> dict[str, Any]:
    character_id = str(
        character.get("item_id")
        or character.get("character_id")
        or character.get("roleId")
        or character.get("entity_id")
        or f"character-{index}"
    )
    appearance = _first_text(
        character,
        (
            "prompt",
            "appearance",
            "rolePrompt",
            "roleDescription",
            "description",
        ),
    )
    if not appearance:
        appearance = "" if multiple else provider_prompt
    return {
        **character,
        "character_id": character_id,
        "name": str(
            character.get("name")
            or character.get("roleName")
            or character.get("display_name")
            or f"Character {index}"
        ),
        "role": str(character.get("role") or character.get("roleDescription") or ""),
        "appearance": appearance,
        "personality": str(character.get("personality") or ""),
    }


def _scene_design_from_provider_prompt(
    provider_prompt: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    source_scenes = _scene_sources_from_context(context)
    if source_scenes:
        selected_scenes = source_scenes
    else:
        beats = _script_beats_from_context(context)
        if not beats:
            beats = build_default_script_beats(
                product_name="Product",
                desired_emotion="confident",
                duration_seconds=_duration_from_context(context),
            )
        selected_scenes = _distinct_scene_source_beats(beats)
    scenes = []
    multiple = len(selected_scenes) > 1
    for index, scene in enumerate(selected_scenes, start=1):
        scene_id = str(
            scene.get("item_id")
            or scene.get("scene_id")
            or scene.get("sceneId")
            or f"scene-reference-{index}"
        )
        scene_prompt = _scene_item_prompt(scene, provider_prompt, multiple)
        scenes.append(
            {
                **scene,
                "scene_id": scene_id,
                "order": _int_value(scene.get("order") or scene.get("sceneIndex"), index),
                "location": str(
                    scene.get("location")
                    or scene.get("sceneName")
                    or scene.get("location_hint")
                    or f"Distinct scene location {index}"
                ),
                "lighting": str(scene.get("lighting") or _lighting_for_scene(index)),
                "atmosphere": scene_prompt,
                "spatial_layout": str(
                    scene.get("spatial_layout")
                    or scene.get("spatialLayout")
                    or (
                        "Create a distinct layout, depth, surfaces, and background. "
                        f"Beat {scene.get('order') or index}: "
                        f"{scene.get('visual_action') or scene.get('visual') or ''}"
                    )
                ),
                "visual_action": str(
                    scene.get("visual_action")
                    or scene.get("visualAction")
                    or scene.get("visual")
                    or ""
                ),
                "input_asset_ids": _list_of_strings(scene.get("input_asset_ids")),
            }
        )
    return {"scenes": scenes}


def _scene_sources_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    media_items = _context_media_items(context, "scene")
    if media_items:
        return media_items
    for key in ("scene_design", "scene_output"):
        value = context.get(key)
        scenes = value.get("scenes") if isinstance(value, dict) else None
        if isinstance(scenes, list) and scenes:
            return [scene for scene in scenes if isinstance(scene, dict)]
    scenes = context.get("scenes")
    if isinstance(scenes, list) and scenes:
        return [scene for scene in scenes if isinstance(scene, dict)]
    return []


def _scene_item_prompt(
    scene: dict[str, Any],
    provider_prompt: str,
    multiple: bool,
) -> str:
    prompt = _first_text(
        scene,
        (
            "prompt",
            "scenePrompt",
            "atmosphere",
            "sceneDescription",
            "scene_intent",
            "visual_action",
            "visual",
        ),
    )
    if prompt:
        return prompt
    return "" if multiple else provider_prompt


def _first_text(source: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _context_media_items(context: dict[str, Any], item_type: str) -> list[dict[str, Any]]:
    items = context.get("media_items")
    if not isinstance(items, list):
        return []
    matching = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("item_type") or "") == item_type:
            matching.append(item)
    return matching


def _storyboard_sources_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    media_items = _context_media_items(context, "storyboard_image")
    if media_items:
        return media_items
    for key in ("storyboard", "storyboard_output"):
        value = context.get(key)
        if not isinstance(value, dict):
            continue
        scenes = value.get("scenes")
        if isinstance(scenes, list) and scenes:
            return [scene for scene in scenes if isinstance(scene, dict)]
        items = value.get("storyboardItems")
        if isinstance(items, list) and items:
            return [item for item in items if isinstance(item, dict)]
    scenes = context.get("scenes")
    if isinstance(scenes, list) and scenes:
        return [scene for scene in scenes if isinstance(scene, dict)]
    return []


def _storyboard_scene_prompt(
    scene: dict[str, Any],
    provider_prompt: str,
    multiple: bool,
    order: int,
) -> str:
    prompt = _first_text(
        scene,
        (
            "prompt",
            "visual",
            "storyboardImagePrompt",
            "shotDescription",
            "action",
            "product_action",
        ),
    )
    if prompt:
        return prompt
    if not multiple and provider_prompt:
        return provider_prompt
    return f"Storyboard keyframe for shot {order}."


def _video_scene_prompt(
    scene: dict[str, Any],
    provider_prompt: str,
    multiple: bool,
    order: int,
) -> str:
    prompt = _first_text(
        scene,
        (
            "storyboardVideoPrompt",
            "videoPrompt",
            "prompt",
            "visual",
            "storyboardImagePrompt",
            "shotDescription",
            "action",
            "product_action",
        ),
    )
    if prompt:
        return prompt
    if not multiple and provider_prompt:
        return provider_prompt
    return f"Storyboard video segment for shot {order}."


def _video_item_duration(value: Any) -> int:
    raw = value
    if raw is None:
        return 5
    try:
        duration = int(float(raw))
    except (TypeError, ValueError):
        return 5
    if duration <= 5:
        return 5
    return 10


def _storyboard_order(scene: dict[str, Any], fallback: int) -> int:
    for key in ("order", "shotIndex", "scene", "index"):
        try:
            return int(scene.get(key))
        except (TypeError, ValueError):
            continue
    return fallback


def _storyboard_scene_id(scene: dict[str, Any], order: int) -> str:
    return str(
        scene.get("scene_id") or scene.get("sceneId") or scene.get("item_id") or f"scene-{order}"
    )


def _storyboard_item_id(scene: dict[str, Any], order: int) -> str:
    return str(
        scene.get("item_id") or scene.get("shotId") or scene.get("entity_id") or f"shot-{order}"
    )


def _storyboard_video_item_id(scene: dict[str, Any], order: int) -> str:
    return str(
        scene.get("item_id") or scene.get("shotId") or scene.get("entity_id") or f"segment-{order}"
    )


def _reference_mode_from_context(context: dict[str, Any]) -> str:
    reference_policy = context.get("reference_policy")
    if isinstance(reference_policy, dict):
        reference_mode = reference_policy.get("reference_mode")
        if isinstance(reference_mode, str) and reference_mode.strip():
            return reference_mode
    reference_mode = context.get("reference_mode")
    return str(reference_mode) if isinstance(reference_mode, str) and reference_mode else "strict"


def _storyboard_scenes_from_provider_prompt(
    provider_prompt: str,
    context: dict[str, Any] | None = None,
    input_assets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    context = context or {}
    input_assets = input_assets or []
    structured_scenes = _structured_storyboard_scenes_from_context(context)
    if structured_scenes:
        multiple = len(structured_scenes) > 1
        return [
            _normalize_storyboard_scene(scene, index, input_assets, provider_prompt, multiple)
            for index, scene in enumerate(structured_scenes, start=1)
        ]

    beats = _script_beats_from_context(context)
    if not beats:
        beats = build_default_script_beats(
            product_name="Product",
            desired_emotion="confident",
            duration_seconds=_duration_from_context(context),
        )
    scenes = []
    multiple = len(beats) > 1
    for index, beat in enumerate(beats, start=1):
        scenes.append(
            _normalize_storyboard_scene(
                {
                    "order": beat.get("order") or index,
                    "scene_id": beat.get("scene_id") or _scene_reference_id_for_order(index),
                    "shot": _shot_for_beat(index),
                    "visual": (
                        f"{beat.get('scene_intent') or 'Storyboard beat'}: "
                        f"{beat.get('visual_action') or ''}"
                    ),
                    "text": beat.get("spoken_or_on_screen_text")
                    or _script_line({"subtitle_lines": []}, index),
                    "duration_seconds": beat.get("duration_seconds") or 6,
                    "camera": _camera_for_beat(index),
                    "action": beat.get("product_action") or "Keep the product action clear.",
                    "input_asset_ids": beat.get("input_asset_ids") or [],
                },
                index,
                input_assets,
                provider_prompt,
                multiple,
            )
        )
    return scenes


def _storyboard_provider_context(
    input_context: dict[str, Any],
    provider_context: dict[str, Any],
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "reference_assets": provider_context.get("reference_assets", []),
    }
    for key in (
        "reference_policy",
        "negative_prompt",
    ):
        if input_context.get(key) not in (None, "", [], {}):
            context[key] = input_context[key]
    return context


def _script_beats_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("script", "storyboard_script"):
        value = context.get(key)
        if isinstance(value, dict):
            beats = _script_beats_from_script(value)
            if beats:
                return beats
    resolved = context.get("resolved_input_context")
    if isinstance(resolved, dict):
        script = resolved.get("script")
        if isinstance(script, dict):
            beats = _script_beats_from_script(script)
            if beats:
                return beats
    return []


def _script_beats_from_script(script: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = ensure_script_beat_aliases(script)
    beats = normalized.get("shot_beats")
    return [beat for beat in beats if isinstance(beat, dict)] if isinstance(beats, list) else []


def _duration_from_context(context: dict[str, Any]) -> int:
    for value in (
        context.get("duration_seconds"),
        (context.get("script") or {}).get("duration_seconds")
        if isinstance(context.get("script"), dict)
        else None,
        (context.get("requirements") or {}).get("duration_seconds")
        if isinstance(context.get("requirements"), dict)
        else None,
    ):
        try:
            duration = int(value)
        except (TypeError, ValueError):
            continue
        if 15 <= duration <= 60:
            return duration
    return 30


def _distinct_scene_source_beats(beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_locations: set[str] = set()
    for beat in beats:
        location = str(beat.get("location_hint") or "").strip().lower()
        if location and location in seen_locations:
            continue
        if location:
            seen_locations.add(location)
        selected.append(beat)
        if len(selected) >= 3:
            break
    if len(selected) >= 3:
        return selected
    for beat in beats:
        if beat not in selected:
            selected.append(beat)
        if len(selected) >= 3:
            break
    while len(selected) < 3:
        selected.append(
            {
                "order": len(selected) + 1,
                "scene_intent": f"Additional distinct scene {len(selected) + 1}",
                "location_hint": f"Distinct commercial environment {len(selected) + 1}",
                "visual_action": "Provide a visually different setting for storyboard coverage.",
            }
        )
    return selected


def _structured_storyboard_scenes_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    return _storyboard_sources_from_context(context)


def _normalize_storyboard_scene(
    scene: dict[str, Any],
    fallback_order: int,
    input_assets: list[dict[str, Any]],
    provider_prompt: str,
    multiple: bool = False,
) -> dict[str, Any]:
    order = _storyboard_order(scene, fallback_order)
    input_asset_ids = _storyboard_scene_asset_ids(scene, order, input_assets)
    scene_id = _storyboard_scene_id(scene, order)
    if not scene_id:
        scene_id = _scene_id_from_asset_ids(input_asset_ids) or _scene_reference_id_for_order(order)
    return {
        "item_id": _storyboard_item_id(scene, order),
        "order": order,
        "scene_id": scene_id,
        "shot": str(scene.get("shot") or _shot_for_beat(order)),
        "visual": _storyboard_scene_prompt(scene, provider_prompt, multiple, order),
        "text": str(scene.get("text") or scene.get("spoken_or_on_screen_text") or ""),
        "dialogue": scene.get("dialogue"),
        "duration_seconds": _int_value(scene.get("duration_seconds"), 6),
        "camera": str(scene.get("camera") or _camera_for_beat(order)),
        "action": str(scene.get("action") or scene.get("product_action") or ""),
        "input_asset_ids": input_asset_ids,
    }


def _storyboard_scene_asset_ids(
    scene: dict[str, Any],
    order: int,
    input_assets: list[dict[str, Any]],
) -> list[str]:
    known_asset_ids = {
        str(asset.get("asset_id"))
        for asset in input_assets
        if isinstance(asset.get("asset_id"), str) and str(asset.get("asset_id")).strip()
    }
    raw_ids = scene.get("input_asset_ids")
    if isinstance(raw_ids, list) and raw_ids:
        return _dedupe_asset_ids([str(asset_id) for asset_id in raw_ids])

    text = " ".join(
        str(scene.get(key) or "") for key in ("scene_id", "visual", "text", "action", "shot")
    )
    ids = _asset_ids_mentioned_in_text(text)
    scene_id = str(scene.get("scene_id") or "").strip()
    if scene_id:
        ids.append(_scene_reference_id(scene_id))
    if not ids:
        ids.append(_scene_reference_id_for_order(order))
    product_ids = [
        str(asset.get("asset_id"))
        for asset in input_assets
        if asset.get("role") == "product_reference" and asset.get("asset_id")
    ]
    allowed_ids = [
        asset_id for asset_id in ids if not known_asset_ids or asset_id in known_asset_ids
    ]
    return _dedupe_asset_ids([*product_ids, *allowed_ids])


def _asset_ids_mentioned_in_text(text: str) -> list[str]:
    return _dedupe_asset_ids(
        [
            match.group(0)
            for match in re.finditer(
                r"(?:scene-reference|character-turnaround)-\d+|asset_[A-Za-z0-9_-]+",
                text,
            )
        ]
    )


def _scene_id_from_asset_ids(asset_ids: list[str]) -> str | None:
    for asset_id in asset_ids:
        if asset_id.startswith("scene-reference-"):
            return asset_id
    return None


def _scene_reference_id(scene_id: str) -> str:
    if scene_id.startswith("scene-reference-"):
        return scene_id
    match = re.search(r"(\d+)$", scene_id)
    if match:
        return f"scene-reference-{match.group(1)}"
    return scene_id


def _scene_reference_id_for_order(order: int) -> str:
    return f"scene-reference-{order}"


def _dedupe_asset_ids(asset_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for asset_id in asset_ids:
        normalized = str(asset_id).strip()
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


def _lighting_for_scene(index: int) -> str:
    options = [
        "Natural establishing light with clear spatial depth",
        "Bright product-reveal light with controlled highlights",
        "Warm lifestyle light with a distinct background palette",
    ]
    return options[(index - 1) % len(options)]


def _shot_for_beat(order: int) -> str:
    options = [
        "wide establishing keyframe",
        "medium product reveal keyframe",
        "close product action keyframe",
        "lifestyle proof keyframe",
        "hero CTA keyframe",
    ]
    return options[min(order - 1, len(options) - 1)]


def _camera_for_beat(order: int) -> str:
    options = [
        "stable wide composition",
        "clean push-in",
        "controlled close-up",
        "gentle lateral movement",
        "hero lock-off",
    ]
    return options[min(order - 1, len(options) - 1)]


def _storyboard_video_prompt_from_binding_plan(
    provider_prompt: str,
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
    binding_plan: dict[str, Any],
) -> dict[str, Any]:
    scene_prompts: list[dict[str, Any]] = []
    shots = [shot for shot in binding_plan.get("shots", []) if isinstance(shot, dict)]
    multiple = len(shots) > 1
    for index, shot in enumerate(shots, start=1):
        order = _storyboard_order(shot, index)
        duration_seconds = _video_item_duration(
            shot.get("duration_seconds") or shot.get("durationSeconds")
        )
        shot_id = str(shot.get("shot_id") or shot.get("item_id") or f"shot_{order:03d}")
        scene_prompts.append(
            {
                "item_id": shot_id,
                "shot_id": shot_id,
                "order": order,
                "scene_id": shot.get("primary_scene_id") or shot.get("scene_id") or "",
                "primary_scene_id": shot.get("primary_scene_id"),
                "scene_reference_ids": list(shot.get("scene_reference_ids") or []),
                "character_ids": list(shot.get("character_ids") or []),
                "product_reference_ids": list(shot.get("product_reference_ids") or []),
                "style_reference_ids": list(shot.get("style_reference_ids") or []),
                "no_scene_reason": shot.get("no_scene_reason"),
                "prompt": _video_scene_prompt(shot, provider_prompt, multiple, order),
                "duration_seconds": duration_seconds,
                "input_asset_ids": list(shot.get("input_asset_ids") or []),
                "input_assets": [
                    asset for asset in shot.get("input_assets", []) if isinstance(asset, dict)
                ],
                "source_storyboard_image": shot.get("source_storyboard_image"),
                "storyboard_asset_id": shot.get("storyboard_asset_id"),
                "metadata": shot.get("metadata") if isinstance(shot.get("metadata"), dict) else {},
            }
        )
    duration_seconds = sum(int(scene.get("duration_seconds") or 0) for scene in scene_prompts)
    reference_assets = context.get("reference_assets")
    return {
        "final_video_prompt": provider_prompt
        if len(scene_prompts) == 1
        else "Generate each storyboard video segment from its item-scoped prompt.",
        "input_assets": input_assets,
        "reference_assets": reference_assets if isinstance(reference_assets, list) else [],
        "scene_prompts": scene_prompts,
        "duration_seconds": duration_seconds,
        "aspect_ratio": context.get("aspect_ratio") or context.get("ratio") or "16:9",
        "output_resolution": context.get("output_resolution")
        or context.get("resolution")
        or "480p",
    }


def _storyboard_video_prompt_from_provider_prompt(
    provider_prompt: str,
    context: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    storyboard_scenes = _storyboard_sources_from_context(context)
    if not storyboard_scenes:
        storyboard_scenes = [
            {
                "order": beat.get("order") or index,
                "scene_id": beat.get("scene_id") or f"scene-{index}",
                "visual": beat.get("visual_action") or beat.get("scene_intent") or "",
                "duration_seconds": beat.get("duration_seconds"),
                "input_asset_ids": beat.get("input_asset_ids") or [],
            }
            for index, beat in enumerate(_script_beats_from_context(context), start=1)
        ]
    if not storyboard_scenes:
        storyboard_scenes = [
            {
                "order": 1,
                "scene_id": "scene-1",
                "visual": provider_prompt,
                "duration_seconds": context.get("duration_seconds") or 10,
                "input_asset_ids": [
                    asset["asset_id"] for asset in input_assets if asset.get("asset_id")
                ],
            }
        ]
    multiple = len(storyboard_scenes) > 1
    scene_prompts = []
    for index, scene in enumerate(storyboard_scenes, start=1):
        order = _storyboard_order(scene, index)
        input_asset_ids = _storyboard_video_scene_asset_ids(scene, order, input_assets)
        duration_seconds = _video_item_duration(
            scene.get("duration_seconds") or scene.get("durationSeconds")
        )
        scene_prompts.append(
            {
                "item_id": _storyboard_video_item_id(scene, order),
                "order": order,
                "scene_id": _storyboard_scene_id(scene, order),
                "prompt": _video_scene_prompt(scene, provider_prompt, multiple, order),
                "duration_seconds": duration_seconds,
                "input_asset_ids": input_asset_ids,
            }
        )
    duration_seconds = sum(int(scene.get("duration_seconds") or 0) for scene in scene_prompts)
    reference_assets = context.get("reference_assets")
    return {
        "final_video_prompt": provider_prompt
        if len(scene_prompts) == 1
        else "Generate each storyboard video segment from its item-scoped prompt.",
        "input_assets": input_assets,
        "reference_assets": reference_assets if isinstance(reference_assets, list) else [],
        "scene_prompts": scene_prompts,
        "duration_seconds": duration_seconds,
        "aspect_ratio": context.get("aspect_ratio") or context.get("ratio") or "16:9",
        "output_resolution": context.get("output_resolution")
        or context.get("resolution")
        or "480p",
    }


def _storyboard_video_scene_asset_ids(
    scene: dict[str, Any],
    order: int,
    input_assets: list[dict[str, Any]],
) -> list[str]:
    ids = _storyboard_scene_asset_ids(scene, order, input_assets)
    storyboard_asset_id = str(
        scene.get("storyboard_asset_id")
        or scene.get("storyboardImageAssetId")
        or f"storyboard-image-{order}"
    )
    available_ids = {
        str(asset.get("asset_id") or "")
        for asset in input_assets
        if str(asset.get("asset_id") or "").strip()
    }
    if storyboard_asset_id in available_ids:
        ids.append(storyboard_asset_id)
    return _dedupe_asset_ids(ids)


def _merge_prompt_optimization(
    media_output: dict[str, Any],
    optimization_output: dict[str, Any],
    node_type: str,
    workflow_id: str,
) -> dict[str, Any]:
    reference_policy = (
        optimization_output.get("reference_policy")
        if isinstance(optimization_output.get("reference_policy"), dict)
        else media_output.get("reference_policy")
    )
    optimization_payload = dict(optimization_output)
    if isinstance(reference_policy, dict):
        optimization_payload["reference_policy"] = reference_policy
    merged = {
        **media_output,
        "optimized_generation_prompt": optimization_payload["optimized_generation_prompt"],
        "provider_prompt": optimization_payload["provider_prompt"],
        "prompt_optimization": optimization_payload,
    }
    if isinstance(reference_policy, dict):
        merged["reference_policy"] = reference_policy
    return _with_structured_output_and_assets(merged, node_type, workflow_id)


def _script_line(script: dict[str, Any], index: int) -> str:
    lines = script.get("subtitle_lines")
    if isinstance(lines, list) and lines:
        return str(lines[min(index - 1, len(lines) - 1)])
    return str(script.get("hook") or script.get("body") or script.get("cta") or "")


generate_character_media_output = _generate_character_media_output
generate_product_media_output = _generate_product_media_output
product_reference_missing_output = _product_reference_missing_output
product_reference_asset_ids_from_context = _product_reference_asset_ids_from_context
product_design_from_provider_prompt = _product_design_from_provider_prompt
generate_scene_media_output = _generate_scene_media_output
generate_storyboard_media_output = _generate_storyboard_media_output
generate_storyboard_video_media_output = _generate_storyboard_video_media_output
scene_design_from_provider_prompt = _scene_design_from_provider_prompt
storyboard_scenes_from_provider_prompt = _storyboard_scenes_from_provider_prompt
storyboard_video_prompt_from_binding_plan = _storyboard_video_prompt_from_binding_plan
storyboard_video_prompt_from_provider_prompt = _storyboard_video_prompt_from_provider_prompt
merge_prompt_optimization = _merge_prompt_optimization
