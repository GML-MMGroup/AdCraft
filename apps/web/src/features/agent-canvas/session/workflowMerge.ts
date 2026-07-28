import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function newerNode(left: CanvasNodeV2, right: CanvasNodeV2): CanvasNodeV2 {
  if (right.revision !== left.revision) {
    return right.revision > left.revision ? right : left;
  }
  return timestamp(right.updated_at) > timestamp(left.updated_at) ? right : left;
}

export function mergeAgentCanvasNode(
  current: CanvasNodeV2,
  incoming: CanvasNodeV2,
): CanvasNodeV2 {
  if (
    current.workflow_id !== incoming.workflow_id
    || current.node_id !== incoming.node_id
  ) {
    return current;
  }
  return {
    ...newerNode(current, incoming),
    position: current.position,
  };
}

export function mergeAgentCanvasWorkflow(
  current: AgentCanvasWorkflowV2 | null,
  incoming: AgentCanvasWorkflowV2,
): AgentCanvasWorkflowV2 {
  if (!current) return incoming;
  if (current.workflow_id !== incoming.workflow_id) return current;
  if (incoming.revision > current.revision) return incoming;
  if (incoming.revision < current.revision) return current;

  const currentNodes = new Map(current.nodes.map((node) => [node.node_id, node]));
  const incomingNodeIds = new Set(incoming.nodes.map((node) => node.node_id));
  const nodes = incoming.nodes.map((node) => {
    const existing = currentNodes.get(node.node_id);
    return existing ? mergeAgentCanvasNode(existing, node) : node;
  });
  current.nodes.forEach((node) => {
    if (!incomingNodeIds.has(node.node_id)) nodes.push(node);
  });

  const incomingBindingIds = new Set(incoming.bindings.map((binding) => binding.binding_id));
  const bindings = [
    ...incoming.bindings,
    ...current.bindings.filter((binding) => !incomingBindingIds.has(binding.binding_id)),
  ];

  const currentAssetIds = new Set(current.assets.map((asset) => asset.asset_id));
  const assets = [
    ...current.assets,
    ...incoming.assets.filter((asset) => !currentAssetIds.has(asset.asset_id)),
  ];

  return {
    ...incoming,
    nodes,
    bindings,
    assets,
  };
}
