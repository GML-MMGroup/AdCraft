from copy import deepcopy
from pathlib import Path
from typing import Any

from app.schemas.workflow_revisions import WorkflowRevisionState
from app.services.workflow_asset_history import load_node_asset_history
from app.services.workflow_item_prompt_utils import (
    item_prompt_from_payload,
    target_item_context_from_active,
)
from app.services.workflow_asset_contract import legacy_output_assets_from_payload
from app.services.workflow_node_identity import ResolvedNodeIdentity


def active_asset_ids_for_revision_target(
    data_dir: Path,
    state: WorkflowRevisionState,
) -> list[str]:
    assets = [
        asset
        for asset in load_node_asset_history(data_dir, state.workflow_id, state.node_id)
        if asset_entity_id(asset) == (state.target_entity_id or "")
        and str(asset.get("semantic_type") or "") == (state.semantic_type or "")
        and asset.get("is_active") is True
        and asset.get("asset_id")
    ]
    if assets:
        return [str(asset["asset_id"]) for asset in assets]
    if state.acceptance_status == "accepted":
        accepted_asset_ids = revision_candidate_asset_ids(state)
        if accepted_asset_ids:
            return accepted_asset_ids
    return previous_active_asset_ids(state)


def resolve_revision_target(active: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    assets = active_assets(active)
    target_asset_id = str(revision.get("target_asset_id") or "")
    if target_asset_id:
        matches = [asset for asset in assets if asset.get("asset_id") == target_asset_id]
        if not matches:
            raise ValueError(f"target_asset_id not found: {target_asset_id}")
        return target_payload(matches[0], revision, active)
    target_entity_id = str(revision.get("target_entity_id") or "")
    semantic_type = str(revision.get("semantic_type") or "")
    if target_entity_id and semantic_type:
        return _resolve_entity_semantic_target(
            assets,
            target_entity_id=target_entity_id,
            semantic_type=semantic_type,
            revision=revision,
            active=active,
        )
    target_field = str(revision.get("target_field") or "")
    if target_field:
        matches = [asset for asset in assets if asset.get("target_field") == target_field]
        if len(matches) == 1:
            return target_payload(matches[0], revision, active)
    raise ValueError(
        "local revision target must include target_asset_id or target_entity_id + semantic_type."
    )


def _resolve_entity_semantic_target(
    assets: list[dict[str, Any]],
    *,
    target_entity_id: str,
    semantic_type: str,
    revision: dict[str, Any],
    active: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        asset
        for asset in assets
        if asset_entity_id(asset) == target_entity_id
        and str(asset.get("semantic_type") or "") == semantic_type
    ]
    active_matches = [asset for asset in matches if asset.get("is_active") is not False]
    if len(active_matches) == 1:
        return target_payload(active_matches[0], revision, active)
    if len(matches) == 1:
        return target_payload(matches[0], revision, active)
    if not matches:
        raise ValueError("local revision target not found.")
    raise ValueError("local revision target is ambiguous; provide target_asset_id.")


def ensure_regenerate_target(
    identity: ResolvedNodeIdentity,
    active: dict[str, Any],
    request: Any,
) -> None:
    try:
        resolve_revision_target(active, request.model_dump(mode="json", exclude_none=True))
    except ValueError as exc:
        raise target_resolution_error(identity, str(exc)) from exc


def target_resolution_error(
    identity: ResolvedNodeIdentity,
    message: str,
) -> ValueError:
    code = (
        "local_revision_target_ambiguous"
        if "ambiguous" in message
        else "local_revision_target_not_found"
    )
    error = ValueError(message)
    error.detail = {
        "code": code,
        "message": message,
        "workflow_id": identity.workflow_id,
        "node_id": identity.node_id,
        "node_type": identity.node_type,
    }
    error.status_code = 422
    return error


def target_payload(
    asset: dict[str, Any],
    revision: dict[str, Any],
    active: dict[str, Any],
) -> dict[str, Any]:
    semantic_type = str(revision.get("semantic_type") or asset.get("semantic_type") or "")
    entity_id = str(revision.get("target_entity_id") or asset_entity_id(asset))
    item = target_item_context_from_active(active, entity_id)
    prompt = item_prompt_from_payload(item) or item_prompt_from_payload(asset)
    return {
        "asset_id": str(asset.get("asset_id") or ""),
        "entity_id": entity_id,
        "semantic_type": semantic_type,
        "target_field": str(
            field_for_semantic_type(semantic_type)
            or revision.get("target_field")
            or asset.get("target_field")
            or field_for_semantic(asset)
        ),
        "uri": asset_uri(asset),
        "asset": deepcopy(asset),
        "item": item,
        "prompt": prompt,
    }


def provider_target_context(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": target.get("asset_id"),
        "entity_id": target.get("entity_id"),
        "semantic_type": target.get("semantic_type"),
        "target_field": target.get("target_field"),
        "uri": target.get("uri"),
        "prompt": target.get("prompt"),
    }


def active_assets(active: dict[str, Any]) -> list[dict[str, Any]]:
    assets = legacy_output_assets_from_payload(active)
    seen = set()
    deduped = []
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id and asset_id in seen:
            continue
        if asset_id:
            seen.add(asset_id)
        deduped.append(deepcopy(asset))
    return deduped


def asset_entity_id(asset: dict[str, Any]) -> str:
    for key in ("entity_id", "shotId", "shot_id", "sceneId", "scene_id", "roleId", "role_id", "id"):
        value = asset.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def asset_uri(asset: dict[str, Any]) -> str:
    for key in ("uri", "local_path", "public_url", "remote_url", "url", "metadata_path"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def field_for_semantic(asset: dict[str, Any]) -> str:
    return field_for_semantic_type(str(asset.get("semantic_type") or ""))


def field_for_semantic_type(semantic_type: str) -> str:
    return {
        "product_image": "productImageUri",
        "character_main": "roleMainImageUri",
        "character_face_id": "roleFaceIdImageUri",
        "character_three_view": "roleThreeViewImageUri",
        "character_concept": "roleConceptImageUri",
        "scene_main": "sceneMainImageUri",
        "scene_multi_view": "sceneMultiViewImageUri",
        "storyboard_image": "storyboardImageUri",
        "storyboard_video": "storyboardVideoUri",
        "bgm": "musicUri",
    }.get(semantic_type, "")


def asset_type_for_semantic(semantic_type: str) -> str:
    if semantic_type == "storyboard_video":
        return "video"
    if semantic_type == "bgm":
        return "audio"
    return "image"


def revision_asset_root(node_type: str) -> str:
    return {
        "character-generation": "characters",
        "scene-generation": "scenes",
        "storyboard": "storyboards",
        "storyboard-video-generation": "videos",
        "bgm": "audio",
    }.get(node_type, "assets")


def revision_candidate_asset_ids(state: WorkflowRevisionState) -> list[str]:
    return [
        str(asset.get("asset_id") or "")
        for asset in state.candidate_assets
        if asset.get("asset_id")
    ]


def previous_active_asset_ids(state: WorkflowRevisionState) -> list[str]:
    if state.previous_active_asset_ids:
        return [asset_id for asset_id in state.previous_active_asset_ids if asset_id]
    return [state.previous_active_asset_id] if state.previous_active_asset_id else []


def same_revision_target(left: WorkflowRevisionState, right: WorkflowRevisionState) -> bool:
    if left.node_id != right.node_id or left.target_entity_id != right.target_entity_id:
        return False
    if left.mode == "regenerate_entity" and right.mode == "regenerate_entity":
        return True
    if left.mode == "regenerate_entity" or right.mode == "regenerate_entity":
        return False
    return left.semantic_type == right.semantic_type


def revision_matches_asset_history(
    state: WorkflowRevisionState,
    entity_id: str,
    semantic_type: str,
) -> bool:
    if state.target_entity_id != entity_id:
        return False
    if state.mode == "regenerate_entity":
        candidate_semantics = revision_candidate_semantic_types(state)
        if candidate_semantics:
            return semantic_type in candidate_semantics
        return state.semantic_type == semantic_type
    return state.semantic_type == semantic_type


def revision_candidate_semantic_types(state: WorkflowRevisionState) -> set[str]:
    semantics = {
        str(asset.get("semantic_type") or "")
        for asset in state.candidate_assets
        if asset.get("semantic_type")
    }
    if not semantics and state.semantic_type:
        semantics.add(state.semantic_type)
    return semantics
