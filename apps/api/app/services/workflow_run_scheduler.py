from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.schemas.workflow_nodes import WorkflowRunRequest
from app.services.workflow_graph import selected_graph_node_ids
from app.services.workflow_asset_contract import legacy_output_assets_from_payload
from app.services.workflow_node_errors import WorkflowNodeInputError
from app.services.workflow_run_inputs import graph_node_as_active_result
from app.services.workflow_run_plan_adapter import can_reuse_active_result


@dataclass(frozen=True)
class ParallelNodeOutcome:
    node_id: str
    node_type: str
    result: dict[str, Any] | None = None
    error: str | None = None


def required_upstreams_by_node(graph: WorkflowGraph) -> dict[str, list[str]]:
    upstreams = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.required:
            upstreams.setdefault(edge.target_node_id, []).append(edge.source_node_id)
    return upstreams


def required_downstream_by_node(graph: WorkflowGraph) -> dict[str, list[str]]:
    downstream = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.required:
            downstream.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    return downstream


def next_ready_node_id(
    ordered_node_ids: list[str],
    *,
    selected: set[str],
    completed: set[str],
    failed: set[str],
    waiting: set[str],
    skipped: set[str],
    blocked: set[str],
    running: set[str],
    required_upstreams: dict[str, list[str]],
    skipped_reasons: dict[str, str],
    active: dict[str, dict[str, Any]],
    graph_nodes: dict[str, WorkflowGraphNode],
    data_dir: Any,
) -> str | None:
    for node_id in ordered_node_ids:
        if node_id not in selected:
            continue
        if node_id in completed | failed | waiting | skipped | blocked | running:
            continue
        if upstreams_satisfied(
            node_id,
            selected=selected,
            completed=completed,
            skipped=skipped,
            skipped_reasons=skipped_reasons,
            required_upstreams=required_upstreams,
            active=active,
            graph_nodes=graph_nodes,
            data_dir=data_dir,
        ):
            return node_id
    return None


def upstreams_satisfied(
    node_id: str,
    *,
    selected: set[str],
    completed: set[str],
    skipped: set[str],
    skipped_reasons: dict[str, str],
    required_upstreams: dict[str, list[str]],
    active: dict[str, dict[str, Any]],
    graph_nodes: dict[str, WorkflowGraphNode],
    data_dir: Any,
) -> bool:
    for upstream_node_id in required_upstreams.get(node_id, []):
        if upstream_node_id not in selected:
            if not node_has_reusable_output(
                upstream_node_id,
                active=active,
                graph_nodes=graph_nodes,
                data_dir=data_dir,
            ):
                return False
            continue
        if upstream_node_id in completed:
            continue
        if upstream_node_id in skipped and skipped_node_satisfies_dependency(
            upstream_node_id,
            skipped_reasons=skipped_reasons,
            active=active,
            graph_nodes=graph_nodes,
            data_dir=data_dir,
        ):
            continue
        return False
    return True


def unsatisfied_upstream_node_ids(
    node_id: str,
    *,
    selected: set[str],
    completed: set[str],
    failed: set[str],
    waiting: set[str],
    skipped: set[str],
    skipped_reasons: dict[str, str],
    required_upstreams: dict[str, list[str]],
    active: dict[str, dict[str, Any]],
    graph_nodes: dict[str, WorkflowGraphNode],
    data_dir: Any,
) -> list[str]:
    unsatisfied: list[str] = []
    for upstream_node_id in required_upstreams.get(node_id, []):
        if upstream_node_id not in selected:
            if not node_has_reusable_output(
                upstream_node_id,
                active=active,
                graph_nodes=graph_nodes,
                data_dir=data_dir,
            ):
                unsatisfied.append(upstream_node_id)
            continue
        if upstream_node_id in completed:
            continue
        if upstream_node_id in skipped and skipped_node_satisfies_dependency(
            upstream_node_id,
            skipped_reasons=skipped_reasons,
            active=active,
            graph_nodes=graph_nodes,
            data_dir=data_dir,
        ):
            continue
        if upstream_node_id in failed | waiting | skipped:
            unsatisfied.append(upstream_node_id)
    return unsatisfied


def skipped_node_satisfies_dependency(
    node_id: str,
    *,
    skipped_reasons: dict[str, str],
    active: dict[str, dict[str, Any]],
    graph_nodes: dict[str, WorkflowGraphNode],
    data_dir: Any,
) -> bool:
    if skipped_reasons.get(node_id) not in {
        "locked",
        "reused_active_output",
        "reused_graph_output",
    }:
        return False
    return node_has_reusable_output(
        node_id,
        active=active,
        graph_nodes=graph_nodes,
        data_dir=data_dir,
    )


def node_has_reusable_output(
    node_id: str,
    *,
    active: dict[str, dict[str, Any]],
    graph_nodes: dict[str, WorkflowGraphNode],
    data_dir: Any,
) -> bool:
    active_result = active.get(node_id)
    if active_result and can_reuse_active_result(active_result, data_dir):
        return True
    graph_node = graph_nodes.get(node_id)
    if graph_node is None:
        return False
    graph_result = graph_node_as_active_result(graph_node)
    return can_reuse_active_result(graph_result, data_dir)


def required_reachable_downstream(
    node_id: str,
    required_downstream: dict[str, list[str]],
) -> list[str]:
    reachable: list[str] = []
    seen: set[str] = set()
    queue = list(required_downstream.get(node_id, []))
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        reachable.append(current)
        queue.extend(required_downstream.get(current, []))
    return reachable


def future_outcome(
    future: Future[ParallelNodeOutcome],
    node_id: str,
    node_type: str,
) -> ParallelNodeOutcome:
    try:
        return future.result()
    except Exception as exc:  # noqa: BLE001 - converted to per-node failure.
        return ParallelNodeOutcome(node_id=node_id, node_type=node_type, error=str(exc))


def failed_graph_result_for_scheduler(
    active_result: dict[str, Any] | None,
    failed_result: dict[str, Any] | None,
    *,
    error: str,
) -> dict[str, Any]:
    if not active_result or not can_reuse_active_result(active_result):
        payload = dict(failed_result or {})
        payload["status"] = "failed"
        payload["error"] = error
        return payload
    payload = dict(active_result)
    payload["status"] = "failed"
    payload["error"] = error
    if failed_result:
        node_run_id = failed_result.get("node_run_id")
        if node_run_id not in (None, ""):
            payload["last_run_id"] = str(node_run_id)
            payload["last_failed_run_id"] = str(node_run_id)
    payload["has_active_output"] = bool(payload.get("output") or payload.get("output_assets"))
    return payload


def select_graph_run_node_ids(
    *,
    graph: WorkflowGraph,
    request: WorkflowRunRequest,
    active: dict[str, dict[str, Any]],
    graph_nodes: dict[str, WorkflowGraphNode],
    ordered_node_ids: list[str],
    mode: str,
) -> tuple[list[str], str, bool]:
    if mode == "single_entity":
        raise WorkflowNodeInputError(
            "single_entity canvas run is not supported yet; run the target node with revision."
        )
    target_node_id = request.target_node_id or request.start_node_id
    if mode == "single_node":
        if not target_node_id:
            raise WorkflowNodeInputError(
                "single_node run requires target_node_id or start_node_id."
            )
        node_ids = selected_graph_node_ids(
            graph,
            start_node_id=target_node_id,
            run_downstream=False,
        )
        return node_ids, target_node_id, False
    if mode == "force_rerun_all":
        frontier = ordered_node_ids[0] if ordered_node_ids else ""
        return ordered_node_ids, frontier, False
    if target_node_id:
        node_ids = selected_graph_node_ids(
            graph,
            start_node_id=target_node_id,
            run_downstream=request.run_downstream,
        )
        return node_ids, target_node_id, False

    frontier = first_dirty_graph_node_id(ordered_node_ids, graph_nodes, active)
    if not frontier:
        return [], "", True
    downstream = set(selected_graph_node_ids(graph, start_node_id=frontier, run_downstream=True))
    execution_set = expand_execution_set_with_dirty_required_siblings(
        graph=graph,
        ordered_node_ids=ordered_node_ids,
        graph_nodes=graph_nodes,
        active=active,
        frontier_node_id=frontier,
        execution_set=downstream,
    )
    node_ids = [node_id for node_id in ordered_node_ids if node_id in execution_set]
    return node_ids, frontier, True


def first_dirty_graph_node_id(
    ordered_node_ids: list[str],
    graph_nodes: dict[str, WorkflowGraphNode],
    active: dict[str, dict[str, Any]],
) -> str:
    for node_id in ordered_node_ids:
        node = graph_nodes[node_id]
        if is_dirty_graph_node(node, active.get(node_id)):
            return node_id
    return ""


def expand_execution_set_with_dirty_required_siblings(
    *,
    graph: WorkflowGraph,
    ordered_node_ids: list[str],
    graph_nodes: dict[str, WorkflowGraphNode],
    active: dict[str, dict[str, Any]],
    frontier_node_id: str,
    execution_set: set[str],
) -> set[str]:
    expanded = set(execution_set)
    try:
        frontier_index = ordered_node_ids.index(frontier_node_id)
    except ValueError:
        frontier_index = 0
    changed = True
    while changed:
        changed = False
        for node_id in ordered_node_ids[frontier_index + 1 :]:
            if node_id in expanded:
                continue
            node = graph_nodes[node_id]
            if not is_dirty_graph_node(node, active.get(node_id)):
                continue
            if node_reaches_any(graph, node_id, expanded):
                expanded.add(node_id)
                changed = True
    return expanded


def node_reaches_any(graph: WorkflowGraph, node_id: str, targets: set[str]) -> bool:
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.required:
            outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    seen: set[str] = set()
    queue = list(outgoing.get(node_id, []))
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        if current in targets:
            return True
        seen.add(current)
        queue.extend(outgoing.get(current, []))
    return False


def is_dirty_graph_node(
    node: WorkflowGraphNode,
    active_result: dict[str, Any] | None,
) -> bool:
    if node.category == "utility":
        return False
    payload = active_result or graph_node_as_active_result(node)
    if node.stale or node.status in {"waiting", "failed", "running", "stale"}:
        return True
    if payload.get("status") in {"failed", "running", "stale", "waiting"}:
        return True
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    output_assets = (
        payload.get("output_assets") if isinstance(payload.get("output_assets"), list) else []
    )
    assets = output_assets_for_clean_check(output, output_assets)
    if payload.get("status") != "completed":
        return True
    if active_result is None and node.status != "completed":
        return True
    if not output and not assets:
        return True
    if node.node_type == "final-composition":
        return not has_final_composition_output(output, assets)
    if node.node_type in {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
        "character-image-generation",
        "scene-image-generation",
        "storyboard-image-generation",
    }:
        return not (has_structured_output(output) or has_active_asset(assets))
    return False


def output_assets_for_clean_check(
    output: dict[str, Any],
    output_assets: list[Any],
) -> list[dict[str, Any]]:
    return legacy_output_assets_from_payload({"output": output, "output_assets": output_assets})


def has_structured_output(output: dict[str, Any]) -> bool:
    structured = output.get("structured_output")
    if isinstance(structured, dict):
        return bool(structured)
    if isinstance(structured, list):
        return bool(structured)
    return False


def has_active_asset(assets: list[dict[str, Any]]) -> bool:
    for asset in assets:
        if asset.get("is_archived") is True:
            continue
        if asset.get("is_active") is False:
            continue
        if asset.get("download_status") == "failed" or asset.get("status") == "failed":
            continue
        if asset.get("asset_id") or asset.get("local_path") or asset.get("uri"):
            return True
    return False


def has_final_composition_output(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
) -> bool:
    structured = output.get("structured_output")
    if isinstance(structured, dict) and structured.get("finalVideoUri"):
        return True
    if output.get("finalVideoUri") or output.get("final_video_uri"):
        return True
    for asset in assets:
        semantic_type = str(asset.get("semantic_type") or asset.get("role") or "")
        asset_type = str(asset.get("asset_type") or asset.get("type") or "")
        if semantic_type == "final_video" or asset.get("asset_id") == "final-ad-video":
            return has_active_asset([asset])
        if asset_type == "video" and asset.get("local_path") and has_active_asset([asset]):
            return True
    return False
