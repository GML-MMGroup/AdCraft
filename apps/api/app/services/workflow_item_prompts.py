from __future__ import annotations

# V1/legacy compatibility only. V2 high-risk provider, repair, fallback,
# and storyboard detail prompt paths must not import this module.

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_item_prompts import (
    WorkflowItemPromptUpdateRequest,
    WorkflowItemPromptUpdateResponse,
)
from app.services.workflow_graph import WorkflowGraphError, load_graph, save_graph
from app.services.workflow_item_prompt_utils import (
    item_id_from_payload,
    normalize_item_prompt_fields_in_payload,
    normalize_node_item_prompt_fields,
    update_item_prompt_in_payload,
)
from app.services.workflow_node_identity import (
    WorkflowNodeIdentityError,
    resolve_node_identity,
)
from app.services.workflow_state import resolve_active_result


class WorkflowItemPromptError(ValueError):
    def __init__(self, *, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail.get("message") or detail.get("code") or "item prompt error"))


class WorkflowItemPromptService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def update_item_prompt(
        self,
        *,
        workflow_id: str,
        node_id: str,
        item_id: str,
        request: WorkflowItemPromptUpdateRequest,
    ) -> WorkflowItemPromptUpdateResponse:
        prompt = request.prompt.strip()
        if not prompt:
            raise WorkflowItemPromptError(
                status_code=422,
                detail={
                    "code": "item_prompt_empty",
                    "message": "Item prompt must not be empty.",
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "item_id": item_id,
                },
            )
        try:
            identity = resolve_node_identity(
                data_dir=self._settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=None,
            )
        except WorkflowNodeIdentityError as exc:
            raise WorkflowItemPromptError(status_code=exc.status_code, detail=exc.detail) from exc
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            raise WorkflowItemPromptError(
                status_code=404,
                detail={
                    "code": "workflow_graph_not_found",
                    "message": f"Workflow graph not found: {workflow_id}.",
                    "workflow_id": workflow_id,
                },
            )
        node = next((item for item in graph.nodes if item.id == identity.node_id), None)
        if node is None:
            raise WorkflowItemPromptError(
                status_code=404,
                detail={
                    "code": "target_node_not_found",
                    "message": f"Workflow node not found: {identity.node_id}.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                },
            )
        normalize_node_item_prompt_fields(node)
        updated = 0
        updated += update_item_prompt_in_payload(
            node.output,
            item_id=item_id,
            prompt=prompt,
            node_type=identity.node_type,
            semantic_type=request.semantic_type,
            mark_stale=request.mark_stale,
        )
        updated += update_item_prompt_in_payload(
            node.input_context,
            item_id=item_id,
            prompt=prompt,
            node_type=identity.node_type,
            semantic_type=request.semantic_type,
            mark_stale=request.mark_stale,
        )
        if updated == 0:
            raise WorkflowItemPromptError(
                status_code=404,
                detail={
                    "code": "target_item_not_found",
                    "message": f"Target item not found: {item_id}.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "item_id": item_id,
                },
            )
        stale_item_ids = [item_id] if request.mark_stale else []
        node.metadata = dict(node.metadata or {})
        if request.mark_stale:
            node.status = "stale"
            node.stale = True
            node.stale_reason = f"item prompt updated: {item_id}"
            node.metadata["stale_item_ids"] = _merge_stale_item_ids(
                node.metadata.get("stale_item_ids"),
                item_id,
            )
        node.version += 1
        graph.version += 1
        save_graph(self._settings.media_data_dir, graph)
        self._sync_active_result(
            workflow_id=workflow_id,
            node_id=identity.node_id,
            node_type=identity.node_type,
            item_id=item_id,
            prompt=prompt,
            semantic_type=request.semantic_type,
            mark_stale=request.mark_stale,
        )
        updated_item = _find_item(node.output, item_id) or _find_item(node.input_context, item_id)
        status = str(updated_item.get("status") if updated_item else "") or (
            "stale" if request.mark_stale else "ready"
        )
        target = {
            "target_type": "item",
            "node_id": identity.node_id,
            "node_type": identity.node_type,
            "item_id": item_id,
            "semantic_type": request.semantic_type,
            "intent_scope": "single",
            "display_name": _display_name(updated_item, item_id),
        }
        return WorkflowItemPromptUpdateResponse(
            workflow_id=workflow_id,
            node_id=identity.node_id,
            node_type=identity.node_type,
            item_id=item_id,
            semantic_type=request.semantic_type,
            prompt=prompt,
            prompt_source="user",
            manual_prompt_dirty=True,
            status=status,
            stale_item_ids=stale_item_ids,
            target=target,
        )

    def _sync_active_result(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_type: str,
        item_id: str,
        prompt: str,
        semantic_type: str | None,
        mark_stale: bool,
    ) -> None:
        active = resolve_active_result(
            self._settings.media_data_dir,
            workflow_id,
            node_id,
            node_type,
        )
        if active is None:
            return
        output = active.get("output")
        if isinstance(output, dict):
            normalize_item_prompt_fields_in_payload(
                output,
                node_type=node_type,
                output_assets=active.get("output_assets")
                if isinstance(active.get("output_assets"), list)
                else [],
            )
            update_item_prompt_in_payload(
                output,
                item_id=item_id,
                prompt=prompt,
                node_type=node_type,
                semantic_type=semantic_type,
                mark_stale=mark_stale,
            )
        input_context = active.get("input_context")
        if isinstance(input_context, dict):
            normalize_item_prompt_fields_in_payload(input_context, node_type=node_type)
            update_item_prompt_in_payload(
                input_context,
                item_id=item_id,
                prompt=prompt,
                node_type=node_type,
                semantic_type=semantic_type,
                mark_stale=mark_stale,
            )
        trace = active.get("trace")
        if isinstance(trace, dict):
            if isinstance(output, dict):
                trace["output"] = output
            if isinstance(input_context, dict):
                trace["input_context"] = input_context
        active_path = self._settings.media_data_dir / "runs" / workflow_id / "nodes" / node_id
        _write_json(active_path / "active.json", active)
        metadata_path = active.get("metadata_path") or active.get("trace_path")
        if isinstance(metadata_path, str) and metadata_path.strip():
            run_path = self._settings.media_data_dir / metadata_path
            if run_path.exists() and run_path != active_path / "active.json":
                _write_json(run_path, active)


def normalize_graph_item_prompt_fields(workflow_id: str, data_dir: Path) -> None:
    graph = load_graph(data_dir, workflow_id)
    if graph is None:
        raise WorkflowGraphError(f"workflow graph not found: {workflow_id}")
    for node in graph.nodes:
        normalize_node_item_prompt_fields(node)


def _find_item(payload: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in _iter_payload_items(payload):
        if item_id_from_payload(item) == item_id:
            return item
    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        for item in _iter_payload_items(structured):
            if item_id_from_payload(item) == item_id:
                return item
    return None


def _display_name(item: dict[str, Any] | None, item_id: str) -> str:
    if not isinstance(item, dict):
        return item_id
    for key in ("display_name", "title", "name", "sceneName", "roleName", "shotName"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return item_id


def _iter_payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in payload.values():
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def _merge_stale_item_ids(existing: Any, item_id: str) -> list[str]:
    result = (
        [str(item) for item in existing if str(item).strip()] if isinstance(existing, list) else []
    )
    if item_id not in result:
        result.append(item_id)
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
