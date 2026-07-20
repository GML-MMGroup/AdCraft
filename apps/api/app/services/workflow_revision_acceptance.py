import json
from pathlib import Path
from typing import Any

from app.schemas.workflow_revisions import WorkflowRevisionState
from app.services.workflow_node_identity import ResolvedNodeIdentity
from app.services.workflow_revision_targets import (
    active_asset_ids_for_revision_target,
    active_assets,
    asset_entity_id,
    asset_type_for_semantic,
    asset_uri,
    ensure_regenerate_target,
    field_for_semantic,
    field_for_semantic_type,
    previous_active_asset_ids,
    provider_target_context,
    resolve_revision_target,
    revision_candidate_asset_ids,
    revision_candidate_semantic_types,
    revision_matches_asset_history,
    same_revision_target,
    target_payload,
    target_resolution_error,
)

__all__ = [
    "active_asset_ids_for_revision_target",
    "active_assets",
    "asset_entity_id",
    "asset_type_for_semantic",
    "asset_uri",
    "ensure_regenerate_target",
    "field_for_semantic",
    "field_for_semantic_type",
    "previous_active_asset_ids",
    "provider_target_context",
    "resolve_revision_target",
    "revision_candidate_asset_ids",
    "revision_candidate_semantic_types",
    "revision_matches_asset_history",
    "same_revision_target",
    "target_payload",
    "target_resolution_error",
]


def revision_has_quality_fields(state: WorkflowRevisionState) -> bool:
    return bool(state.quality_summary) or any(
        "quality_status" in asset or "quality_issues" in asset for asset in state.candidate_assets
    )


def revision_quality_status(state: WorkflowRevisionState) -> str:
    summary_status = state.quality_summary.get("status")
    if isinstance(summary_status, str) and summary_status:
        return summary_status
    for asset in state.candidate_assets:
        asset_status = asset.get("quality_status")
        if isinstance(asset_status, str) and asset_status:
            return asset_status
    return "unchecked"


def revision_quality_issue_count(state: WorkflowRevisionState) -> int:
    issues = state.quality_summary.get("issues")
    if isinstance(issues, list):
        return len(issues)
    count = 0
    for asset in state.candidate_assets:
        asset_issues = asset.get("quality_issues")
        if isinstance(asset_issues, list):
            count += len(asset_issues)
    return count


def revision_has_quality_warning(state: WorkflowRevisionState) -> bool:
    if revision_quality_status(state) in {"warning", "failed"}:
        return True
    return revision_quality_issue_count(state) > 0


def revision_error_code(state: WorkflowRevisionState) -> str | None:
    error_code = state.metadata.get("error_code")
    if isinstance(error_code, str) and error_code.strip():
        return error_code.strip()
    if not state.error or ":" not in state.error:
        return None
    prefix = state.error.split(":", 1)[0].strip()
    if prefix and all(character.isalnum() or character == "_" for character in prefix):
        return prefix
    return None


def revision_target_resource_id(state: WorkflowRevisionState) -> str:
    entity_id = state.target_entity_id or ""
    semantic_type = state.semantic_type or ""
    return f"{state.node_id}:{entity_id}:{semantic_type}"


def revision_asset_is_ready(asset: dict[str, Any]) -> bool:
    status = str(asset.get("status") or "").lower()
    download_status = str(asset.get("download_status") or "").lower()
    if status in {"failed", "error"} or download_status == "failed":
        return False
    if download_status in {"waiting_for_remote_url", "submitted", "running"}:
        return False
    return bool(
        asset.get("local_path")
        or asset.get("remote_url")
        or asset.get("url")
        or status in {"ready", "completed", "downloaded"}
    )


def revision_payload_from_state(state: WorkflowRevisionState) -> dict[str, Any]:
    return {
        "mode": state.mode,
        "target_entity_id": state.target_entity_id,
        "target_asset_id": state.target_asset_id,
        "semantic_type": state.semantic_type,
        "target_field": state.target_field,
        "instruction": state.instruction,
        "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
        "providerRevisionPrompt": state.providerRevisionPrompt,
        "revisionRequirements": state.revisionRequirements,
    }


def candidate_quality_failed(state: WorkflowRevisionState) -> bool:
    summary_status = str(state.quality_summary.get("status") or "")
    if summary_status == "failed":
        return True
    return any(
        str(asset.get("quality_status") or "") == "failed" for asset in state.candidate_assets
    )


def append_warning_once(state: WorkflowRevisionState, warning: dict[str, Any]) -> None:
    code = warning.get("code")
    if code and any(item.get("code") == code for item in state.warnings):
        return
    state.warnings.append(warning)


def generated_revision_asset(
    data_dir: Path,
    identity: ResolvedNodeIdentity,
    state: WorkflowRevisionState,
) -> dict[str, Any]:
    semantic_type = state.semantic_type or ""
    entity_id = state.target_entity_id or "target"
    asset_type = asset_type_for_semantic(semantic_type)
    asset_id = f"{identity.node_id}-{entity_id}-{semantic_type}-{state.revision_id}"
    extension = {"image": "json", "video": "json", "audio": "json"}.get(asset_type, "json")
    relative_path = (
        Path(revision_asset_root(identity.node_type))
        / identity.workflow_id
        / "revisions"
        / f"{asset_id}.{extension}"
    )
    asset = {
        "asset_id": asset_id,
        "workflow_id": identity.workflow_id,
        "node_id": identity.node_id,
        "node_type": identity.node_type,
        "run_id": state.revision_id,
        "asset_type": asset_type,
        "type": asset_type,
        "media_type": asset_type,
        "semantic_type": semantic_type,
        "entity_id": entity_id,
        "uri": relative_path.as_posix(),
        "local_path": relative_path.as_posix(),
        "mime_type": "application/json",
        "is_active": True,
        "is_archived": False,
        "status": "ready",
        "download_status": "ready",
        "target_field": state.target_field,
        "metadata": {
            "revision_id": state.revision_id,
            "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
            "providerRevisionPrompt": state.providerRevisionPrompt,
        },
    }
    output_path = data_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return asset


def revision_asset_root(node_type: str) -> str:
    return {
        "character-generation": "characters",
        "scene-generation": "scenes",
        "storyboard": "storyboards",
        "storyboard-video-generation": "videos",
        "bgm": "audio",
    }.get(node_type, "assets")


_active_asset_ids_for_revision_target = active_asset_ids_for_revision_target
_resolve_revision_target = resolve_revision_target
_ensure_regenerate_target = ensure_regenerate_target
_target_resolution_error = target_resolution_error
_target_payload = target_payload
_provider_target_context = provider_target_context
_active_assets = active_assets
_asset_entity_id = asset_entity_id
_asset_uri = asset_uri
_field_for_semantic = field_for_semantic
_field_for_semantic_type = field_for_semantic_type
_asset_type_for_semantic = asset_type_for_semantic
_same_revision_target = same_revision_target
_revision_matches_asset_history = revision_matches_asset_history
_revision_candidate_semantic_types = revision_candidate_semantic_types
