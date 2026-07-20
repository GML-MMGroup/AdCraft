from typing import Any

from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.agent_trace import utc_now
from app.services.media_paths import with_public_urls
from app.services.workflow_asset_contract import (
    LEGACY_PROVIDER_OUTPUT_ASSET_CONTAINER_KEYS,
    legacy_output_assets_from_payload,
)
from app.services.workflow_resolved_assets import (
    append_asset,
    asset_upstream_ids,
    normalize_asset,
    selected_assets_for_node,
)

TEXT_FIELD_PRIORITY = (
    "prompt",
    "text",
    "script",
    "summary",
    "description",
    "final_video_prompt",
    "generation_prompt",
    "product",
    "product_name",
    "core_selling_point",
    "target_audience",
    "campaign_goal",
    "desired_emotion",
    "duration_seconds",
    "visual_style",
    "references",
    "hook",
    "body",
    "cta",
    "subtitle_lines",
    "scenes",
)
ASSET_PATH_KEYS = ("local_path", "public_url", "remote_url", "url")
REQUIREMENT_FIELD_LABELS = {
    "product": "产品",
    "product_name": "产品",
    "core_selling_point": "核心卖点",
    "target_audience": "目标受众",
    "campaign_goal": "营销目标",
    "desired_emotion": "期望情绪",
    "duration_seconds": "目标时长",
    "visual_style": "视觉风格",
    "references": "参考信息",
}


def materialized_inputs(
    graph_node: WorkflowGraphNode,
    active: dict[str, dict[str, Any]],
    graph: WorkflowGraph,
) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    prompt_sections: list[tuple[str, list[str]]] = []
    assets: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    source_mappings: list[dict[str, Any]] = []
    incoming_edges = [edge for edge in graph.edges if edge.target_node_id == graph_node.id]
    incoming_source_ids = {edge.source_node_id for edge in incoming_edges}

    for edge in incoming_edges:
        collect_edge_materialized_inputs(
            edge=edge,
            graph_node=graph_node,
            active=active,
            prompt_sections=prompt_sections,
            assets=assets,
            seen_assets=seen_assets,
            source_mappings=source_mappings,
        )
    collect_non_edge_materialized_assets(
        graph_node=graph_node,
        graph=graph,
        active=active,
        incoming_source_ids=incoming_source_ids,
        assets=assets,
        seen_assets=seen_assets,
    )

    materialized_prompt = render_materialized_prompt(prompt_sections) or first_text(
        graph_node.input_context.get("materialized_prompt")
    )
    if not assets:
        assets = stored_materialized_assets(graph_node)
    if not source_mappings:
        source_mappings = stored_source_mappings(graph_node)
    return materialized_prompt, with_public_urls(assets), source_mappings


def collect_edge_materialized_inputs(
    *,
    edge: Any,
    graph_node: WorkflowGraphNode,
    active: dict[str, dict[str, Any]],
    prompt_sections: list[tuple[str, list[str]]],
    assets: list[dict[str, Any]],
    seen_assets: set[str],
    source_mappings: list[dict[str, Any]],
) -> None:
    from app.services.workflow_resolved_context import (
        edge_mapping_or_default,
        extract_upstream_value,
    )

    upstream_payload = active.get(edge.source_node_id)
    if not isinstance(upstream_payload, dict):
        return
    upstream_output = upstream_payload.get("output")
    if not isinstance(upstream_output, dict):
        upstream_output = {}

    source_fragments: list[str] = []
    for item in edge_mapping_or_default(edge):
        if not isinstance(item, dict):
            continue
        from_path = str(item.get("from") or "output")
        to_path = str(item.get("to") or "")
        if not to_path:
            continue
        value = extract_upstream_value(upstream_output, from_path, upstream_payload)
        fragments = prompt_fragments(value)
        mapped_assets = materialized_assets_from_value(value, edge.source_node_id)
        source_fragments.extend(fragments)
        for asset in mapped_assets:
            append_asset(assets, seen_assets, asset)
        source_mappings.append(
            {
                "source_node_id": edge.source_node_id,
                "target_node_id": graph_node.id,
                "edge_id": edge.id,
                "from": from_path,
                "to": to_path,
                "value_type": materialized_value_type(value, fragments, mapped_assets),
                "applied": value is not None,
                "reason": None if value is not None else "mapping source not found",
            }
        )

    source_fragments.extend(prompt_fragments(upstream_output))
    for asset in materialized_assets_from_active_payload(upstream_payload, edge.source_node_id):
        append_asset(assets, seen_assets, asset)

    source_fragments = unique_non_empty_strings(source_fragments)
    if source_fragments:
        prompt_sections.append((edge.source_node_id, source_fragments))


def collect_non_edge_materialized_assets(
    *,
    graph_node: WorkflowGraphNode,
    graph: WorkflowGraph,
    active: dict[str, dict[str, Any]],
    incoming_source_ids: set[str],
    assets: list[dict[str, Any]],
    seen_assets: set[str],
) -> None:
    for asset in selected_assets_for_node(graph_node.node_type, graph):
        append_asset(assets, seen_assets, normalize_asset(asset, "selected_assets"))
    for upstream_id in asset_upstream_ids(graph_node.node_type):
        if upstream_id in incoming_source_ids:
            continue
        upstream_payload = active.get(upstream_id)
        if not isinstance(upstream_payload, dict):
            continue
        for asset in materialized_assets_from_active_payload(upstream_payload, upstream_id):
            append_asset(assets, seen_assets, asset)
    for asset in graph_node.input_assets:
        append_asset(
            assets,
            seen_assets,
            normalize_asset(asset, asset.get("source_node_id") or asset.get("source")),
        )


def stored_materialized_assets(graph_node: WorkflowGraphNode) -> list[dict[str, Any]]:
    value = graph_node.input_context.get("materialized_assets")
    if not isinstance(value, list):
        return []
    return [asset for asset in value if isinstance(asset, dict)]


def stored_source_mappings(graph_node: WorkflowGraphNode) -> list[dict[str, Any]]:
    value = graph_node.input_context.get("source_mappings")
    if not isinstance(value, list):
        return []
    return [mapping for mapping in value if isinstance(mapping, dict)]


def prompt_fragments(value: Any) -> list[str]:
    if value in (None, "", {}, []):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return prompt_fragments_from_list(value)
    if isinstance(value, dict):
        return prompt_fragments_from_dict(value)
    return []


def prompt_fragments_from_list(value: list[Any]) -> list[str]:
    fragments: list[str] = []
    for item in value:
        fragments.extend(prompt_fragments(item))
    return unique_non_empty_strings(fragments)


def prompt_fragments_from_dict(value: dict[str, Any]) -> list[str]:
    fragments = requirements_prompt_fragments(value)
    fragments.extend(text_field_prompt_fragments(value))
    fragments.extend(asset_container_prompt_fragments(value))
    return unique_non_empty_strings(fragments)


def text_field_prompt_fragments(value: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    for field_name in TEXT_FIELD_PRIORITY:
        if field_name not in value:
            continue
        field_value = value.get(field_name)
        if field_name == "scenes":
            fragments.extend(scene_prompt_fragments(field_value))
        else:
            fragments.extend(prompt_fragments(field_value))
    return fragments


def asset_container_prompt_fragments(value: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    for field_name in LEGACY_PROVIDER_OUTPUT_ASSET_CONTAINER_KEYS:
        if field_name in value:
            fragments.extend(prompt_fragments(value.get(field_name)))
    return fragments


def scene_prompt_fragments(value: Any) -> list[str]:
    if not isinstance(value, list):
        return prompt_fragments(value)
    fragments: list[str] = []
    for scene in value:
        if isinstance(scene, dict):
            for field_name in ("prompt", "shot", "visual", "text", "camera", "action"):
                fragments.extend(prompt_fragments(scene.get(field_name)))
        else:
            fragments.extend(prompt_fragments(scene))
    return unique_non_empty_strings(fragments)


def requirements_prompt_fragments(value: dict[str, Any]) -> list[str]:
    if not ({*REQUIREMENT_FIELD_LABELS} & set(value)):
        return []
    fragments = []
    for field_name, label in REQUIREMENT_FIELD_LABELS.items():
        field_value = value.get(field_name)
        if field_value in (None, "", [], {}):
            continue
        if isinstance(field_value, list):
            rendered = ", ".join(str(item) for item in field_value if str(item).strip())
        else:
            rendered = str(field_value).strip()
        if rendered:
            fragments.append(f"{label}: {rendered}")
    return fragments


def materialized_assets_from_active_payload(
    active_payload: dict[str, Any], source_node_id: str
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for asset in legacy_output_assets_from_payload(active_payload):
        assets.extend(materialized_assets_from_value(asset, source_node_id))
    return assets


def materialized_assets_from_value(value: Any, source_node_id: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        assets: list[dict[str, Any]] = []
        for item in value:
            assets.extend(materialized_assets_from_value(item, source_node_id))
        return assets
    if not isinstance(value, dict):
        return []

    assets = []
    if looks_like_materialized_asset(value):
        assets.append(normalize_materialized_asset(value, source_node_id))
    for nested_value in value.values():
        if isinstance(nested_value, (dict, list)):
            assets.extend(materialized_assets_from_value(nested_value, source_node_id))
    return assets


def looks_like_materialized_asset(value: dict[str, Any]) -> bool:
    if any(value.get(key) for key in ASSET_PATH_KEYS):
        return True
    return bool(
        value.get("asset_id")
        and (value.get("asset_type") or value.get("type") or value.get("mime_type"))
    )


def normalize_materialized_asset(asset: dict[str, Any], source_node_id: str) -> dict[str, Any]:
    normalized = dict(asset)
    identifier = (
        normalized.get("asset_id")
        or normalized.get("segment_id")
        or normalized.get("id")
        or normalized.get("task_id")
        or normalized.get("local_path")
        or normalized.get("public_url")
        or normalized.get("remote_url")
        or normalized.get("url")
    )
    if identifier:
        normalized["asset_id"] = str(identifier)
    return normalize_asset(normalized, source_node_id)


def materialized_value_type(
    value: Any,
    fragments: list[str],
    assets: list[dict[str, Any]],
) -> str:
    if fragments or isinstance(value, str):
        return "text"
    if assets:
        asset_types = {
            str(asset.get("type") or asset.get("asset_type") or "asset") for asset in assets
        }
        if asset_types == {"image"}:
            return "image"
        if asset_types == {"video"}:
            return "video"
        return "asset"
    if isinstance(value, (dict, list)):
        return "json"
    return "unknown"


def render_materialized_prompt(prompt_sections: list[tuple[str, list[str]]]) -> str | None:
    lines: list[str] = []
    for source_node_id, fragments in prompt_sections:
        clean_fragments = unique_non_empty_strings(fragments)
        if not clean_fragments:
            continue
        if lines:
            lines.append("")
        lines.append(f"Source: {source_node_id}")
        for fragment in clean_fragments:
            fragment_lines = [line.strip() for line in fragment.splitlines() if line.strip()]
            for line in fragment_lines:
                lines.append(f"- {line}")
    return "\n".join(lines) if lines else None


def update_materialized_metadata(
    node: WorkflowGraphNode,
    *,
    materialized_prompt: str | None,
    materialized_assets: list[dict[str, Any]],
    source_mappings: list[dict[str, Any]],
    resolved_input_context: dict[str, Any],
    resolved_input_assets: list[dict[str, Any]],
    resolved_prompt_preview: str,
    resolved_prompt_with_assets: str | None,
    previous_system_prompt: str | None,
) -> None:
    node.metadata = dict(node.metadata or {})
    if materialized_prompt:
        if previous_system_prompt and previous_system_prompt != materialized_prompt:
            node.metadata["previous_system_materialized_prompt"] = previous_system_prompt
        node.metadata["system_materialized_prompt"] = materialized_prompt
        node.metadata["materialized_prompt"] = materialized_prompt
        node.metadata["materialized_prompt_updated_at"] = utc_now().isoformat()
    node.metadata.pop("materialized_assets", None)
    node.metadata["materialized_asset_count"] = len(materialized_assets)
    node.metadata["source_mappings"] = source_mappings
    node.metadata["resolved_input_context"] = resolved_input_context
    node.metadata.pop("resolved_input_assets", None)
    node.metadata["resolved_input_asset_count"] = len(resolved_input_assets)
    node.metadata["resolved_prompt_preview"] = resolved_prompt_preview
    node.metadata["resolved_prompt_with_assets"] = resolved_prompt_with_assets


def should_sync_materialized_prompt(
    node: WorkflowGraphNode,
    previous_system_prompt: str | None,
) -> bool:
    if node.metadata.get("prompt_source") == "user":
        return False
    if node.metadata.get("manual_prompt_dirty") is True:
        return False
    prompt = first_text(node.prompt)
    override_prompt = first_text(node.override_prompt)
    previous = first_text(previous_system_prompt)
    if previous and (
        (prompt and prompt != previous) or (override_prompt and override_prompt != previous)
    ):
        return False
    if node.metadata.get("prompt_source") == "system":
        return True
    if not prompt and not override_prompt:
        return True
    return bool(
        previous
        and (not prompt or prompt == previous)
        and (not override_prompt or override_prompt == previous)
    )


def has_manual_prompt(
    node: WorkflowGraphNode,
    previous_system_prompt: str | None,
    materialized_prompt: str,
) -> bool:
    system_prompts = {
        value
        for value in (first_text(previous_system_prompt), first_text(materialized_prompt))
        if value
    }
    for prompt in (first_text(node.prompt), first_text(node.override_prompt)):
        if prompt and prompt not in system_prompts:
            return True
    return False


def previous_system_materialized_prompt(node: WorkflowGraphNode) -> str | None:
    return first_text(
        node.metadata.get("system_materialized_prompt"),
        node.metadata.get("materialized_prompt"),
        node.input_context.get("materialized_prompt"),
    )


def unique_non_empty_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
