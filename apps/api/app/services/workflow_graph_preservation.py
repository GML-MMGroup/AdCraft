from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphEdge,
    WorkflowGraphEdgeSaveItem,
    WorkflowGraphNode,
    WorkflowGraphNodeSaveItem,
)
from app.schemas.workflow_handles import (
    WorkflowNodeHandles,
    get_node_handles,
    normalize_edge_handles,
)

from app.services.workflow_graph_common import (
    GRAPH_INPUT_CONTEXT_OMIT_KEYS,
    NODE_CATEGORY_BY_TYPE,
    PRESERVED_SYSTEM_INPUT_CONTEXT_KEYS,
    PRESERVED_SYSTEM_METADATA_KEYS,
    WorkflowGraphError,
)


def _normalize_saved_nodes(
    workflow_id: str,
    nodes: list[WorkflowGraphNodeSaveItem],
    existing_nodes: dict[str, WorkflowGraphNode] | None = None,
) -> list[WorkflowGraphNode]:
    normalized_nodes: list[WorkflowGraphNode] = []
    existing_nodes = existing_nodes or {}
    for item in nodes:
        existing = existing_nodes.get(item.id)
        node_type = item.node_type or (existing.node_type if existing is not None else item.id)
        category = item.category or (
            existing.category
            if existing is not None
            else NODE_CATEGORY_BY_TYPE.get(node_type, "utility")
        )
        input_context = _preserved_input_context(
            item.input_context,
            existing,
            _save_item_has_field(item, "input_context"),
        )
        override_prompt = _preserved_prompt(
            item.override_prompt,
            existing,
            input_context,
            "override_prompt",
            _save_item_has_field(item, "override_prompt"),
        )
        prompt = _preserved_prompt(
            item.prompt,
            existing,
            input_context,
            "prompt",
            _save_item_has_field(item, "prompt"),
        )
        metadata = _metadata_with_prompt_source(
            _preserved_metadata(
                item.metadata,
                existing,
                input_context,
                _save_item_has_field(item, "metadata"),
            ),
            prompt,
            override_prompt,
            input_context,
        )
        input_assets = _preserved_input_assets(item.input_assets, existing, input_context)
        normalized_nodes.append(
            WorkflowGraphNode(
                id=item.id,
                workflow_id=workflow_id,
                node_type=node_type,
                category=category,
                title=_preserved_field(item, existing, "title") or item.id,
                description=_preserved_field(item, existing, "description"),
                position=item.position,
                config=_preserved_field(item, existing, "config"),
                prompt=prompt,
                override_prompt=override_prompt,
                input_schema=_preserved_field(item, existing, "input_schema"),
                output_schema=_preserved_field(item, existing, "output_schema"),
                input_context=input_context,
                output=_preserved_field(item, existing, "output"),
                metadata=metadata,
                input_assets=input_assets,
                output_assets=_preserved_field(item, existing, "output_assets"),
                status=_preserved_field(item, existing, "status"),
                version=_preserved_field(item, existing, "version"),
                input_hash=_preserved_field(item, existing, "input_hash"),
                output_hash=_preserved_field(item, existing, "output_hash"),
                locked=_preserved_field(item, existing, "locked"),
                stale=_preserved_field(item, existing, "stale"),
                stale_reason=_preserved_field(item, existing, "stale_reason"),
                depends_on=_preserved_field(item, existing, "depends_on"),
                can_run_standalone=_preserved_field(item, existing, "can_run_standalone"),
                supports_override_prompt=_preserved_field(
                    item, existing, "supports_override_prompt"
                ),
                handles=_handles_or_default(node_type, item.handles),
            )
        )
    return normalized_nodes


def _save_item_has_field(item: WorkflowGraphNodeSaveItem, field_name: str) -> bool:
    return field_name in item.model_fields_set


def _preserved_field(
    item: WorkflowGraphNodeSaveItem,
    existing: WorkflowGraphNode | None,
    field_name: str,
) -> Any:
    if _save_item_has_field(item, field_name) or existing is None:
        return getattr(item, field_name)
    return getattr(existing, field_name)


def _preserved_prompt(
    incoming: str | None,
    existing: WorkflowGraphNode | None,
    incoming_context: dict[str, Any],
    field_name: str,
    incoming_was_set: bool = True,
) -> str | None:
    if existing is not None and not incoming_was_set:
        return getattr(existing, field_name)
    incoming_prompt = _first_text(incoming)
    incoming_materialized_prompt = _first_text(incoming_context.get("materialized_prompt"))
    if incoming_prompt:
        if (
            existing is not None
            and incoming_materialized_prompt
            and incoming_prompt != incoming_materialized_prompt
            and incoming_prompt in _known_system_prompts(existing, incoming_context)
        ):
            return incoming_materialized_prompt
        return incoming
    if existing is None:
        return incoming_materialized_prompt or incoming
    has_materialized_context = bool(
        incoming_materialized_prompt
        or existing.input_context.get("materialized_prompt")
        or existing.metadata.get("system_materialized_prompt")
        or existing.metadata.get("materialized_prompt")
    )
    if not has_materialized_context:
        return incoming
    if _existing_has_manual_prompt(existing):
        preferred = getattr(existing, field_name)
        return preferred or existing.prompt or existing.override_prompt or incoming
    if incoming_materialized_prompt:
        return incoming_materialized_prompt
    preferred = getattr(existing, field_name)
    return preferred or existing.prompt or existing.override_prompt or incoming


def _preserved_input_context(
    incoming: dict[str, Any],
    existing: WorkflowGraphNode | None,
    incoming_was_set: bool = True,
) -> dict[str, Any]:
    context = dict(incoming or {})
    for omitted_key in GRAPH_INPUT_CONTEXT_OMIT_KEYS:
        context.pop(omitted_key, None)
    if existing is None:
        return context
    if not incoming_was_set:
        return dict(existing.input_context)
    for key in PRESERVED_SYSTEM_INPUT_CONTEXT_KEYS:
        if _has_value(context.get(key)):
            continue
        existing_value = existing.input_context.get(key)
        if _has_value(existing_value):
            context[key] = existing_value
    return context


def _preserved_input_assets(
    incoming: list[dict[str, Any]],
    existing: WorkflowGraphNode | None,
    input_context: dict[str, Any],
) -> list[dict[str, Any]]:
    if incoming:
        return incoming
    materialized_assets = input_context.get("materialized_assets")
    if isinstance(materialized_assets, list) and materialized_assets:
        return [asset for asset in materialized_assets if isinstance(asset, dict)]
    if existing is not None:
        return existing.input_assets
    return incoming


def _preserved_metadata(
    incoming: dict[str, Any],
    existing: WorkflowGraphNode | None,
    input_context: dict[str, Any],
    incoming_was_set: bool = True,
) -> dict[str, Any]:
    metadata = dict(incoming or {})
    metadata.pop("materialized_assets", None)
    metadata.pop("resolved_input_assets", None)
    if existing is not None:
        if not incoming_was_set:
            metadata = dict(existing.metadata)
        for key in PRESERVED_SYSTEM_METADATA_KEYS:
            if _has_value(metadata.get(key)):
                continue
            existing_value = existing.metadata.get(key)
            if _has_value(existing_value):
                metadata[key] = existing_value
    materialized_prompt = input_context.get("materialized_prompt")
    if _has_value(materialized_prompt):
        previous_prompt = _first_text(
            metadata.get("system_materialized_prompt"),
            metadata.get("materialized_prompt"),
        )
        if previous_prompt and previous_prompt != materialized_prompt:
            metadata.setdefault("previous_system_materialized_prompt", previous_prompt)
        metadata["system_materialized_prompt"] = materialized_prompt
        metadata["materialized_prompt"] = materialized_prompt
    for key in (
        "source_mappings",
        "resolved_input_context",
    ):
        value = input_context.get(key)
        if _has_value(value):
            metadata[key] = value
    return metadata


def _existing_has_manual_prompt(existing: WorkflowGraphNode) -> bool:
    if existing.metadata.get("prompt_source") != "user" and (
        existing.metadata.get("manual_prompt_dirty") is not True
    ):
        return False
    return bool(_first_text(existing.prompt, existing.override_prompt))


def _known_system_prompts(
    existing: WorkflowGraphNode,
    incoming_context: dict[str, Any],
) -> set[str]:
    values = (
        existing.metadata.get("system_materialized_prompt"),
        existing.metadata.get("materialized_prompt"),
        existing.metadata.get("previous_system_materialized_prompt"),
        existing.input_context.get("materialized_prompt"),
        incoming_context.get("system_materialized_prompt"),
    )
    return {value for value in (_first_text(item) for item in values) if value}


def _apply_prompt_source_metadata(node: WorkflowGraphNode) -> None:
    node.metadata = _metadata_with_prompt_source(
        node.metadata,
        node.prompt,
        node.override_prompt,
        node.input_context,
    )


def _metadata_with_prompt_source(
    metadata: dict[str, Any],
    prompt: str | None,
    override_prompt: str | None,
    input_context: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(metadata or {})
    prompt_value = _first_text(prompt, override_prompt)
    if not prompt_value:
        return updated
    system_prompt = _first_text(
        updated.get("system_materialized_prompt"),
        updated.get("materialized_prompt"),
        input_context.get("materialized_prompt"),
    )
    if system_prompt and prompt_value == system_prompt:
        updated["prompt_source"] = "system"
        updated["manual_prompt_dirty"] = False
    else:
        updated["prompt_source"] = "user"
        updated["manual_prompt_dirty"] = True
    return updated


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _normalize_saved_edges(
    workflow_id: str,
    edges: list[WorkflowGraphEdgeSaveItem],
    existing_edges: list[WorkflowGraphEdge] | None = None,
) -> list[WorkflowGraphEdge]:
    normalized_edges: list[WorkflowGraphEdge] = []
    used_edge_ids: set[str] = set()
    existing_by_id = {edge.id: edge for edge in existing_edges or []}
    existing_by_identity = {
        _edge_identity(edge.source_node_id, edge.target_node_id, edge.label): edge
        for edge in existing_edges or []
    }
    existing_by_pair = _unique_existing_edges_by_pair(existing_edges or [])
    for item in edges:
        source_node_id = item.source_node_id or item.source
        target_node_id = item.target_node_id or item.target
        if not source_node_id:
            raise WorkflowGraphError("source_node_id is required")
        if not target_node_id:
            raise WorkflowGraphError("target_node_id is required")
        existing = _existing_edge_for_save_item(
            item,
            source_node_id,
            target_node_id,
            existing_by_id,
            existing_by_identity,
            existing_by_pair,
        )
        edge_id = _unique_edge_id(
            _edge_id_for_save_item(item, existing, source_node_id, target_node_id),
            used_edge_ids,
        )
        used_edge_ids.add(edge_id)
        label = _preserved_edge_field(item, existing, "label")
        normalized_edges.append(
            WorkflowGraphEdge(
                id=edge_id,
                workflow_id=workflow_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                source_handle=_preserved_edge_field(item, existing, "source_handle") or "",
                target_handle=_preserved_edge_field(item, existing, "target_handle") or "",
                label=label,
                mapping=_preserved_edge_mapping(item, existing, label),
                required=_preserved_edge_field(item, existing, "required"),
            )
        )
    return normalized_edges


def _existing_edge_for_save_item(
    item: WorkflowGraphEdgeSaveItem,
    source_node_id: str,
    target_node_id: str,
    existing_by_id: dict[str, WorkflowGraphEdge],
    existing_by_identity: dict[tuple[str, str, str | None], WorkflowGraphEdge],
    existing_by_pair: dict[tuple[str, str], WorkflowGraphEdge],
) -> WorkflowGraphEdge | None:
    if item.id and item.id in existing_by_id:
        return existing_by_id[item.id]
    if "label" in item.model_fields_set:
        return existing_by_identity.get(_edge_identity(source_node_id, target_node_id, item.label))
    return existing_by_pair.get((source_node_id, target_node_id))


def _unique_existing_edges_by_pair(
    existing_edges: list[WorkflowGraphEdge],
) -> dict[tuple[str, str], WorkflowGraphEdge]:
    edges_by_pair: dict[tuple[str, str], WorkflowGraphEdge] = {}
    duplicate_pairs: set[tuple[str, str]] = set()
    for edge in existing_edges:
        pair = (edge.source_node_id, edge.target_node_id)
        if pair in edges_by_pair:
            duplicate_pairs.add(pair)
            continue
        edges_by_pair[pair] = edge
    for pair in duplicate_pairs:
        edges_by_pair.pop(pair, None)
    return edges_by_pair


def _edge_id_for_save_item(
    item: WorkflowGraphEdgeSaveItem,
    existing: WorkflowGraphEdge | None,
    source_node_id: str,
    target_node_id: str,
) -> str:
    if item.id:
        return item.id
    if existing is not None:
        return existing.id
    return _edge_id(source_node_id, target_node_id)


def _edge_identity(
    source_node_id: str,
    target_node_id: str,
    label: str | None,
) -> tuple[str, str, str | None]:
    return (source_node_id, target_node_id, label)


def _preserved_edge_field(
    item: WorkflowGraphEdgeSaveItem,
    existing: WorkflowGraphEdge | None,
    field_name: str,
) -> Any:
    if field_name in item.model_fields_set or existing is None:
        return getattr(item, field_name)
    return getattr(existing, field_name)


def _preserved_edge_mapping(
    item: WorkflowGraphEdgeSaveItem,
    existing: WorkflowGraphEdge | None,
    label: str | None,
) -> list[dict[str, Any]]:
    if "mapping" not in item.model_fields_set and existing is not None:
        return existing.mapping
    return item.mapping or _default_mapping(label)


def _handles_or_default(
    node_type: str,
    handles: WorkflowNodeHandles | None,
) -> WorkflowNodeHandles:
    if handles is None or (not handles.inputs and not handles.outputs):
        return get_node_handles(node_type)
    return handles


def _unique_edge_id(base_edge_id: str, used_edge_ids: set[str]) -> str:
    if base_edge_id not in used_edge_ids:
        return base_edge_id
    suffix = 2
    while f"{base_edge_id}_{suffix}" in used_edge_ids:
        suffix += 1
    return f"{base_edge_id}_{suffix}"


def _normalize_graph_edge(edge: WorkflowGraphEdge) -> None:
    edge.source_handle, edge.target_handle = normalize_edge_handles(
        edge.source_node_id,
        edge.target_node_id,
        edge.source_handle,
        edge.target_handle,
        edge.label,
    )
    if not edge.mapping:
        edge.mapping = _default_mapping(edge.label)


def _normalize_graph_edges(graph: WorkflowGraph) -> bool:
    changed = False
    for edge in graph.edges:
        before = (
            edge.source_handle,
            edge.target_handle,
            tuple(json.dumps(item, sort_keys=True) for item in edge.mapping),
        )
        _normalize_graph_edge(edge)
        after = (
            edge.source_handle,
            edge.target_handle,
            tuple(json.dumps(item, sort_keys=True) for item in edge.mapping),
        )
        changed = changed or before != after
    return changed


def _raw_graph_edge_handles_differ(raw_payload: dict[str, Any], graph: WorkflowGraph) -> bool:
    raw_edges = raw_payload.get("edges")
    if not isinstance(raw_edges, list):
        return False
    graph_edges = {edge.id: edge for edge in graph.edges}
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            continue
        edge = graph_edges.get(str(raw_edge.get("id") or ""))
        if edge is None and index < len(graph.edges):
            edge = graph.edges[index]
        if edge is None:
            return True
        raw_source_handle = raw_edge.get("source_handle", raw_edge.get("sourceHandle", ""))
        raw_target_handle = raw_edge.get("target_handle", raw_edge.get("targetHandle", ""))
        if raw_source_handle != edge.source_handle or raw_target_handle != edge.target_handle:
            return True
    return False


def _edge_id(source: str, target: str) -> str:
    return f"edge_{_slug(source)}_to_{_slug(target)}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")


def _default_mapping(label: str | None) -> list[dict[str, str]]:
    return [{"from": "output", "to": f"input_context.{label or 'input'}"}]


def _hash_payload(payload: Any) -> str:
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
