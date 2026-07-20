import json
from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.director_context import load_director_context
from app.services.media_paths import with_public_urls
from app.services.workflow_materialized_inputs import first_text, prompt_fragments
from app.services.workflow_prompt_projection import (
    TARGET_PROMPT_NODES,
    build_projected_input_context,
)
from app.services.workflow_resolved_assets import merge_assets
from app.services.workflow_resolved_context import merge_non_empty, output
from app.services.workflow_state import planning_context_path


def target_aware_input_context(
    graph_node: WorkflowGraphNode,
    active: dict[str, dict[str, Any]],
    graph: WorkflowGraph,
    resolved_context: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any] | None:
    if should_skip_target_projection(graph_node, graph, data_dir):
        return None
    target_node_type = graph_node.node_type or graph_node.id
    target_node_key = target_node_type if target_node_type in TARGET_PROMPT_NODES else graph_node.id
    if target_node_key not in TARGET_PROMPT_NODES:
        return None

    script = script_for_projection(active, graph, resolved_context)
    if not script:
        return None

    planning_context = projection_context(data_dir, graph, active, resolved_context, script)
    projected = build_projected_input_context(target_node_key, script, planning_context)
    if not first_text(projected.get("materialized_prompt")):
        return None
    return retarget_projected_input_context(projected, graph_node.id, target_node_key)


def should_skip_target_projection(
    graph_node: WorkflowGraphNode,
    graph: WorkflowGraph,
    data_dir: Path,
) -> bool:
    director_node_types = {
        "script",
        "character-generation",
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
        "bgm",
        "final-composition",
    }
    if graph_node.node_type in director_node_types and load_director_context(
        data_dir, graph.workflow_id
    ):
        return True
    return bool(
        graph_node.input_context.get("director_context_summary")
        or graph_node.input_context.get("system_suggested_prompt")
    )


def retarget_projected_input_context(
    projected: dict[str, Any],
    target_node_id: str,
    target_node_type: str,
) -> dict[str, Any]:
    retargeted = dict(projected)
    resolved_context = projected.get("resolved_input_context")
    if isinstance(resolved_context, dict):
        resolved_context = dict(resolved_context)
        resolved_context["target_node_id"] = target_node_id
        resolved_context["target_node_type"] = target_node_type
        retargeted["resolved_input_context"] = resolved_context
    source_mappings = projected.get("source_mappings")
    if isinstance(source_mappings, list):
        retargeted["source_mappings"] = [
            {**mapping, "target_node_id": target_node_id}
            for mapping in source_mappings
            if isinstance(mapping, dict)
        ]
    return retargeted


def merge_target_aware_context(
    resolved_context: dict[str, Any],
    target_aware_context: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(resolved_context)
    projected_context = target_aware_context.get("resolved_input_context")
    if isinstance(projected_context, dict):
        merge_non_empty(merged, projected_context)
    return merged


def node_system_prompt(
    graph_node: WorkflowGraphNode,
    graph: WorkflowGraph,
    data_dir: Path,
) -> str | None:
    for key in ("system_suggested_prompt", "materialized_prompt"):
        value = graph_node.input_context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if graph_node.prompt:
        return graph_node.prompt
    director_context = load_director_context(data_dir, graph.workflow_id)
    if director_context is None:
        return None
    field_by_node = {
        "script": "script",
        "character-generation": "character_generation",
        "scene-generation": "scene_generation",
        "storyboard": "storyboard",
        "storyboard-video-generation": "storyboard_video_generation",
        "bgm": "bgm",
        "final-composition": "final_composition",
    }
    field_name = field_by_node.get(graph_node.node_type)
    if not field_name:
        return None
    value = getattr(director_context.node_briefs, field_name)
    return value if value else None


def append_script_refresh_to_system_prompt(
    materialized_prompt: str | None,
    script: Any,
) -> str | None:
    if not materialized_prompt:
        return materialized_prompt
    summary = script_refresh_summary(script)
    if not summary or summary in materialized_prompt:
        return materialized_prompt
    return f"{materialized_prompt}\n\nLatest script context:\n{summary}"


def append_storyboard_bgm_context_to_system_prompt(
    materialized_prompt: str | None,
    storyboard: Any,
) -> str | None:
    if not materialized_prompt:
        return materialized_prompt
    summary = storyboard_bgm_summary(storyboard)
    if not summary or summary in materialized_prompt:
        return materialized_prompt
    return f"{materialized_prompt}\n\nStoryboard music context:\n{summary}"


def storyboard_bgm_summary(storyboard: Any) -> str | None:
    if not isinstance(storyboard, dict):
        return None
    lines: list[str] = []
    for key, label in (
        ("rhythm_summary", "Rhythm"),
        ("mood", "Mood"),
        ("pacing", "Pacing"),
        ("music_notes", "Music notes"),
    ):
        fragments = prompt_fragments(storyboard.get(key))
        if fragments:
            lines.append(f"- {label}: {' '.join(fragments)}")
    scene_lines = _storyboard_scene_music_lines(storyboard.get("scenes"))
    if scene_lines:
        lines.append("- Shot cues:")
        lines.extend(scene_lines)
    return "\n".join(lines) if lines else None


def _storyboard_scene_music_lines(scenes: Any) -> list[str]:
    if not isinstance(scenes, list):
        return []
    lines: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        fragments: list[str] = []
        for key in ("text", "camera", "action", "duration_seconds"):
            fragments.extend(prompt_fragments(scene.get(key)))
        if fragments:
            lines.append(f"  - Shot {scene.get('order') or index}: {'; '.join(fragments)}")
    return lines[:8]


def script_refresh_summary(script: Any) -> str | None:
    if not isinstance(script, dict):
        return None
    lines: list[str] = []
    for key, label in (("hook", "Hook"), ("body", "Body"), ("cta", "CTA")):
        value = script.get(key)
        if value in (None, "", [], {}):
            continue
        fragments = prompt_fragments(value)
        if fragments:
            lines.append(f"- {label}: {' '.join(fragments)}")
    return "\n".join(lines) if lines else None


def script_for_projection(
    active: dict[str, dict[str, Any]],
    graph: WorkflowGraph,
    resolved_context: dict[str, Any],
) -> dict[str, Any]:
    active_script = output(active, "script")
    if active_script:
        return active_script
    context_script = resolved_context.get("script")
    if isinstance(context_script, dict) and context_script:
        return context_script
    graph_script = graph_node_output(graph, "script")
    return graph_script if graph_script else {}


def projection_context(
    data_dir: Path,
    graph: WorkflowGraph,
    active: dict[str, dict[str, Any]],
    resolved_context: dict[str, Any],
    script: dict[str, Any],
) -> dict[str, Any]:
    context = load_planning_context(data_dir, graph.workflow_id)
    merge_non_empty(context, projection_context_from_resolved_inputs(resolved_context))
    if graph.ad_request:
        context["ad_request"] = graph.ad_request
    context["script"] = script
    merge_non_empty(
        context,
        {
            "requirements_analysis": output(active, "requirements-analysis"),
            "product_design": output(active, "product-design"),
            "creative_direction": output(active, "creative-direction"),
        },
    )
    requirements = context.get("requirements")
    if "requirements_analysis" not in context and isinstance(requirements, dict):
        context["requirements_analysis"] = requirements
    if "requirements" not in context and isinstance(context.get("requirements_analysis"), dict):
        context["requirements"] = context["requirements_analysis"]
    return context


def projection_context_from_resolved_inputs(resolved_context: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in (
        "ad_request",
        "requirements",
        "requirements_analysis",
        "product_design",
        "creative_direction",
    ):
        value = resolved_context.get(key)
        if value not in (None, "", {}, []):
            context[key] = value
    return context


def load_planning_context(data_dir: Path, workflow_id: str) -> dict[str, Any]:
    path = planning_context_path(data_dir, workflow_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def graph_node_output(graph: WorkflowGraph, node_id: str) -> dict[str, Any]:
    for node in graph.nodes:
        if node.id == node_id and isinstance(node.output, dict):
            return node.output
    return {}


def target_aware_assets(
    target_aware_context: dict[str, Any],
    *generic_asset_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    value = target_aware_context.get("materialized_assets")
    target_assets = (
        [asset for asset in value if isinstance(asset, dict)] if isinstance(value, list) else []
    )
    merged = with_public_urls(target_assets)
    for assets in generic_asset_groups:
        merged = merge_assets(merged, assets)
    return merged


def target_aware_source_mappings(
    target_aware_context: dict[str, Any],
    target_node_id: str,
    generic_source_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    value = target_aware_context.get("source_mappings")
    mappings = (
        [
            {**mapping, "target_node_id": target_node_id}
            for mapping in value
            if isinstance(mapping, dict)
        ]
        if isinstance(value, list)
        else []
    )
    seen_edges: set[tuple[str, str, str, str, str]] = set()
    for mapping in generic_source_mappings:
        if not isinstance(mapping, dict):
            continue
        normalized = dict(mapping)
        normalized["target_node_id"] = target_node_id
        edge_key = (
            str(normalized.get("source_node_id") or ""),
            str(normalized.get("target_node_id") or ""),
            str(normalized.get("edge_id") or ""),
            str(normalized.get("from") or ""),
            str(normalized.get("to") or ""),
        )
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        mappings.append(normalized)
    return mappings
