import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.prompt_optimization import PromptOptimizationRequest
from app.schemas.workflow_revisions import WorkflowRevisionRequest, WorkflowRevisionState
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text_with_warnings
from app.services.prompt_optimizer_context import prompt_optimizer_context_summaries
from app.services.workflow_asset_contract import extract_provider_output_assets
from app.services.workflow_node_identity import ResolvedNodeIdentity
from app.services.workflow_prompt_optimizer import WorkflowPromptOptimizerError
from app.services.workflow_prompt_target_metadata import revision_provider_prompt_value
from app.services.workflow_revision_targets import (
    active_assets,
    asset_type_for_semantic,
    field_for_semantic,
    provider_target_context,
    revision_asset_root,
)
from app.tools.media import build_media_provider


def revision_prompt_request(
    identity: ResolvedNodeIdentity,
    active: dict[str, Any],
    target: dict[str, Any],
    request: WorkflowRevisionRequest,
    settings: Settings,
) -> PromptOptimizationRequest:
    input_context = (
        active.get("input_context") if isinstance(active.get("input_context"), dict) else {}
    )
    output = active.get("output") if isinstance(active.get("output"), dict) else {}
    sanitized_input_context, input_context_warnings = _sanitize_for_optimizer_request(input_context)
    sanitized_output, output_warnings = _sanitize_for_optimizer_request(output)
    sanitized_target, target_warnings = _sanitize_for_optimizer_request(target)
    sanitized_active_assets, active_asset_warnings = _sanitize_for_optimizer_request(
        active_assets(active)
    )
    media_type = asset_type_for_semantic(str(target.get("semantic_type") or ""))
    asset_references = [item.model_dump(mode="json") for item in request.asset_references]
    sanitized_asset_references, asset_reference_warnings = _sanitize_for_optimizer_request(
        asset_references
    )
    summaries = prompt_optimizer_context_summaries(
        settings=settings,
        workflow_id=identity.workflow_id,
        node_id=identity.node_id,
        node_type=identity.node_type,
        input_context=sanitized_input_context,
        media_type=media_type,
        media_mode=settings.media_mode,
        request_provider=request.provider,
        reference_mode=request.reference_mode,
        asset_references=sanitized_asset_references,
    )
    return PromptOptimizationRequest(
        workflow_id=identity.workflow_id,
        node_id=identity.node_id,
        node_type=identity.node_type,
        mode="local_revision",
        user_prompt=request.instruction,
        system_suggested_prompt=_string_value(sanitized_input_context, "system_suggested_prompt"),
        materialized_prompt=_string_value(sanitized_input_context, "materialized_prompt"),
        override_prompt=_string_value(sanitized_input_context, "override_prompt"),
        director_context=_director_context_from_active(sanitized_input_context),
        resolved_input_context={
            **sanitized_input_context,
            "revision_instruction": request.instruction,
            "target": sanitized_target,
        },
        resolved_input_assets=sanitized_active_assets,
        upstream_structured_outputs={
            "active_output": sanitized_output,
            "structured_output": sanitized_output.get("structured_output", {}),
        },
        asset_references=sanitized_asset_references,
        provider_media_type=media_type,
        provider_capability_summary=summaries.provider_capability_summary,
        reference_policy_summary=summaries.reference_policy_summary,
        identity_certification_summary=summaries.identity_certification_summary,
        selected_provider=summaries.selected_provider,
        target_context=sanitized_target,
        allow_optimizer_fallback=request.allow_optimizer_fallback,
        warnings=[
            *input_context_warnings,
            *output_warnings,
            *target_warnings,
            *active_asset_warnings,
            *asset_reference_warnings,
        ],
    )


def _director_context_from_active(input_context: dict[str, Any]) -> dict[str, Any]:
    for key in ("director_context", "director_context_summary"):
        value = input_context.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _string_value(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _sanitize_for_optimizer_request(value: Any) -> tuple[Any, list[dict[str, Any]]]:
    try:
        return sanitize_context_for_llm_text_with_warnings(value)
    except Exception as exc:
        raise WorkflowPromptOptimizerError(
            "llm_context_sanitization_failed",
            "Failed to sanitize prompt optimizer context for LLM text.",
        ) from exc


def optimized_revision_prompt(
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    request: WorkflowRevisionRequest,
) -> str:
    return (
        f"Optimize local revision for {identity.node_type} {target['entity_id']} "
        f"({target['semantic_type']}): {request.instruction or ''}".strip()
    )


def provider_revision_prompt(
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    request: WorkflowRevisionRequest,
) -> str:
    return (
        f"Provider prompt for {identity.node_type} local revision. "
        f"Target {target['entity_id']} {target['semantic_type']}. "
        f"Instruction: {request.instruction or ''}"
    )


def provider_revision_asset(
    settings: Settings,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    state: WorkflowRevisionState,
    request: WorkflowRevisionRequest,
    active: dict[str, Any],
) -> dict[str, Any]:
    assets = provider_revision_assets(settings, identity, target, state, request, active)
    if not assets:
        raise ValueError("Local revision provider did not return a usable asset.")
    return assets[0]


def provider_revision_assets(
    settings: Settings,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    state: WorkflowRevisionState,
    request: WorkflowRevisionRequest,
    active: dict[str, Any],
    *,
    provider_factory: Any = build_media_provider,
) -> list[dict[str, Any]]:
    provider = provider_factory(settings)
    provider_output = call_revision_provider(provider, identity, target, state, request, active)
    candidates = select_provider_revision_assets_for_identity(
        provider_output, identity, target, request.mode
    )
    if not candidates:
        raise ValueError("Local revision provider did not return a usable asset.")
    return [
        normalize_provider_revision_asset(
            settings.media_data_dir,
            identity,
            state,
            target,
            candidate,
            provider_output,
        )
        for candidate in candidates
    ]


def call_revision_provider(
    provider: Any,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    state: WorkflowRevisionState,
    request: WorkflowRevisionRequest,
    active: dict[str, Any],
) -> dict[str, Any]:
    prompt = revision_provider_prompt_value(request, state, target)
    context = {
        "workflow_id": identity.workflow_id,
        "node_id": identity.node_id,
        "node_type": identity.node_type,
        "target": provider_target_context(target),
        "target_item": target.get("item") if isinstance(target.get("item"), dict) else {},
        "target_asset": target.get("asset") if isinstance(target.get("asset"), dict) else {},
        "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
        "providerRevisionPrompt": state.providerRevisionPrompt,
        "revisionRequirements": state.revisionRequirements,
        "revision_instruction": request.instruction,
    }
    if identity.node_type == "product-generation":
        return _call_product_revision_provider(provider, identity, target, request, prompt, context)
    if identity.node_type == "character-generation":
        return _call_character_revision_provider(provider, identity, target, prompt, context)
    if identity.node_type == "scene-generation":
        return _call_scene_revision_provider(provider, identity, target, prompt, context)
    if identity.node_type == "storyboard":
        return _call_storyboard_revision_provider(
            provider, identity, target, active, prompt, context
        )
    if identity.node_type == "storyboard-video-generation":
        return _call_storyboard_video_revision_provider(
            provider, identity, target, active, prompt, context, state
        )
    if identity.node_type == "bgm":
        bgm_plan = {
            "prompt": prompt,
            "mood": request.provider_hints.get("mood") or "revision",
            "duration_seconds": _target_duration(active),
            "revision_context": context,
        }
        return provider.generate_audio_assets({}, {}, bgm_plan, identity.workflow_id)
    raise ValueError(f"local revision node_type is not supported: {identity.node_type}")


def _call_product_revision_provider(
    provider: Any,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    request: WorkflowRevisionRequest,
    prompt: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return provider.generate_product_images(
        {
            "products": [
                {
                    "item_id": target["entity_id"],
                    "product_id": target["entity_id"],
                    "display_name": target["entity_id"],
                    "prompt": prompt,
                    "reference_mode": request.reference_mode,
                    "input_asset_ids": [],
                    "metadata": {
                        "product_reference_required": False,
                        "product_identity_locked": False,
                        "commercial_design_source": "local_revision",
                    },
                    "revision_context": context,
                }
            ],
            "reference_assets": [],
        },
        identity.workflow_id,
    )


def _call_character_revision_provider(
    provider: Any,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return provider.generate_character_turnaround_images(
        {
            "characters": [
                {
                    "id": target["entity_id"],
                    "name": target["entity_id"],
                    "appearance": prompt,
                    "prompt": prompt,
                    "revision_context": context,
                }
            ]
        },
        identity.workflow_id,
    )


def _call_scene_revision_provider(
    provider: Any,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return provider.generate_scene_reference_images(
        {
            "scenes": [
                {
                    "scene_id": target["entity_id"],
                    "name": target["entity_id"],
                    "visual_description": prompt,
                    "prompt": prompt,
                    "revision_context": context,
                }
            ]
        },
        identity.workflow_id,
    )


def _call_storyboard_revision_provider(
    provider: Any,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    active: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    scene = {
        "order": _target_order(target),
        "scene_id": target["entity_id"],
        "shot_id": target["entity_id"],
        "prompt": prompt,
        "description": prompt,
        "duration_seconds": _target_duration(active),
        "input_asset_ids": [],
    }
    return provider.generate_storyboard_images(
        [scene],
        identity.workflow_id,
        input_assets=[],
        context=context,
    )


def _call_storyboard_video_revision_provider(
    provider: Any,
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    active: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    state: WorkflowRevisionState,
) -> dict[str, Any]:
    segment = {
        "order": _target_order(target),
        "scene_id": target["entity_id"],
        "shot_id": target["entity_id"],
        "prompt": prompt,
        "duration_seconds": _target_duration(active),
        "input_asset_ids": [],
    }
    return provider.generate_storyboard_video(
        {
            "scene_prompts": [segment],
            "duration_seconds": segment["duration_seconds"],
            "input_assets": [],
            "providerRevisionPrompt": state.providerRevisionPrompt,
            "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
            "target_item": context["target_item"],
        },
        identity.workflow_id,
    )


def select_provider_revision_asset(
    provider_output: dict[str, Any],
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
) -> dict[str, Any] | None:
    selected = select_provider_revision_assets_for_identity(
        provider_output, identity, target, "regenerate_asset"
    )
    return selected[0] if selected else None


def select_provider_revision_assets_for_identity(
    provider_output: dict[str, Any],
    identity: ResolvedNodeIdentity,
    target: dict[str, Any],
    mode: str,
) -> list[dict[str, Any]]:
    return select_provider_revision_assets(
        provider_output,
        node_type=identity.node_type,
        target=target,
        mode=mode,
    )


def select_provider_revision_assets(
    provider_output: dict[str, Any],
    *,
    node_type: str,
    target: dict[str, Any],
    mode: str,
) -> list[dict[str, Any]]:
    semantic_type = str(target.get("semantic_type") or "")
    candidates = dedupe_provider_revision_candidates(provider_revision_candidates(provider_output))
    if not candidates:
        return []
    if mode == "regenerate_entity":
        matches = _entity_revision_matches(
            candidates,
            node_type=node_type,
            target=target,
            target_semantic=semantic_type,
        )
        if matches:
            return dedupe_provider_revision_candidates(matches)
    bgm_match = _bgm_revision_match(candidates, node_type, target)
    if bgm_match:
        return [bgm_match]
    semantic_match = _semantic_revision_match(
        candidates, node_type=node_type, target=target, target_semantic=semantic_type
    )
    if semantic_match:
        return [semantic_match]
    order_match = _order_revision_match(candidates, node_type=node_type, target=target)
    if order_match:
        return [order_match]
    return [fill_provider_revision_target(node_type, deepcopy(candidates[0]), target)]


def _entity_revision_matches(
    candidates: list[dict[str, Any]],
    *,
    node_type: str,
    target: dict[str, Any],
    target_semantic: str,
) -> list[dict[str, Any]]:
    entity_id = str(target.get("entity_id") or "")
    supported_semantics = node_revision_entity_semantic_types(node_type)
    matches: list[dict[str, Any]] = []
    for asset in candidates:
        candidate = deepcopy(asset)
        candidate_semantic = canonical_revision_semantic(
            node_type,
            provider_asset_semantic(candidate),
            target_semantic,
        )
        candidate_entity_id = provider_asset_entity_id(candidate)
        if candidate_semantic:
            candidate["semantic_type"] = candidate_semantic
        if candidate_entity_id == entity_id or (
            not candidate_entity_id and candidate_semantic in supported_semantics
        ):
            matches.append(fill_provider_revision_target(node_type, candidate, target))
    return matches


def _bgm_revision_match(
    candidates: list[dict[str, Any]],
    node_type: str,
    target: dict[str, Any],
) -> dict[str, Any] | None:
    if node_type != "bgm":
        return None
    for asset in candidates:
        if str(asset.get("asset_id") or "") == "bgm":
            return fill_provider_revision_target(node_type, deepcopy(asset), target)
    return None


def _semantic_revision_match(
    candidates: list[dict[str, Any]],
    *,
    node_type: str,
    target: dict[str, Any],
    target_semantic: str,
) -> dict[str, Any] | None:
    for asset in candidates:
        if (
            canonical_revision_semantic(
                node_type,
                provider_asset_semantic(asset),
                target_semantic,
            )
            == target_semantic
        ):
            return fill_provider_revision_target(node_type, deepcopy(asset), target)
    return None


def _order_revision_match(
    candidates: list[dict[str, Any]],
    *,
    node_type: str,
    target: dict[str, Any],
) -> dict[str, Any] | None:
    order = _target_order(target)
    for asset in candidates:
        if _target_order({"asset": asset, "entity_id": target["entity_id"]}) == order:
            return fill_provider_revision_target(node_type, deepcopy(asset), target)
    return None


def provider_revision_candidates(provider_output: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = extract_provider_output_assets(provider_output)
    if _looks_like_asset(provider_output):
        candidates.append(provider_output)
    return candidates


def dedupe_provider_revision_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = provider_revision_candidate_key(candidate)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(deepcopy(candidate))
    return deduped


def provider_revision_candidate_key(candidate: dict[str, Any]) -> str:
    for key in ("asset_id", "local_path", "public_url", "remote_url", "url", "uri"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value}"
    return ""


def provider_asset_semantic(asset: dict[str, Any]) -> str:
    return str(asset.get("semantic_type") or asset.get("role") or asset.get("kind") or "")


def canonical_revision_semantic(
    node_type: str,
    raw_semantic: str,
    target_semantic: str | None = None,
) -> str:
    raw = str(raw_semantic or "").strip()
    target = str(target_semantic or "").strip()
    semantic_aliases = {
        "character-generation": {
            "character_turnaround": "character_main",
            "character_main_image": "character_main",
            "character_avatar": "character_face_id",
            "character_face": "character_face_id",
            "character_face_id": "character_face_id",
            "character_three_view": "character_three_view",
            "character_concept": "character_concept",
        },
        "scene-generation": {
            "scene_reference": "scene_main",
            "scene_main_image": "scene_main",
            "scene_main": "scene_main",
            "scene_multi_view": "scene_multi_view",
        },
    }
    supported = node_revision_entity_semantic_types(node_type)
    mapped = semantic_aliases.get(node_type, {}).get(raw, raw)
    if mapped in supported:
        return mapped
    if raw in supported:
        return raw
    if target:
        return target
    return raw


def provider_asset_entity_id(asset: dict[str, Any]) -> str:
    for key in (
        "entity_id",
        "shotId",
        "shot_id",
        "sceneId",
        "scene_id",
        "roleId",
        "role_id",
        "characterId",
        "character_id",
        "productId",
        "product_id",
        "id",
    ):
        value = asset.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def node_revision_entity_semantic_types(node_type: str) -> set[str]:
    return {
        "product-generation": {"product_image"},
        "character-generation": {
            "character_main",
            "character_face_id",
            "character_three_view",
            "character_concept",
        },
        "scene-generation": {"scene_main", "scene_multi_view"},
        "storyboard": {"storyboard_image"},
        "storyboard-video-generation": {"storyboard_video"},
        "bgm": {"bgm"},
    }.get(node_type, set())


def fill_provider_revision_target(
    node_type: str,
    provider_asset: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    candidate = deepcopy(provider_asset)
    semantic_type = canonical_revision_semantic(
        node_type,
        provider_asset_semantic(candidate),
        str(target.get("semantic_type") or ""),
    )
    entity_id = provider_asset_entity_id(candidate) or str(target.get("entity_id") or "")
    if semantic_type:
        candidate["semantic_type"] = semantic_type
    if entity_id and not provider_asset_entity_id(candidate):
        candidate["entity_id"] = entity_id
    target_field = str(candidate.get("target_field") or field_for_semantic(candidate) or "")
    if not target_field and semantic_type == str(target.get("semantic_type") or ""):
        target_field = str(target.get("target_field") or "")
    if target_field:
        candidate["target_field"] = target_field
    return candidate


def normalize_provider_revision_asset(
    data_dir: Path,
    identity: ResolvedNodeIdentity,
    state: WorkflowRevisionState,
    target: dict[str, Any],
    provider_asset: dict[str, Any],
    provider_output: dict[str, Any],
) -> dict[str, Any]:
    target_semantic = str(target.get("semantic_type") or state.semantic_type or "")
    provider_semantic = canonical_revision_semantic(
        identity.node_type,
        provider_asset_semantic(provider_asset),
        target_semantic,
    )
    canonical_target_semantic = canonical_revision_semantic(
        identity.node_type,
        target_semantic,
        target_semantic,
    )
    semantic_type = _provider_revision_semantic(
        state=state,
        target=target,
        provider_semantic=provider_semantic,
        canonical_target_semantic=canonical_target_semantic,
    )
    entity_id = (
        provider_asset_entity_id(provider_asset)
        or state.target_entity_id
        or str(target.get("entity_id") or "target")
    )
    asset_type = asset_type_for_semantic(semantic_type)
    asset_id = f"{identity.node_id}-{entity_id}-{semantic_type}-{state.revision_id}"
    metadata_path = (
        Path(revision_asset_root(identity.node_type))
        / identity.workflow_id
        / "revisions"
        / f"{asset_id}.json"
    )
    local_path = _first_string(provider_asset, "local_path", "uri")
    remote_url = _first_string(provider_asset, "remote_url", "url")
    source_item_id = str(state.target_entity_id or target.get("entity_id") or entity_id)
    prompt_used = str(
        state.metadata.get("source_item_prompt")
        or state.instruction
        or target.get("prompt")
        or revision_prompt_value(state)
        or provider_asset.get("prompt")
    )
    provider_prompt = str(
        state.providerRevisionPrompt
        or provider_asset.get("provider_prompt")
        or provider_asset.get("prompt")
        or ""
    )
    asset = _provider_revision_asset_payload(
        identity=identity,
        state=state,
        target=target,
        provider_asset=provider_asset,
        provider_output=provider_output,
        semantic_type=semantic_type,
        entity_id=entity_id,
        asset_type=asset_type,
        asset_id=asset_id,
        metadata_path=metadata_path,
        source_item_id=source_item_id,
        prompt_used=prompt_used,
        provider_prompt=provider_prompt,
    )
    _apply_revision_asset_paths(
        asset, local_path=local_path, remote_url=remote_url, metadata_path=metadata_path
    )
    output_path = data_dir / metadata_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return asset


def _provider_revision_semantic(
    *,
    state: WorkflowRevisionState,
    target: dict[str, Any],
    provider_semantic: str,
    canonical_target_semantic: str,
) -> str:
    if state.mode == "regenerate_entity":
        return (
            provider_semantic or canonical_target_semantic or str(target.get("semantic_type") or "")
        )
    return (
        canonical_target_semantic
        or state.semantic_type
        or str(target.get("semantic_type") or "")
        or provider_semantic
    )


def _provider_revision_asset_payload(
    *,
    identity: ResolvedNodeIdentity,
    state: WorkflowRevisionState,
    target: dict[str, Any],
    provider_asset: dict[str, Any],
    provider_output: dict[str, Any],
    semantic_type: str,
    entity_id: str,
    asset_type: str,
    asset_id: str,
    metadata_path: Path,
    source_item_id: str,
    prompt_used: str,
    provider_prompt: str,
) -> dict[str, Any]:
    return {
        **deepcopy(provider_asset),
        "asset_id": asset_id,
        "provider_asset_id": provider_asset.get("asset_id"),
        "workflow_id": identity.workflow_id,
        "node_id": identity.node_id,
        "source_node_id": identity.node_id,
        "node_type": identity.node_type,
        "run_id": state.revision_id,
        "asset_type": asset_type,
        "type": asset_type,
        "media_type": asset_type,
        "semantic_type": semantic_type,
        "entity_id": entity_id,
        "source_item_id": source_item_id,
        "prompt": prompt_used,
        "provider_prompt": provider_prompt,
        "target_field": normalize_provider_target_field(
            state, target, provider_asset, semantic_type
        ),
        "metadata_path": metadata_path.as_posix(),
        "is_active": True,
        "is_archived": False,
        "status": str(provider_asset.get("status") or provider_output.get("status") or "ready"),
        "download_status": str(provider_asset.get("download_status") or "ready"),
        "metadata": {
            **(
                provider_asset.get("metadata")
                if isinstance(provider_asset.get("metadata"), dict)
                else {}
            ),
            "revision_id": state.revision_id,
            "source_item_id": source_item_id,
            "entity_id": entity_id,
            "semantic_type": semantic_type,
            "prompt": prompt_used,
            "provider_prompt": provider_prompt,
            "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
            "providerRevisionPrompt": state.providerRevisionPrompt,
            "provider_output": compact_provider_output(provider_output),
        },
    }


def _apply_revision_asset_paths(
    asset: dict[str, Any],
    *,
    local_path: str,
    remote_url: str,
    metadata_path: Path,
) -> None:
    if local_path:
        asset["local_path"] = local_path
        asset["uri"] = local_path
    elif remote_url:
        asset["uri"] = remote_url
    else:
        asset["uri"] = metadata_path.as_posix()
    if remote_url:
        asset["remote_url"] = remote_url
        asset["url"] = remote_url


def revision_prompt_value(state: WorkflowRevisionState) -> str:
    return str(
        state.providerRevisionPrompt or state.optimizedRevisionPrompt or state.instruction or ""
    )


def normalize_provider_target_field(
    state: WorkflowRevisionState,
    target: dict[str, Any],
    provider_asset: dict[str, Any],
    semantic_type: str,
) -> str:
    provider_field = str(provider_asset.get("target_field") or "")
    semantic_field = field_for_semantic({"semantic_type": semantic_type})
    if state.mode == "regenerate_entity":
        return (
            provider_field
            or semantic_field
            or state.target_field
            or str(target.get("target_field") or "")
        )
    return (
        state.target_field
        or str(target.get("target_field") or "")
        or provider_field
        or semantic_field
    )


def _looks_like_asset(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("asset_id", "local_path", "remote_url", "url", "uri"))


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def compact_provider_output(provider_output: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in provider_output.items()
        if key not in {"assets", "output_assets", "segments"}
    }


def _target_order(target: dict[str, Any]) -> int:
    asset = target.get("asset") if isinstance(target.get("asset"), dict) else {}
    for key in ("order", "scene", "shot_order"):
        value = asset.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    entity_id = str(target.get("entity_id") or "")
    digits = "".join(character for character in entity_id if character.isdigit())
    return max(int(digits), 1) if digits else 1


def _target_duration(active: dict[str, Any]) -> int:
    output = active.get("output")
    if isinstance(output, dict):
        for key in ("duration_seconds", "duration"):
            value = output.get(key)
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return 5


_revision_prompt_request = revision_prompt_request
_optimized_revision_prompt = optimized_revision_prompt
_provider_revision_prompt = provider_revision_prompt
_provider_revision_asset = provider_revision_asset
_provider_revision_assets = provider_revision_assets
_call_revision_provider = call_revision_provider
_select_provider_revision_asset = select_provider_revision_asset
_select_provider_revision_assets = select_provider_revision_assets_for_identity
_provider_revision_candidates = provider_revision_candidates
_dedupe_provider_revision_candidates = dedupe_provider_revision_candidates
_provider_revision_candidate_key = provider_revision_candidate_key
_provider_asset_semantic = provider_asset_semantic
_canonical_revision_semantic = canonical_revision_semantic
_provider_asset_entity_id = provider_asset_entity_id
_node_revision_entity_semantic_types = node_revision_entity_semantic_types
_fill_provider_revision_target = fill_provider_revision_target
_normalize_provider_revision_asset = normalize_provider_revision_asset
_normalize_provider_target_field = normalize_provider_target_field
