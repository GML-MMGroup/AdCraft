from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import (
    MarkStaleRequest,
    WorkflowGraph,
    WorkflowGraphEdge,
    WorkflowGraphEdgeCreateRequest,
    WorkflowGraphEdgeDeleteResponse,
    WorkflowGraphEdgeMutationResponse,
    WorkflowGraphEdgePatchRequest,
    WorkflowGraphNode,
    WorkflowGraphNodeCreateRequest,
    WorkflowGraphNodePatchRequest,
    WorkflowGraphSaveRequest,
    WorkflowGraphValidationResponse,
    WorkflowNodeVersionsResponse,
)
from app.schemas.workflow_handles import (
    CANONICAL_PRODUCT_EDGE_HANDLES,
    get_node_handles,
)
from app.services.agent_trace import utc_now
from app.services.workflow_shot_bindings import item_id_for_stale, shot_references_entity
from app.services.workflow_state import load_workflow_plan

from app.services.workflow_graph_common import (
    VERSION_FIELDS,
    WorkflowGraphError,
)
from app.services.workflow_graph_preservation import (
    _apply_prompt_source_metadata,
    _default_mapping,
    _edge_id,
    _normalize_graph_edge,
    _normalize_saved_edges,
    _normalize_saved_nodes,
    _unique_edge_id,
)
from app.services.workflow_graph_store import (
    _append_node_version,
    load_graph,
    save_graph,
    workflow_versions_path,
)
from app.services.workflow_graph_topology import (
    _affected_downstream_node_ids,
    _downstream_node_ids,
    _find_node,
    _refresh_depends_on,
    _require_edge,
    _require_node,
)
from app.services.workflow_graph_validation import (
    _reject_incompatible_requested_handles,
    validate_graph,
)


def _restore_canonical_product_edges_from_sources(
    *,
    data_dir: Path,
    graph: WorkflowGraph,
    restore_from_plan: bool,
    source_edges: list[WorkflowGraphEdge] | None = None,
) -> bool:
    source_labels: dict[tuple[str, str], str | None] = {}
    if source_edges:
        source_labels.update(_canonical_product_edge_labels_from_edges(source_edges))
    if restore_from_plan:
        source_labels.update(_canonical_product_edge_labels_from_plan(data_dir, graph.workflow_id))
    if not source_labels:
        return False

    changed = _refresh_product_edge_node_handles(graph)
    node_ids = {node.id for node in graph.nodes}
    edge_ids = {edge.id for edge in graph.edges}
    existing_by_pair = {(edge.source_node_id, edge.target_node_id): edge for edge in graph.edges}
    for edge_pair, (source_handle, target_handle) in CANONICAL_PRODUCT_EDGE_HANDLES.items():
        if edge_pair not in source_labels:
            continue
        source_node_id, target_node_id = edge_pair
        if source_node_id not in node_ids or target_node_id not in node_ids:
            continue
        existing = existing_by_pair.get(edge_pair)
        if existing is not None:
            if existing.source_handle != source_handle or existing.target_handle != target_handle:
                existing.source_handle = source_handle
                existing.target_handle = target_handle
                changed = True
            continue

        label = source_labels[edge_pair]
        edge_id = _unique_edge_id(_edge_id(source_node_id, target_node_id), edge_ids)
        edge_ids.add(edge_id)
        edge = WorkflowGraphEdge(
            id=edge_id,
            workflow_id=graph.workflow_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            source_handle=source_handle,
            target_handle=target_handle,
            label=label,
            mapping=_default_mapping(label),
            required=True,
        )
        graph.edges.append(edge)
        existing_by_pair[edge_pair] = edge
        changed = True
    if changed:
        _refresh_depends_on(graph)
    return changed


def _refresh_product_edge_node_handles(graph: WorkflowGraph) -> bool:
    changed = False
    node_ids = {"product-generation", "final-composition"}
    for node in graph.nodes:
        if node.id not in node_ids:
            continue
        expected = get_node_handles(node.node_type)
        if node.handles != expected:
            node.handles = expected
            changed = True
    return changed


def _canonical_product_edge_labels_from_plan(
    data_dir: Path, workflow_id: str
) -> dict[tuple[str, str], str | None]:
    plan = load_workflow_plan(data_dir, workflow_id)
    if plan is None:
        return {}
    workflow = plan.get("workflow")
    if not isinstance(workflow, dict):
        return {}
    edges = workflow.get("edges")
    if not isinstance(edges, list):
        return {}
    labels: dict[tuple[str, str], str | None] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source") or edge.get("source_node_id")
        target = edge.get("target") or edge.get("target_node_id")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        pair = (source, target)
        if pair in CANONICAL_PRODUCT_EDGE_HANDLES:
            label = edge.get("label")
            labels[pair] = label if isinstance(label, str) else None
    return labels


def _canonical_product_edge_labels_from_edges(
    edges: list[WorkflowGraphEdge],
) -> dict[tuple[str, str], str | None]:
    labels: dict[tuple[str, str], str | None] = {}
    for edge in edges:
        pair = (edge.source_node_id, edge.target_node_id)
        if pair in CANONICAL_PRODUCT_EDGE_HANDLES:
            labels[pair] = edge.label
    return labels


def _enrich_nodes_with_prompt_preview(
    data_dir: Path,
    workflow_id: str,
    graph: WorkflowGraph,
) -> None:
    from app.services.workflow_input_resolver import (
        compute_node_prompt_preview,
        compute_node_prompt_with_assets,
    )

    for node in graph.nodes:
        try:
            preview = compute_node_prompt_preview(data_dir, workflow_id, node.id)
        except Exception:  # noqa: BLE001 - preview enrichment must never break get_graph
            preview = None
        if preview:
            node.input_context["system_resolved_prompt_preview"] = preview
        elif "system_resolved_prompt_preview" in node.input_context:
            node.input_context.pop("system_resolved_prompt_preview", None)
        try:
            prompt_with_assets = compute_node_prompt_with_assets(data_dir, workflow_id, node.id)
        except Exception:  # noqa: BLE001 - enrichment must never break get_graph
            prompt_with_assets = None
        if prompt_with_assets:
            node.input_context["system_resolved_prompt_with_assets"] = prompt_with_assets
        elif "system_resolved_prompt_with_assets" in node.input_context:
            node.input_context.pop("system_resolved_prompt_with_assets", None)


class WorkflowGraphService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def get_graph(self, workflow_id: str) -> WorkflowGraph:
        graph = load_graph(self._data_dir, workflow_id)
        if graph is None:
            raise WorkflowGraphError(f"workflow graph not found: {workflow_id}")
        _enrich_nodes_with_prompt_preview(self._data_dir, workflow_id, graph)
        return graph

    def save_full_graph(self, workflow_id: str, request: WorkflowGraphSaveRequest) -> WorkflowGraph:
        existing_graph = load_graph(self._data_dir, workflow_id)
        now = utc_now().isoformat()
        ad_request = (
            request.ad_request
            if request.ad_request
            else existing_graph.ad_request
            if existing_graph is not None
            else {}
        )
        graph = WorkflowGraph(
            workflow_id=workflow_id,
            name=request.name
            if request.name is not None
            else existing_graph.name
            if existing_graph is not None
            else f"{workflow_id} Workflow",
            description=request.description
            if request.description is not None
            else existing_graph.description
            if existing_graph is not None
            else "",
            version=request.version
            if request.version is not None
            else existing_graph.version
            if existing_graph is not None
            else 1,
            status=request.status
            if request.status is not None
            else existing_graph.status
            if existing_graph is not None
            else "draft",
            nodes=_normalize_saved_nodes(
                workflow_id,
                request.nodes,
                {node.id: node for node in existing_graph.nodes}
                if existing_graph is not None
                else None,
            ),
            edges=_normalize_saved_edges(
                workflow_id,
                request.edges,
                existing_graph.edges if existing_graph is not None else None,
            ),
            created_at=request.created_at
            if request.created_at is not None
            else existing_graph.created_at
            if existing_graph is not None
            else now,
            updated_at=now,
            ad_request=ad_request,
            audio_mode=request.audio_mode
            if request.audio_mode is not None
            else existing_graph.audio_mode
            if existing_graph is not None
            else "bgm_only",
        )
        _restore_canonical_product_edges_from_sources(
            data_dir=self._data_dir,
            graph=graph,
            restore_from_plan=True,
            source_edges=existing_graph.edges if existing_graph is not None else None,
        )
        issues = validate_graph(graph).issues
        errors = [issue.message for issue in issues if issue.level == "error"]
        if errors:
            raise WorkflowGraphError("; ".join(errors))
        return save_graph(self._data_dir, graph)

    def validate(self, workflow_id: str) -> WorkflowGraphValidationResponse:
        return validate_graph(self.get_graph(workflow_id))

    def add_node(self, workflow_id: str, request: WorkflowGraphNodeCreateRequest) -> WorkflowGraph:
        graph = self.get_graph(workflow_id)
        if _find_node(graph, request.id) is not None:
            raise WorkflowGraphError(f"node already exists: {request.id}")
        node = WorkflowGraphNode(
            **request.model_dump(mode="json"),
            workflow_id=workflow_id,
            version=1,
        )
        graph.nodes.append(node)
        graph.version += 1
        graph = save_graph(self._data_dir, graph)
        _append_node_version(self._data_dir, workflow_id, node, reason="node created")
        return graph

    def patch_node(
        self,
        workflow_id: str,
        node_id: str,
        request: WorkflowGraphNodePatchRequest,
    ) -> WorkflowGraph:
        graph = self.get_graph(workflow_id)
        node = _require_node(graph, node_id)
        patch = request.model_dump(exclude_unset=True, mode="json")
        changed_fields: set[str] = set()
        for field_name, value in patch.items():
            if getattr(node, field_name) != value:
                setattr(node, field_name, value)
                changed_fields.add(field_name)
        if changed_fields:
            if changed_fields & {"prompt", "override_prompt"}:
                _apply_prompt_source_metadata(node)
            if changed_fields & VERSION_FIELDS:
                node.version += 1
                _append_node_version(
                    self._data_dir,
                    workflow_id,
                    node,
                    reason=f"node fields changed: {', '.join(sorted(changed_fields))}",
                )
                self._mark_downstream_stale(graph, node_id, f"upstream {node_id} changed")
            graph.version += 1
        return save_graph(self._data_dir, graph)

    def delete_node(self, workflow_id: str, node_id: str) -> WorkflowGraph:
        graph = self.get_graph(workflow_id)
        _require_node(graph, node_id)
        graph.nodes = [node for node in graph.nodes if node.id != node_id]
        graph.edges = [
            edge
            for edge in graph.edges
            if edge.source_node_id != node_id and edge.target_node_id != node_id
        ]
        graph.version += 1
        return save_graph(self._data_dir, graph)

    def add_edge(
        self, workflow_id: str, request: WorkflowGraphEdgeCreateRequest
    ) -> WorkflowGraphEdgeMutationResponse:
        graph = self.get_graph(workflow_id)
        source_node = _require_node(graph, request.source_node_id)
        target_node = _require_node(graph, request.target_node_id)
        _reject_incompatible_requested_handles(
            source_node,
            target_node,
            request.source_handle,
            request.target_handle,
        )
        edge = WorkflowGraphEdge(
            id=request.id or _edge_id(request.source_node_id, request.target_node_id),
            workflow_id=workflow_id,
            source_node_id=request.source_node_id,
            target_node_id=request.target_node_id,
            source_handle=request.source_handle or "",
            target_handle=request.target_handle or "",
            label=request.label,
            mapping=request.mapping or _default_mapping(request.label),
            required=request.required,
        )
        if any(existing.id == edge.id for existing in graph.edges):
            edge = edge.model_copy(update={"id": f"{edge.id}_{len(graph.edges) + 1}"})
        graph.edges.append(edge)
        issues = validate_graph(graph).issues
        errors = [issue.message for issue in issues if issue.level == "error"]
        if errors:
            raise WorkflowGraphError("; ".join(errors))
        graph.version += 1
        saved = save_graph(self._data_dir, graph)
        saved_edge = _require_edge(saved, edge.id)
        return WorkflowGraphEdgeMutationResponse(
            edge=saved_edge,
            affected_downstream_nodes=_affected_downstream_node_ids(
                saved, saved_edge.target_node_id
            ),
            workflow_version=saved.version,
        )

    def patch_edge(
        self,
        workflow_id: str,
        edge_id: str,
        request: WorkflowGraphEdgePatchRequest,
    ) -> WorkflowGraphEdgeMutationResponse:
        graph = self.get_graph(workflow_id)
        edge = _require_edge(graph, edge_id)
        patch = request.model_dump(exclude_unset=True, mode="json")
        source_node_id = str(patch.get("source_node_id") or edge.source_node_id)
        target_node_id = str(patch.get("target_node_id") or edge.target_node_id)
        source_node = _require_node(graph, source_node_id)
        target_node = _require_node(graph, target_node_id)
        _reject_incompatible_requested_handles(
            source_node,
            target_node,
            patch.get("source_handle"),
            patch.get("target_handle"),
        )
        for field_name, value in patch.items():
            setattr(edge, field_name, value)
        _normalize_graph_edge(edge)
        issues = validate_graph(graph).issues
        errors = [issue.message for issue in issues if issue.level == "error"]
        if errors:
            raise WorkflowGraphError("; ".join(errors))
        graph.version += 1
        saved = save_graph(self._data_dir, graph)
        saved_edge = _require_edge(saved, edge_id)
        return WorkflowGraphEdgeMutationResponse(
            edge=saved_edge,
            affected_downstream_nodes=_affected_downstream_node_ids(
                saved, saved_edge.target_node_id
            ),
            workflow_version=saved.version,
        )

    def delete_edge(self, workflow_id: str, edge_id: str) -> WorkflowGraphEdgeDeleteResponse:
        graph = self.get_graph(workflow_id)
        edge = _require_edge(graph, edge_id)
        affected_downstream_nodes = _affected_downstream_node_ids(graph, edge.target_node_id)
        graph.edges = [edge for edge in graph.edges if edge.id != edge_id]
        graph.version += 1
        saved = save_graph(self._data_dir, graph)
        return WorkflowGraphEdgeDeleteResponse(
            deleted_edge_id=edge_id,
            affected_downstream_nodes=affected_downstream_nodes,
            workflow_version=saved.version,
        )

    def lock_node(self, workflow_id: str, node_id: str) -> WorkflowGraph:
        graph = self.get_graph(workflow_id)
        node = _require_node(graph, node_id)
        node.locked = True
        graph.version += 1
        return save_graph(self._data_dir, graph)

    def unlock_node(self, workflow_id: str, node_id: str) -> WorkflowGraph:
        graph = self.get_graph(workflow_id)
        node = _require_node(graph, node_id)
        node.locked = False
        graph.version += 1
        return save_graph(self._data_dir, graph)

    def mark_stale(self, workflow_id: str, request: MarkStaleRequest) -> WorkflowGraph:
        graph = self.get_graph(workflow_id)
        node_ids = request.node_ids or [node.id for node in graph.nodes]
        changed_entity_ids = {
            str(entity_id) for entity_id in request.changed_entity_ids if str(entity_id).strip()
        }
        for node_id in node_ids:
            _require_node(graph, node_id)
            if request.include_downstream:
                self._mark_downstream_stale(
                    graph,
                    node_id,
                    request.reason,
                    changed_entity_ids=changed_entity_ids,
                )
            else:
                node = _require_node(graph, node_id)
                if not node.locked:
                    node.stale = True
                    node.stale_reason = request.reason
        graph.version += 1
        return save_graph(self._data_dir, graph)

    def node_versions(self, workflow_id: str, node_id: str) -> WorkflowNodeVersionsResponse:
        graph = self.get_graph(workflow_id)
        _require_node(graph, node_id)
        path = workflow_versions_path(self._data_dir, workflow_id, node_id)
        versions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not versions:
            node = _require_node(graph, node_id)
            versions = [{"version": node.version, "node": node.model_dump(mode="json")}]
        return WorkflowNodeVersionsResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            versions=versions,
        )

    def _mark_downstream_stale(
        self,
        graph: WorkflowGraph,
        node_id: str,
        reason: str,
        *,
        changed_entity_ids: set[str] | None = None,
    ) -> None:
        for downstream_id in _downstream_node_ids(graph, node_id):
            downstream = _require_node(graph, downstream_id)
            if downstream.locked:
                downstream.stale_reason = f"locked node not auto-marked stale after {reason}"
                continue
            if changed_entity_ids and downstream.node_type in {
                "storyboard",
                "storyboard-video-generation",
            }:
                if _mark_referencing_media_items_stale(
                    downstream,
                    changed_entity_ids,
                    reason,
                ):
                    continue
            downstream.stale = True
            downstream.status = "stale"
            downstream.stale_reason = reason


def _mark_referencing_media_items_stale(
    node: WorkflowGraphNode,
    changed_entity_ids: set[str],
    reason: str,
) -> bool:
    found_item_list = False
    stale_item_ids: list[str] = []
    for payload in (node.input_context, node.output):
        for key in ("media_items", "shots", "storyboardItems", "videoSegments", "segments"):
            value = payload.get(key)
            if isinstance(value, list):
                found_item_list = True
                _mark_items_stale(value, changed_entity_ids, stale_item_ids)
        structured_output = payload.get("structured_output")
        if isinstance(structured_output, dict):
            for key in ("shots", "storyboardItems", "videoSegments", "segments"):
                value = structured_output.get(key)
                if isinstance(value, list):
                    found_item_list = True
                    _mark_items_stale(value, changed_entity_ids, stale_item_ids)
    if not found_item_list:
        return False
    node.metadata = dict(node.metadata or {})
    deduped_item_ids = [item_id for item_id in dict.fromkeys(stale_item_ids) if item_id]
    if deduped_item_ids:
        node.stale = True
        node.status = "stale"
        node.stale_reason = reason
        node.metadata["stale_item_ids"] = deduped_item_ids
        node.metadata["stale_entity_ids"] = sorted(changed_entity_ids)
    else:
        node.metadata.pop("stale_item_ids", None)
    return True


def _mark_items_stale(
    items: list[Any],
    changed_entity_ids: set[str],
    stale_item_ids: list[str],
) -> None:
    for item in items:
        if not isinstance(item, dict) or not shot_references_entity(item, changed_entity_ids):
            continue
        item["status"] = "stale"
        item["stale"] = True
        item["stale_reason"] = "referenced entity changed"
        item_id = item_id_for_stale(item)
        if item_id:
            stale_item_ids.append(item_id)
