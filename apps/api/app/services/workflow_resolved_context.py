from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.asset_library_references import reference_context_for_node
from app.services.director_context import load_director_context
from app.services.workflow_media_segments import (
    load_workflow_segments,
    segment_readiness,
    storyboard_video_output_from_segments,
)
from app.services.workflow_resolved_assets import active_output_assets

SYSTEM_INPUT_CONTEXT_KEYS = {
    "system_resolved_prompt_preview",
    "system_resolved_prompt_with_assets",
    "resolved_input_context",
    "resolved_input_assets",
    "materialized_prompt",
    "materialized_assets",
    "source_mappings",
}

_ACTIVE_CONTEXT_DEPENDENCIES: dict[str, tuple[tuple[str, str], ...]] = {
    "script": (
        ("requirements", "requirements-analysis"),
        ("creative_direction", "creative-direction"),
        ("product_design", "product-design"),
    ),
    "character-design": (
        ("requirements", "requirements-analysis"),
        ("creative_direction", "creative-direction"),
        ("script", "script"),
    ),
    "scene-design": (
        ("requirements", "requirements-analysis"),
        ("creative_direction", "creative-direction"),
        ("script", "script"),
    ),
    "character-generation": (("script", "script"),),
    "scene-generation": (("script", "script"),),
    "bgm": (
        ("script", "script"),
        ("storyboard", "storyboard"),
    ),
    "character-image-generation": (("character_design", "character-design"),),
    "scene-image-generation": (("scene_design", "scene-design"),),
    "storyboard": (
        ("script", "script"),
        ("product_generation", "product-generation"),
        ("character_generation", "character-generation"),
        ("scene_generation", "scene-generation"),
    ),
    "storyboard-image-generation": (
        ("storyboard", "storyboard"),
        ("script", "script"),
        ("character_design", "character-design"),
        ("scene_design", "scene-design"),
    ),
}


def resolved_context(
    node_id: str,
    active: dict[str, dict[str, Any]],
    graph_node: WorkflowGraphNode,
    graph: WorkflowGraph,
    data_dir: Path,
) -> dict[str, Any]:
    context = stored_resolved_context(graph_node)
    if graph_node.input_context:
        merge_non_empty(context, without_system_context(graph_node.input_context))
    fallback = input_context_from_active(
        graph_node.node_type,
        active,
        data_dir,
        graph_node.workflow_id,
    )
    edge_context = context_from_edge_mapping(graph_node, active, graph)
    merge_non_empty(context, fallback)
    merge_non_empty(context, edge_context)
    merge_director_context_fields(context, data_dir, graph_node.workflow_id, graph_node.node_type)
    context.setdefault("target_node_id", graph_node.id)
    context.setdefault("target_node_type", graph_node.node_type)
    return context


def context_from_edge_mapping(
    graph_node: WorkflowGraphNode,
    active: dict[str, dict[str, Any]],
    graph: WorkflowGraph,
) -> dict[str, Any]:
    incoming_edges = [edge for edge in graph.edges if edge.target_node_id == graph_node.id]
    if not incoming_edges:
        return {}
    context: dict[str, Any] = {}
    nodes_by_id = {node.id: node for node in graph.nodes}
    for edge in incoming_edges:
        upstream_node = nodes_by_id.get(edge.source_node_id)
        upstream = (
            active_or_graph_payload(active, upstream_node)
            if upstream_node is not None
            else active.get(edge.source_node_id, {})
        )
        upstream_output = upstream.get("output") if isinstance(upstream, dict) else None
        if not isinstance(upstream_output, dict):
            upstream_output = {}
        merge_edge_mapping_context(context, edge, upstream_output, upstream)
    return context


def merge_edge_mapping_context(
    context: dict[str, Any],
    edge: Any,
    upstream_output: dict[str, Any],
    upstream: dict[str, Any],
) -> None:
    for item in edge_mapping_or_default(edge):
        if not isinstance(item, dict):
            continue
        from_path = str(item.get("from") or "output")
        to_path = str(item.get("to") or "")
        if not to_path:
            continue
        value = extract_upstream_value(upstream_output, from_path, upstream)
        if value is None:
            continue
        target_key = normalize_mapping_target(to_path)
        if target_key:
            context[target_key] = value


def extract_upstream_value(
    upstream_output: dict[str, Any],
    from_path: str,
    upstream_payload: dict[str, Any],
) -> Any:
    if from_path in {"output", "output:text", "output:prompt", "output:json", "output:any"}:
        return upstream_output
    if from_path in {"output:image", "output:video", "output:audio", "output:asset"}:
        assets = active_output_assets(upstream_payload)
        return assets if assets else upstream_output
    if from_path == "output_assets":
        assets = upstream_payload.get("output_assets")
        return assets if isinstance(assets, list) else None
    if from_path.startswith("output."):
        return nested_output_value(upstream_output, from_path[len("output.") :])
    if from_path in upstream_output:
        return upstream_output[from_path]
    return None


def nested_output_value(upstream_output: dict[str, Any], dotted_path: str) -> Any:
    current: Any = upstream_output
    for key in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def normalize_mapping_target(to_path: str) -> str | None:
    if to_path.startswith("input_context."):
        return to_path[len("input_context.") :] or None
    if to_path in {"input:text", "input:prompt"}:
        return "prompt"
    if to_path in {"input:image", "input:video", "input:audio", "input:asset"}:
        return None
    if to_path == "input_context":
        return None
    return to_path or None


def edge_mapping_or_default(edge: Any) -> list[dict[str, Any]]:
    if edge.mapping:
        return edge.mapping
    return [{"from": "output", "to": f"input_context.{edge.label or 'input'}"}]


def reference_context_fields(context: dict[str, Any], node_id: str) -> dict[str, Any]:
    references = context.get("asset_references")
    if not isinstance(references, list):
        references = []
    reference_context = reference_context_for_node(
        [reference for reference in references if isinstance(reference, dict)],
        node_id,
    )
    context["asset_references"] = reference_context["asset_references"]
    context["asset_bindings"] = reference_context["asset_bindings"]
    context["prompt_context_assets"] = reference_context["prompt_context_assets"]
    context["provider_reference_assets"] = reference_context["provider_reference_assets"]
    context["display_input_assets"] = reference_context["display_input_assets"]
    return reference_context


def merge_director_context_fields(
    context: dict[str, Any],
    data_dir: Path,
    workflow_id: str,
    node_type: str,
) -> None:
    if context.get("ad_type") and context.get("recommended_skill_groups"):
        return
    director_context = load_director_context(data_dir, workflow_id)
    if director_context is None:
        return
    context.setdefault("ad_type", director_context.ad_type)
    recommended = director_context.recommended_skill_groups.get(node_type, [])
    if recommended and not context.get("recommended_skill_groups"):
        context["recommended_skill_groups"] = recommended
    context.setdefault(
        "director_context",
        {
            "workflow_id": director_context.workflow_id,
            "version": director_context.version,
            "ad_type": director_context.ad_type,
            "ad_type_confidence": director_context.ad_type_confidence,
            "node_briefs": director_context.node_briefs.model_dump(mode="json"),
            "recommended_skill_groups": director_context.recommended_skill_groups,
            "references": director_context.references,
        },
    )
    if not context.get("asset_references"):
        reference_context = reference_context_for_node(director_context.references, node_type)
        context["asset_references"] = reference_context["asset_references"]
        context["asset_bindings"] = reference_context["asset_bindings"]
        context["prompt_context_assets"] = reference_context["prompt_context_assets"]
        context["provider_reference_assets"] = reference_context["provider_reference_assets"]
        context["display_input_assets"] = reference_context["display_input_assets"]


def with_final_composition_segment_defaults(
    context: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any]:
    resolved = dict(context)
    segments = resolved.get("segments")
    if not isinstance(segments, list):
        segments = []
    resolved["segments"] = segments
    resolved.setdefault("storyboard_video", {})
    resolved.update(segment_readiness(data_dir, [s for s in segments if isinstance(s, dict)]))
    return resolved


def input_context_from_active(
    node_type: str,
    active: dict[str, dict[str, Any]],
    data_dir: Path,
    workflow_id: str,
) -> dict[str, Any]:
    if node_type == "storyboard-video-generation":
        context = input_context_from_dependencies(
            active,
            (
                ("storyboard", "storyboard"),
                ("script", "script"),
                ("product_generation", "product-generation"),
                ("character_generation", "character-generation"),
                ("scene_generation", "scene-generation"),
            ),
        )
        context["duration_seconds"] = duration_from_script(active)
        return context
    if node_type == "final-composition":
        return final_composition_context_from_active(active, data_dir, workflow_id)
    return input_context_from_dependencies(active, _ACTIVE_CONTEXT_DEPENDENCIES.get(node_type, ()))


def input_context_from_dependencies(
    active: dict[str, dict[str, Any]],
    dependencies: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    return {context_key: output(active, node_type) for context_key, node_type in dependencies}


def final_composition_context_from_active(
    active: dict[str, dict[str, Any]],
    data_dir: Path,
    workflow_id: str,
) -> dict[str, Any]:
    video_output = output(active, "storyboard-video-generation")
    latest_segments = load_workflow_segments(data_dir, workflow_id)
    if latest_segments:
        latest_video_output = storyboard_video_output_from_segments(
            data_dir,
            workflow_id,
            latest_segments,
            existing_output=video_output if isinstance(video_output, dict) else {},
        )
        return {
            "storyboard_video": latest_video_output,
            "segments": latest_segments,
            "bgm": output(active, "bgm"),
            **segment_readiness(data_dir, latest_segments),
        }
    readiness = segment_readiness(data_dir, [])
    return {
        "storyboard_video": {
            key: value
            for key, value in video_output.items()
            if key not in {"segments", "source_segments"}
        }
        if isinstance(video_output, dict)
        else {},
        "segments": [],
        "bgm": output(active, "bgm"),
        **readiness,
    }


def active_or_graph_payload(
    active: dict[str, dict[str, Any]],
    graph_node: WorkflowGraphNode,
) -> dict[str, Any]:
    active_payload = active.get(graph_node.id)
    if isinstance(active_payload, dict) and has_resolved_output(active_payload):
        return active_payload
    if graph_node.output or graph_node.output_assets:
        return {
            "workflow_id": graph_node.workflow_id,
            "node_id": graph_node.id,
            "node_type": graph_node.node_type,
            "status": graph_node.status,
            "output": graph_node.output,
            "input_assets": graph_node.input_assets,
            "output_assets": graph_node.output_assets,
        }
    return active_payload if isinstance(active_payload, dict) else {}


def has_resolved_output(payload: dict[str, Any]) -> bool:
    return bool(payload.get("output") or payload.get("output_assets"))


def stored_resolved_context(graph_node: WorkflowGraphNode) -> dict[str, Any]:
    resolved = graph_node.input_context.get("resolved_input_context")
    return dict(resolved) if isinstance(resolved, dict) else {}


def merge_non_empty(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if value in (None, "", {}, []):
            continue
        target[key] = value


def without_system_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key not in SYSTEM_INPUT_CONTEXT_KEYS}


def output(active: dict[str, dict[str, Any]], node_type: str) -> dict[str, Any]:
    node_output = active.get(node_type, {}).get("output")
    return node_output if isinstance(node_output, dict) else {}


def duration_from_script(active: dict[str, dict[str, Any]]) -> int:
    script = output(active, "script")
    try:
        return int(script.get("duration_seconds") or 30)
    except (TypeError, ValueError):
        return 30
