from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas.workflow_graph import MarkStaleRequest
from app.services.agent_trace import utc_now
from app.services.media_paths import with_public_urls
from app.services.workflow_asset_history import (
    load_node_asset_history,
    write_node_asset_history,
)
from app.services.workflow_graph import WorkflowGraphService, load_graph, save_graph
from app.services.workflow_state import persist_node_run, resolve_active_result
from app.services.workflow_working_version_items import (
    active_assets_for_output,
    asset_matches_item,
    asset_root_for_node,
    asset_type_for_node,
    asset_uri,
    require_item,
    set_item_uri,
    semantic_type_for_node,
)


def version_assets(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    output_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    history = load_node_asset_history(data_dir, workflow_id, node_id)
    merged: dict[str, dict[str, Any]] = {}
    for asset in [*history, *output_assets]:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id:
            continue
        merged[asset_id] = deepcopy(asset)
    return with_public_urls(list(merged.values()))


def select_current_assets(
    data_dir: Path,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    version: dict[str, Any],
    force_quality_override: bool,
    use_for_composition: bool,
) -> list[dict[str, Any]]:
    asset_ids = [str(asset_id) for asset_id in version.get("asset_ids", []) if asset_id]
    history = load_node_asset_history(data_dir, workflow_id, node_id)
    selected_assets: list[dict[str, Any]] = []
    now = utc_now().isoformat()
    for asset in history:
        if asset_matches_item(asset, item_id, node_type):
            asset["is_active"] = str(asset.get("asset_id") or "") in asset_ids
        if str(asset.get("asset_id") or "") not in asset_ids:
            continue
        asset["is_active"] = True
        asset["candidate_status"] = "accepted"
        asset["acceptance_status"] = "accepted"
        asset["visibility_status"] = "visible"
        asset["selected_at"] = now
        asset["selected_reason"] = "user_override" if force_quality_override else "user_selected"
        if force_quality_override:
            asset["quality_override"] = True
            metadata = asset.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["quality_override"] = True
                metadata["selected_reason"] = "user_override"
        if use_for_composition:
            asset["selected_for_composition"] = True
        selected_assets.append(deepcopy(asset))
    if not selected_assets:
        raise ValueError("Current working version assets are missing.")
    write_node_asset_history(data_dir, workflow_id, node_id, history)
    return selected_assets


def apply_selected_assets_to_output(
    data_dir: Path,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    output: dict[str, Any],
    item_id: str,
    assets: list[dict[str, Any]],
    quality_override: bool,
) -> dict[str, Any]:
    updated = deepcopy(output)
    item = require_item(updated, item_id)
    item["lifecycle_state"] = "active"
    item["needs_apply"] = False
    if quality_override:
        item["quality_override"] = True
        item["selected_reason"] = "user_override"
    uri = asset_uri(assets[0])
    if uri:
        set_item_uri(item, node_type, uri)
    updated["assets"] = active_assets_for_output(
        load_node_asset_history(data_dir, workflow_id, node_id)
    )
    updated["output_assets"] = updated["assets"]
    return updated


def persist_node_output(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    output: dict[str, Any],
    output_assets: list[dict[str, Any]],
) -> None:
    active = resolve_active_result(data_dir, workflow_id, node_id)
    if active is None:
        node_type = node_type_from_graph(data_dir, workflow_id, node_id)
        if node_type is None:
            return
        persist_node_run(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node_type,
            status="completed",
            output=output,
            input_assets=[],
            output_assets=output_assets,
            input_context={},
            error=None,
            source="workflow-working-version",
            data_dir=data_dir,
        )
        return
    active["output"] = output
    active["output_assets"] = output_assets
    trace = active.get("trace")
    if isinstance(trace, dict):
        trace["output"] = output
        trace["output_assets"] = output_assets
    node_dir = data_dir / "runs" / workflow_id / "nodes" / node_id
    write_json_atomic(node_dir / "active.json", active)
    trace_path = active.get("trace_path") or active.get("metadata_path")
    if isinstance(trace_path, str) and trace_path:
        run_path = data_dir / trace_path
        if run_path.exists():
            write_json_atomic(run_path, active)


def save_graph_node_output(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    output: dict[str, Any],
    output_assets: list[dict[str, Any]],
) -> None:
    graph = load_graph(data_dir, workflow_id)
    if graph is None:
        return
    node = find_graph_node(graph, node_id)
    if node is None:
        return
    node.output = output
    node.output_assets = output_assets
    node.status = "completed"
    node.stale = False
    node.stale_reason = None
    graph.version += 1
    save_graph(data_dir, graph)


def create_working_version(
    data_dir: Path,
    events: Any,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item: dict[str, Any],
    prompt: str,
    visual_assets: list[dict[str, Any]] | None = None,
    media_type: str | None = None,
    asset_slot_id: str | None = None,
    semantic_type: str | None = None,
    source_asset_id: str | None = None,
) -> dict[str, Any]:
    item_id = _item_id_from_payload(item)
    if not item_id:
        raise ValueError("Target item has no item_id.")
    asset_type = media_type or asset_type_for_node(node_type)
    revision_id = f"wv_{uuid4().hex[:12]}"
    slot_suffix = f"-{_safe_id(asset_slot_id)}" if asset_slot_id else ""
    asset_id = f"{node_id}-{item_id}{slot_suffix}-{revision_id}"
    extension = "mp4" if asset_type == "video" else "png"
    relative_path = Path(asset_root_for_node(node_type)) / workflow_id / f"{asset_id}.{extension}"
    output_path = data_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"mock generated working version")
    now = utc_now().isoformat()
    asset = {
        "asset_id": asset_id,
        "workflow_id": workflow_id,
        "node_id": node_id,
        "source_node_id": node_id,
        "run_id": revision_id,
        "asset_type": asset_type,
        "type": asset_type,
        "media_type": asset_type,
        "semantic_type": semantic_type or semantic_type_for_node(node_type),
        "entity_id": item_id,
        "item_id": item_id,
        "asset_slot_id": asset_slot_id or "",
        "local_path": relative_path.as_posix(),
        "uri": relative_path.as_posix(),
        "is_active": False,
        "is_archived": False,
        "candidate_status": "pending",
        "acceptance_status": "pending",
        "visibility_status": "visible",
        "status": "ready",
        "download_status": "ready",
        "created_at": now,
        "prompt": prompt,
        "provider_prompt": prompt,
        "quality_status": "passed",
        "quality_issues": [],
        "metadata": {
            "revision_id": revision_id,
            "source_item_id": item_id,
            "source_asset_id": source_asset_id,
            "asset_slot_id": asset_slot_id,
            "prompt_scope": "asset" if asset_slot_id else "item",
            "source_asset_prompt": prompt if asset_slot_id else None,
            "source_item_prompt": prompt,
            "input_asset_ids": [
                str(asset.get("asset_id") or "")
                for asset in visual_assets or []
                if asset.get("asset_id")
            ],
        },
    }
    if node_type == "storyboard-video-generation":
        asset["role"] = "video_segment"
        asset["kind"] = "video"
        asset["shot_id"] = item_id
        asset["shotId"] = item_id
        asset["selected_for_composition"] = False
    if node_type == "scene-generation":
        asset["scene_id"] = item_id
    if node_type == "character-generation":
        asset["character_id"] = item_id
    history = load_node_asset_history(data_dir, workflow_id, node_id)
    history.append(asset)
    write_node_asset_history(data_dir, workflow_id, node_id, history)
    events.append_event(
        workflow_id,
        "item_working_version_started",
        node_id=node_id,
        node_type=node_type,
        resource_type="item",
        resource_id=item_id,
        payload={
            "workflow_id": workflow_id,
            "node_id": node_id,
            "node_type": node_type,
            "item_id": item_id,
            "semantic_type": asset["semantic_type"],
            "revision_id": revision_id,
            "version_id": revision_id,
            "asset_ids": [asset_id],
            "refresh": ["workflow_nodes"],
        },
    )
    events.append_event(
        workflow_id,
        "item_working_version_updated",
        node_id=node_id,
        node_type=node_type,
        resource_type="item",
        resource_id=item_id,
        payload={
            "workflow_id": workflow_id,
            "node_id": node_id,
            "node_type": node_type,
            "item_id": item_id,
            "semantic_type": asset["semantic_type"],
            "revision_id": revision_id,
            "version_id": revision_id,
            "asset_ids": [asset_id],
            "refresh": ["workflow_nodes", "asset_history"],
        },
    )
    return asset


def mark_downstream_stale(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    *,
    changed_item_ids: list[str],
) -> list[str]:
    graph_service = WorkflowGraphService(data_dir)
    graph = graph_service.mark_stale(
        workflow_id,
        MarkStaleRequest(
            node_ids=[node_id],
            include_downstream=True,
            reason=f"item selected: {', '.join(changed_item_ids)}",
            changed_entity_ids=changed_item_ids,
        ),
    )
    return downstream_node_ids(graph, node_id)


def find_graph_node(graph: Any, node_id: str) -> Any | None:
    return next((node for node in graph.nodes if node.id == node_id), None)


def node_type_from_graph(data_dir: Path, workflow_id: str, node_id: str) -> str | None:
    graph = load_graph(data_dir, workflow_id)
    if graph is None:
        return None
    node = find_graph_node(graph, node_id)
    return node.node_type if node is not None else None


def downstream_node_ids(graph: Any, node_id: str) -> list[str]:
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    result: list[str] = []
    queue = list(outgoing.get(node_id, []))
    while queue:
        current = queue.pop(0)
        if current in result:
            continue
        result.append(current)
        queue.extend(outgoing.get(current, []))
    return result


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _item_id_from_payload(item: dict[str, Any]) -> str:
    for key in ("item_id", "shot_id", "shotId", "sceneId", "roleId", "productId"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _safe_id(value: str | None) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value or ""))
