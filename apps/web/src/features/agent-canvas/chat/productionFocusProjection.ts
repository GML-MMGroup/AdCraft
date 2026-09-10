import type {
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
  GuidanceAwaitingV1,
  NodeRuntimeV2,
} from "../../../types-v2.ts";

export type ProductionFocusKind = "guidance" | "failed" | "running" | "waiting";

export interface ProductionFocusProjection {
  kind: ProductionFocusKind;
  title: string;
  detail: string;
  actionLabel: "View node" | "View blocker" | "View on canvas" | null;
  nodeIds: string[];
}

export interface ProductionFocusProjectionInput {
  nodes: CanvasNodeV2[];
  runtime: CanvasRuntimeSnapshotV2 | null;
  guidanceAwaiting: GuidanceAwaitingV1 | null;
}

function nodeName(node: CanvasNodeV2 | undefined, fallback = "This node"): string {
  return node?.title?.trim() || fallback;
}

function guidanceProjection(
  awaiting: GuidanceAwaitingV1,
  nodesById: Map<string, CanvasNodeV2>,
): ProductionFocusProjection {
  if (awaiting.kind === "manual_node_run" && awaiting.node_ids.length) {
    const names = awaiting.node_ids.map((nodeId) => nodeName(nodesById.get(nodeId)));
    return {
      kind: "guidance",
      title: names.length === 1 ? `${names[0]} is ready to run` : `${names.length} nodes are ready to run`,
      detail: names.length === 1 ? "Run this node to continue" : "Run these nodes to continue",
      actionLabel: awaiting.node_ids.length === 1 ? "View node" : "View on canvas",
      nodeIds: awaiting.node_ids,
    };
  }
  const copy: Record<GuidanceAwaitingV1["kind"], [string, string]> = {
    clarification: ["Your input is needed", "Answer the current question to continue"],
    concept_selection: ["Your creative choice is needed", "Choose an option to continue"],
    product_source: ["A product source is needed", "Add or choose a product source to continue"],
    media_review: ["Your media review is needed", "Review the generated media to continue"],
    reference_source: ["A reference source is needed", "Choose a reference image or skip to continue"],
    manual_node_run: ["A node is ready to run", "Run the node to continue"],
    milestone_idle: ["This production milestone is complete", "Continue when you are ready"],
  };
  return {
    kind: "guidance",
    title: copy[awaiting.kind][0],
    detail: copy[awaiting.kind][1],
    actionLabel: awaiting.node_ids.length === 1 ? "View node" : awaiting.node_ids.length > 1 ? "View on canvas" : null,
    nodeIds: awaiting.node_ids,
  };
}

function runtimeStates(runtime: CanvasRuntimeSnapshotV2 | null): NodeRuntimeV2[] {
  return runtime ? Object.values(runtime.node_runtime) : [];
}

function aggregateNodeTitle(states: NodeRuntimeV2[], nodesById: Map<string, CanvasNodeV2>, suffix: string): string {
  if (states.length === 1) return `${nodeName(nodesById.get(states[0]!.node_id))} ${suffix}`;
  const nodeTypes = new Set(states.map((state) => nodesById.get(state.node_id)?.node_type).filter(Boolean));
  const subject = nodeTypes.size === 1 ? `${[...nodeTypes][0]} nodes` : "nodes";
  return `${states.length} ${subject} ${suffix}`;
}

function runningDetail(states: NodeRuntimeV2[]): string {
  if (states.length !== 1) return "Generation is in progress";
  switch (states[0]!.phase) {
    case "waiting_provider": return "Generation is still processing";
    case "recovering": return "Retrying generation";
    case "publishing": return "Saving generated result";
    case "queued": return "Waiting to start";
    default: return "Generation is in progress";
  }
}

export function projectProductionFocus({
  nodes,
  runtime,
  guidanceAwaiting,
}: ProductionFocusProjectionInput): ProductionFocusProjection | null {
  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  if (guidanceAwaiting?.requires_user_action) {
    return guidanceProjection(guidanceAwaiting, nodesById);
  }

  const states = runtimeStates(runtime);
  const failed = states.filter((state) => state.visible_status === "failed" || state.error !== null);
  if (failed.length) {
    return {
      kind: "failed",
      title: aggregateNodeTitle(failed, nodesById, failed.length === 1 ? "needs attention" : "need attention"),
      detail: "Generation failed",
      actionLabel: failed.length === 1 ? "View node" : "View on canvas",
      nodeIds: failed.map((state) => state.node_id),
    };
  }

  const activePhases = new Set<NodeRuntimeV2["phase"]>([
    "queued",
    "running",
    "waiting_provider",
    "recovering",
    "publishing",
  ]);
  const running = states.filter((state) => (
    activePhases.has(state.phase)
    || (state.visible_status === "working"
      && state.phase !== "waiting_for_input"
      && state.phase !== "blocked_by_upstream")
  ));
  if (running.length) {
    return {
      kind: "running",
      title: aggregateNodeTitle(running, nodesById, running.length === 1 ? "is generating" : "are generating"),
      detail: runningDetail(running),
      actionLabel: running.length === 1 ? "View node" : "View on canvas",
      nodeIds: running.map((state) => state.node_id),
    };
  }

  const waiting = states.filter((state) => (
    state.phase === "waiting_for_input" || state.phase === "blocked_by_upstream"
  ));
  if (!waiting.length) return null;
  const primary = waiting[0]!;
  const blockerIds = [...new Set([
    ...primary.blocked_by_node_ids,
    ...primary.waiting_for_node_ids,
  ])];
  const blockerNames = blockerIds.map((nodeId) => nodeName(nodesById.get(nodeId), "an upstream node"));
  return {
    kind: "waiting",
    title: aggregateNodeTitle(waiting, nodesById, waiting.length === 1 ? "is waiting" : "are waiting"),
    detail: blockerNames.length ? `Waiting for ${blockerNames.join(", ")}` : "This step is waiting",
    actionLabel: blockerIds.length ? "View blocker" : waiting.length === 1 ? "View node" : "View on canvas",
    nodeIds: blockerIds.length ? blockerIds : waiting.map((state) => state.node_id),
  };
}
