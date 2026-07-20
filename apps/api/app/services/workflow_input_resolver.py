from collections import Counter
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.schemas.workflow_nodes import ResolvedNodeInputsResponse
from app.services.workflow_graph import load_graph, save_graph
from app.services.workflow_materialized_inputs import (
    first_text as _first_text,
    has_manual_prompt as _has_manual_prompt,
    materialized_inputs as _materialized_inputs,
    previous_system_materialized_prompt as _previous_system_materialized_prompt,
    should_sync_materialized_prompt as _should_sync_materialized_prompt,
    update_materialized_metadata as _update_materialized_metadata,
)
from app.services.workflow_media_segments import (
    load_workflow_segments,
    sync_storyboard_video_run_with_segments,
)
from app.services.workflow_resolved_assets import (
    merge_assets as _merge_assets,
    resolved_assets as _resolved_assets,
)
from app.services.workflow_resolved_context import (
    active_or_graph_payload as _active_or_graph_payload,
    reference_context_fields as _reference_context_fields,
    resolved_context as _resolved_context,
    with_final_composition_segment_defaults as _with_final_composition_segment_defaults,
    without_system_context as _without_system_context,
)
from app.services.workflow_shot_bindings import enrich_storyboard_context
from app.services.workflow_state import load_active_node_results
from app.services.workflow_target_projection import (
    append_script_refresh_to_system_prompt as _append_script_refresh_to_system_prompt,
    append_storyboard_bgm_context_to_system_prompt as _append_storyboard_bgm_context_to_system_prompt,
    merge_target_aware_context as _merge_target_aware_context,
    node_system_prompt as _node_system_prompt,
    target_aware_assets as _target_aware_assets,
    target_aware_input_context as _target_aware_input_context,
    target_aware_source_mappings as _target_aware_source_mappings,
)


class WorkflowInputResolutionError(ValueError):
    """Raised when workflow node inputs cannot be resolved."""


class WorkflowNodeInputResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve_node_inputs(self, workflow_id: str, node_id: str) -> ResolvedNodeInputsResponse:
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            raise WorkflowInputResolutionError(f"workflow graph not found: {workflow_id}")
        if node_id == "final-composition":
            latest_segments = load_workflow_segments(self._settings.media_data_dir, workflow_id)
            if latest_segments:
                sync_storyboard_video_run_with_segments(
                    self._settings.media_data_dir,
                    workflow_id,
                    latest_segments,
                )
                graph = load_graph(self._settings.media_data_dir, workflow_id) or graph
        node = _require_graph_node(graph, node_id)
        active = load_active_node_results(self._settings.media_data_dir, workflow_id)
        context = _resolved_context(node_id, active, node, graph, self._settings.media_data_dir)
        assets = _resolved_assets(
            node.node_type, active, graph, node, self._settings.media_data_dir
        )
        reference_context = _reference_context_fields(context, node.id)
        assets = _merge_assets(reference_context["display_input_assets"], assets)
        context = _enrich_storyboard_binding_context(node.node_type, context, assets)
        (
            generic_materialized_prompt,
            generic_materialized_assets,
            generic_source_mappings,
        ) = _materialized_inputs(node, active, graph)
        target_aware = _target_aware_input_context(
            node,
            active,
            graph,
            context,
            self._settings.media_data_dir,
        )
        if target_aware:
            context = _merge_target_aware_context(context, target_aware)
            materialized_prompt = _first_text(target_aware.get("materialized_prompt"))
            materialized_assets = _target_aware_assets(
                target_aware,
                generic_materialized_assets,
                assets,
            )
            source_mappings = _target_aware_source_mappings(
                target_aware,
                node.id,
                generic_source_mappings,
            )
        else:
            materialized_prompt = (
                _node_system_prompt(node, graph, self._settings.media_data_dir)
                or generic_materialized_prompt
            )
            materialized_assets = generic_materialized_assets
            source_mappings = _source_mappings_with_director(node, generic_source_mappings)
        if node.node_type == "bgm":
            materialized_prompt = _append_storyboard_bgm_context_to_system_prompt(
                materialized_prompt,
                context.get("storyboard"),
            )
        context = _enrich_storyboard_binding_context(node.node_type, context, assets)
        if node.node_type == "final-composition":
            materialized_assets = assets
        if node.node_type == "final-composition":
            context = _with_final_composition_segment_defaults(
                context,
                self._settings.media_data_dir,
            )
        source_mappings = _source_mappings_with_asset_references(
            reference_context["source_mappings"],
            source_mappings,
        )
        source_mappings = _source_mappings_with_media_segments(node, source_mappings, context)
        source_mappings = _source_mappings_with_storyboard_bindings(node, source_mappings, context)
        upstream_nodes = _upstream_nodes(graph, node_id)
        missing_inputs = _missing_inputs(upstream_nodes, active)
        missing_inputs.extend(_missing_required_context(node_id, context, missing_inputs))
        stale_upstream_nodes = [
            {
                "node_id": upstream.id,
                "node_type": upstream.node_type,
                "stale_reason": upstream.stale_reason,
            }
            for upstream in upstream_nodes
            if upstream.stale
        ]
        locked_upstream_nodes = [
            {"node_id": upstream.id, "node_type": upstream.node_type}
            for upstream in upstream_nodes
            if upstream.locked
        ]
        prompt_preview = (
            _first_text(target_aware.get("system_resolved_prompt_preview"))
            if target_aware
            else None
        ) or _prompt_preview(node, upstream_nodes, context, assets)
        prompt_with_assets = (
            _first_text(target_aware.get("system_resolved_prompt_with_assets"))
            if target_aware
            else None
        ) or _prompt_with_assets(node, context, assets)
        effective_prompt = _effective_prompt(prompt_preview, node.override_prompt)
        return ResolvedNodeInputsResponse(
            node_id=node.id,
            node_type=node.node_type,
            upstream_nodes=[
                {
                    "node_id": upstream.id,
                    "node_type": upstream.node_type,
                    "status": upstream.status,
                    "stale": upstream.stale,
                    "locked": upstream.locked,
                }
                for upstream in upstream_nodes
            ],
            resolved_input_context=context,
            resolved_input_assets=assets,
            asset_references=reference_context["asset_references"],
            prompt_context_assets=reference_context["prompt_context_assets"],
            provider_reference_assets=reference_context["provider_reference_assets"],
            display_input_assets=reference_context["display_input_assets"],
            materialized_prompt=materialized_prompt,
            materialized_assets=materialized_assets,
            source_mappings=source_mappings,
            resolved_prompt_preview=prompt_preview,
            resolved_prompt_with_assets=prompt_with_assets,
            missing_inputs=missing_inputs,
            stale_upstream_nodes=stale_upstream_nodes,
            locked_upstream_nodes=locked_upstream_nodes,
            effective_prompt=effective_prompt,
        )

    def update_downstream_resolved_inputs(
        self,
        workflow_id: str,
        source_node_id: str,
    ) -> list[str]:
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            return []
        affected = _downstream_node_ids(graph, source_node_id)
        if not affected:
            return []
        active = load_active_node_results(self._settings.media_data_dir, workflow_id)
        nodes_by_id = {node.id: node for node in graph.nodes}
        for downstream_id in affected:
            node = nodes_by_id[downstream_id]
            self._refresh_downstream_node_inputs(
                workflow_id=workflow_id,
                source_node_id=source_node_id,
                downstream_id=downstream_id,
                node=node,
                graph=graph,
                active=active,
            )
        save_graph(self._settings.media_data_dir, graph)
        return affected

    def _refresh_downstream_node_inputs(
        self,
        *,
        workflow_id: str,
        source_node_id: str,
        downstream_id: str,
        node: WorkflowGraphNode,
        graph: WorkflowGraph,
        active: dict[str, dict[str, Any]],
    ) -> None:
        previous_system_prompt = _previous_system_materialized_prompt(node)
        self._mark_downstream_node_changed(node, source_node_id)
        payload = self._downstream_resolved_payload(
            workflow_id=workflow_id,
            source_node_id=source_node_id,
            downstream_id=downstream_id,
            node=node,
            graph=graph,
            active=active,
        )
        self._persist_downstream_resolved_payload(
            node,
            payload=payload,
            previous_system_prompt=previous_system_prompt,
        )

    def _mark_downstream_node_changed(
        self,
        node: WorkflowGraphNode,
        source_node_id: str,
    ) -> None:
        if node.locked:
            node.stale_reason = (
                f"locked node not auto-marked stale after upstream {source_node_id} changed"
            )
            return
        node.stale = True
        node.status = "stale"
        node.stale_reason = f"upstream {source_node_id} changed"

    def _downstream_resolved_payload(
        self,
        *,
        workflow_id: str,
        source_node_id: str,
        downstream_id: str,
        node: WorkflowGraphNode,
        graph: WorkflowGraph,
        active: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        context = _resolved_context(
            downstream_id,
            active,
            node,
            graph,
            self._settings.media_data_dir,
        )
        assets = _resolved_assets(
            node.node_type, active, graph, node, self._settings.media_data_dir
        )
        reference_context = _reference_context_fields(context, node.id)
        assets = _merge_assets(reference_context["display_input_assets"], assets)
        context = _enrich_storyboard_binding_context(node.node_type, context, assets)
        generic_prompt, generic_assets, generic_mappings = _materialized_inputs(node, active, graph)
        target_aware = _target_aware_input_context(
            node,
            active,
            graph,
            context,
            self._settings.media_data_dir,
        )
        if target_aware:
            payload = self._target_aware_downstream_payload(
                node=node,
                context=context,
                assets=assets,
                target_aware=target_aware,
                generic_assets=generic_assets,
                generic_mappings=generic_mappings,
            )
        else:
            payload = self._generic_downstream_payload(
                source_node_id=source_node_id,
                downstream_id=downstream_id,
                node=node,
                graph=graph,
                context=context,
                assets=assets,
                generic_prompt=generic_prompt,
                generic_assets=generic_assets,
                generic_mappings=generic_mappings,
            )
        payload["workflow_id"] = workflow_id
        return self._finalize_downstream_payload(node, reference_context, payload)

    def _target_aware_downstream_payload(
        self,
        *,
        node: WorkflowGraphNode,
        context: dict[str, Any],
        assets: list[dict[str, Any]],
        target_aware: dict[str, Any],
        generic_assets: list[dict[str, Any]],
        generic_mappings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "context": _merge_target_aware_context(context, target_aware),
            "assets": assets,
            "materialized_prompt": _first_text(target_aware.get("materialized_prompt")),
            "materialized_assets": _target_aware_assets(target_aware, generic_assets, assets),
            "source_mappings": _target_aware_source_mappings(
                target_aware,
                node.id,
                generic_mappings,
            ),
            "preview": _first_text(target_aware.get("system_resolved_prompt_preview")) or "",
            "prompt_with_assets": _first_text(
                target_aware.get("system_resolved_prompt_with_assets")
            ),
        }

    def _generic_downstream_payload(
        self,
        *,
        source_node_id: str,
        downstream_id: str,
        node: WorkflowGraphNode,
        graph: WorkflowGraph,
        context: dict[str, Any],
        assets: list[dict[str, Any]],
        generic_prompt: str | None,
        generic_assets: list[dict[str, Any]],
        generic_mappings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        materialized_prompt = (
            _node_system_prompt(node, graph, self._settings.media_data_dir) or generic_prompt
        )
        if source_node_id == "script":
            materialized_prompt = _append_script_refresh_to_system_prompt(
                materialized_prompt,
                context.get("script"),
            )
        if node.node_type == "bgm":
            materialized_prompt = _append_storyboard_bgm_context_to_system_prompt(
                materialized_prompt,
                context.get("storyboard"),
            )
        return {
            "context": context,
            "assets": assets,
            "materialized_prompt": materialized_prompt,
            "materialized_assets": generic_assets,
            "source_mappings": _source_mappings_with_director(node, generic_mappings),
            "preview": _prompt_preview(
                node, _upstream_nodes(graph, downstream_id), context, assets
            ),
            "prompt_with_assets": _prompt_with_assets(node, context, assets),
        }

    def _finalize_downstream_payload(
        self,
        node: WorkflowGraphNode,
        reference_context: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context = _enrich_storyboard_binding_context(
            node.node_type,
            payload["context"],
            payload["assets"],
        )
        materialized_assets = (
            payload["assets"]
            if node.node_type == "final-composition"
            else payload["materialized_assets"]
        )
        source_mappings = _source_mappings_with_asset_references(
            reference_context["source_mappings"],
            payload["source_mappings"],
        )
        source_mappings = _source_mappings_with_media_segments(node, source_mappings, context)
        source_mappings = _source_mappings_with_storyboard_bindings(node, source_mappings, context)
        return {
            **payload,
            "context": context,
            "materialized_assets": materialized_assets,
            "source_mappings": source_mappings,
            "reference_context": reference_context,
        }

    def _persist_downstream_resolved_payload(
        self,
        node: WorkflowGraphNode,
        *,
        payload: dict[str, Any],
        previous_system_prompt: str | None,
    ) -> None:
        materialized_prompt = payload["materialized_prompt"]
        materialized_assets = payload["materialized_assets"]
        node.input_context = _without_system_context(node.input_context)
        node.input_context.update(
            {
                "system_resolved_prompt_preview": payload["preview"],
                "system_resolved_prompt_with_assets": payload["prompt_with_assets"],
                "resolved_input_context": payload["context"],
                "materialized_prompt": materialized_prompt,
                "source_mappings": payload["source_mappings"],
                "asset_references": payload["reference_context"]["asset_references"],
                "prompt_context_assets": payload["reference_context"]["prompt_context_assets"],
                "provider_reference_assets": payload["reference_context"][
                    "provider_reference_assets"
                ],
                "display_input_assets": payload["reference_context"]["display_input_assets"],
            }
        )
        _update_materialized_metadata(
            node,
            materialized_prompt=materialized_prompt,
            materialized_assets=materialized_assets,
            source_mappings=payload["source_mappings"],
            resolved_input_context=payload["context"],
            resolved_input_assets=payload["assets"],
            resolved_prompt_preview=payload["preview"],
            resolved_prompt_with_assets=payload["prompt_with_assets"],
            previous_system_prompt=previous_system_prompt,
        )
        self._sync_downstream_prompt_metadata(
            node,
            materialized_prompt=materialized_prompt,
            previous_system_prompt=previous_system_prompt,
        )
        if materialized_assets:
            node.input_assets = _merge_assets(node.input_assets, materialized_assets)

    def _sync_downstream_prompt_metadata(
        self,
        node: WorkflowGraphNode,
        *,
        materialized_prompt: str | None,
        previous_system_prompt: str | None,
    ) -> None:
        if not materialized_prompt:
            return
        if _should_sync_materialized_prompt(node, previous_system_prompt):
            node.prompt = materialized_prompt
            node.override_prompt = materialized_prompt
            node.metadata["prompt_source"] = "system"
            node.metadata["manual_prompt_dirty"] = False
        elif _has_manual_prompt(node, previous_system_prompt, materialized_prompt):
            node.metadata["prompt_source"] = "user"
            node.metadata["manual_prompt_dirty"] = True


def _require_graph_node(graph: WorkflowGraph, node_id: str) -> WorkflowGraphNode:
    for node in graph.nodes:
        if node.id == node_id:
            return node
    raise WorkflowInputResolutionError(f"workflow node not found: {node_id}")


def _upstream_nodes(graph: WorkflowGraph, node_id: str) -> list[WorkflowGraphNode]:
    node_ids = [
        edge.source_node_id
        for edge in graph.edges
        if edge.target_node_id == node_id and edge.required
    ]
    nodes_by_id = {node.id: node for node in graph.nodes}
    return [nodes_by_id[upstream_id] for upstream_id in node_ids if upstream_id in nodes_by_id]


def _downstream_node_ids(graph: WorkflowGraph, node_id: str) -> list[str]:
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    seen: set[str] = set()
    queue = list(outgoing.get(node_id, []))
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        queue.extend(outgoing.get(current, []))
    return ordered


def _missing_inputs(
    upstream_nodes: list[WorkflowGraphNode],
    active: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for upstream in upstream_nodes:
        active_payload = _active_or_graph_payload(active, upstream)
        output = active_payload.get("output") if isinstance(active_payload, dict) else None
        output_assets = (
            active_payload.get("output_assets") if isinstance(active_payload, dict) else None
        )
        if not active_payload or not output and not output_assets:
            missing.append(
                {
                    "node_id": upstream.id,
                    "node_type": upstream.node_type,
                    "reason": "upstream node has no active output",
                }
            )
    return missing


def _missing_required_context(
    node_id: str,
    context: dict[str, Any],
    existing_missing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required_context_sources = {
        "script": {
            "director_context": "director-context",
        },
        "character-generation": {"script": "script"},
        "scene-generation": {"script": "script"},
        "bgm": {
            "script": "script",
        },
        "character-image-generation": {"character_design": "character-design"},
        "scene-image-generation": {"scene_design": "scene-design"},
        "storyboard": {
            "script": "script",
        },
        "storyboard-video-generation": {"storyboard": "storyboard"},
        "final-composition": {"segments": "storyboard-video-generation"},
    }
    existing_node_ids = {item["node_id"] for item in existing_missing}
    missing: list[dict[str, Any]] = []
    for field_name, source_node_id in required_context_sources.get(node_id, {}).items():
        if source_node_id in existing_node_ids:
            continue
        value = context.get(field_name)
        if value in (None, "", {}, []):
            missing.append(
                {
                    "node_id": source_node_id,
                    "node_type": source_node_id,
                    "field": field_name,
                    "reason": f"required input context is missing: {field_name}",
                }
            )
    return missing


def _enrich_storyboard_binding_context(
    node_type: str,
    context: dict[str, Any],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    if node_type not in {"storyboard", "storyboard-video-generation"}:
        return context
    return enrich_storyboard_context(context, assets)


def _source_mappings_with_director(
    graph_node: WorkflowGraphNode,
    generic_source_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    _append_source_mapping(
        mappings,
        seen,
        {
            "source_node_id": "director-context",
            "target_node_id": graph_node.id,
            "field": "system_suggested_prompt",
        },
    )
    stored = graph_node.input_context.get("source_mappings")
    for mapping in stored if isinstance(stored, list) else []:
        if not isinstance(mapping, dict) or mapping.get("source_node_id") != "director-context":
            continue
        _append_source_mapping(mappings, seen, {**mapping, "target_node_id": graph_node.id})
    for mapping in generic_source_mappings:
        if isinstance(mapping, dict):
            _append_source_mapping(mappings, seen, {**mapping, "target_node_id": graph_node.id})
    return mappings


def _source_mappings_with_asset_references(
    reference_source_mappings: list[dict[str, Any]],
    source_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for mapping in [*source_mappings, *reference_source_mappings]:
        if isinstance(mapping, dict):
            _append_source_mapping(mappings, seen, mapping)
    return mappings


def _source_mappings_with_media_segments(
    graph_node: WorkflowGraphNode,
    source_mappings: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    if graph_node.node_type != "final-composition" or not context.get("segments"):
        return source_mappings
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for mapping in source_mappings:
        if isinstance(mapping, dict):
            _append_source_mapping(mappings, seen, mapping)
    _append_source_mapping(
        mappings,
        seen,
        {
            "source_node_id": "media-segments",
            "target_node_id": graph_node.id,
            "field": "segments",
            "from": "videos/{workflow_id}/segments/*.json",
            "to": "resolved_input_context.segments",
        },
    )
    return mappings


def _source_mappings_with_storyboard_bindings(
    graph_node: WorkflowGraphNode,
    source_mappings: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    if graph_node.node_type not in {"storyboard", "storyboard-video-generation"}:
        return source_mappings
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for mapping in source_mappings:
        if isinstance(mapping, dict):
            _append_source_mapping(mappings, seen, mapping)
    existing_source_ids = {
        str(mapping.get("source_node_id") or "")
        for mapping in mappings
        if isinstance(mapping, dict)
    }
    field_sources = {
        "scene_assets": "scene-generation",
        "character_assets": "character-generation",
        "product_assets": "product-generation",
        "shots": "storyboard"
        if graph_node.node_type == "storyboard-video-generation"
        else "script",
        "media_items": "storyboard"
        if graph_node.node_type == "storyboard-video-generation"
        else "script",
    }
    for field_name, source_node_id in field_sources.items():
        if source_node_id in existing_source_ids:
            continue
        if source_node_id == "storyboard" and not context.get("storyboard"):
            continue
        if source_node_id == "script" and not context.get("script"):
            continue
        if context.get(field_name):
            _append_source_mapping(
                mappings,
                seen,
                {
                    "source_node_id": source_node_id,
                    "target_node_id": graph_node.id,
                    "field": field_name,
                    "from": f"{source_node_id}.{field_name}",
                    "to": f"resolved_input_context.{field_name}",
                },
            )
    return mappings


def _append_source_mapping(
    mappings: list[dict[str, Any]],
    seen: set[tuple[str, str, str, str, str]],
    mapping: dict[str, Any],
) -> None:
    key = (
        str(mapping.get("source_node_id") or ""),
        str(mapping.get("target_node_id") or ""),
        str(mapping.get("edge_id") or ""),
        str(mapping.get("from") or ""),
        str(mapping.get("to") or ""),
    )
    if key in seen:
        return
    seen.add(key)
    mappings.append(mapping)


def _prompt_preview(
    node: WorkflowGraphNode,
    upstream_nodes: list[WorkflowGraphNode],
    context: dict[str, Any],
    assets: list[dict[str, Any]],
) -> str:
    lines = [f"当前节点：{node.id}", ""]
    lines.append("上游文本输入：")
    if not context:
        lines.append("- 暂无可用文本输入")
    else:
        for key, value in context.items():
            lines.append(f"- {key}：{_summarize_value(key, value)}")
    lines.append("")
    lines.append("上游媒体资产：")
    if not assets:
        lines.append("- 暂无可用媒体资产")
    else:
        role_counts = Counter(str(asset.get("role") or "reference") for asset in assets)
        for role, count in sorted(role_counts.items()):
            lines.append(f"- {role}：{count} 个")
    lines.append("")
    lines.append("执行要求：")
    lines.extend(_execution_requirements(node, context, assets, upstream_nodes))
    lines.append("")
    lines.append("用户补充要求：")
    lines.append(node.override_prompt or "无")
    return "\n".join(lines)


def _summarize_value(key: str, value: Any) -> str:
    if value in ({}, [], None, ""):
        return "暂无可用内容"
    if isinstance(value, dict):
        if isinstance(value.get("scenes"), list):
            return f"包含 {len(value['scenes'])} 个分镜/场景"
        if isinstance(value.get("characters"), list):
            return f"包含 {len(value['characters'])} 个角色设定"
        if {"hook", "body", "cta"} & set(value):
            parts = [str(value.get(name) or "") for name in ("hook", "body", "cta")]
            return "；".join(part for part in parts if part)[:160]
        if key == "requirements":
            product = value.get("product") or value.get("product_name") or "产品"
            audience = value.get("target_audience") or "目标受众"
            return f"{product}，面向 {audience}"
        keys = ", ".join(list(value.keys())[:6])
        return f"结构化内容字段：{keys}"
    if isinstance(value, list):
        return f"{len(value)} 项"
    return str(value)[:180]


def _execution_requirements(
    node: WorkflowGraphNode,
    context: dict[str, Any],
    assets: list[dict[str, Any]],
    upstream_nodes: list[WorkflowGraphNode],
) -> list[str]:
    requirements = []
    duration = context.get("duration_seconds") or node.config.get("duration_seconds")
    resolution = node.config.get("output_resolution") or context.get("output_resolution")
    aspect_ratio = node.config.get("aspect_ratio") or context.get("aspect_ratio")
    if duration:
        requirements.append(f"- 目标时长：{duration} 秒")
    if resolution:
        requirements.append(f"- 输出清晰度：{resolution}")
    if aspect_ratio:
        requirements.append(f"- 输出比例：{aspect_ratio}")
    asset_roles = {str(asset.get("role") or "") for asset in assets}
    if "character_turnaround" in asset_roles:
        requirements.append("- 使用角色三视图保持脸型、发型、服装和体型一致")
    if "scene_reference" in asset_roles:
        requirements.append("- 使用场景参考图保持空间结构、光线和色调一致")
    if "storyboard" in asset_roles:
        requirements.append("- 使用分镜图保持镜头构图和动作一致")
    if "product_reference" in asset_roles:
        requirements.append("- 使用产品图保持包装、颜色、Logo、形状和比例一致")
    if not requirements:
        upstream_names = ", ".join(upstream.id for upstream in upstream_nodes) or "当前节点配置"
        requirements.append(f"- 根据 {upstream_names} 的最新产物执行")
    return requirements


def _effective_prompt(prompt_preview: str, override_prompt: str | None) -> str:
    if not override_prompt:
        return prompt_preview
    return f"{prompt_preview}\n\n最终执行时叠加用户补充要求：\n{override_prompt}"


def _prompt_with_assets(
    node: WorkflowGraphNode,
    context: dict[str, Any],
    assets: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"当前节点：{node.id}（{node.node_type}）")
    lines.append("")
    lines.append("【上游文本产物】")
    if not context:
        lines.append("（暂无）")
    else:
        for key, value in context.items():
            rendered = _render_context_value(value)
            if rendered:
                lines.append(f"[{key}]")
                lines.append(rendered)
                lines.append("")
    lines.append("【上游媒体产物】")
    if not assets:
        lines.append("（暂无）")
    else:
        for asset in assets:
            url = (
                asset.get("public_url") or asset.get("remote_url") or asset.get("local_path") or ""
            )
            asset_type = asset.get("type") or asset.get("asset_type") or "reference"
            role = asset.get("role") or "reference"
            source = asset.get("source_node_id") or ""
            label_parts = [asset_type, role]
            if source:
                label_parts.append(f"from {source}")
            label = " / ".join(label_parts)
            if url:
                lines.append(f"[{label}] {url}")
            else:
                lines.append(f"[{label}] (无可用URL)")
    lines.append("")
    lines.append("【用户补充要求】")
    lines.append(node.override_prompt or "（无）")
    return "\n".join(lines)


def _render_context_value(value: Any) -> str:
    if value in (None, "", {}, []):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        import json

        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def compute_node_prompt_preview(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
) -> str | None:
    graph = load_graph(data_dir, workflow_id)
    if graph is None:
        return None
    try:
        node = _require_graph_node(graph, node_id)
    except WorkflowInputResolutionError:
        return None
    active = load_active_node_results(data_dir, workflow_id)
    context = _resolved_context(node_id, active, node, graph, data_dir)
    assets = _resolved_assets(node.node_type, active, graph, node, data_dir)
    reference_context = _reference_context_fields(context, node.id)
    assets = _merge_assets(reference_context["display_input_assets"], assets)
    upstream_nodes = _upstream_nodes(graph, node_id)
    return _prompt_preview(node, upstream_nodes, context, assets)


def compute_node_prompt_with_assets(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
) -> str | None:
    graph = load_graph(data_dir, workflow_id)
    if graph is None:
        return None
    try:
        node = _require_graph_node(graph, node_id)
    except WorkflowInputResolutionError:
        return None
    active = load_active_node_results(data_dir, workflow_id)
    context = _resolved_context(node_id, active, node, graph, data_dir)
    assets = _resolved_assets(node.node_type, active, graph, node, data_dir)
    reference_context = _reference_context_fields(context, node.id)
    assets = _merge_assets(reference_context["display_input_assets"], assets)
    return _prompt_with_assets(node, context, assets)
