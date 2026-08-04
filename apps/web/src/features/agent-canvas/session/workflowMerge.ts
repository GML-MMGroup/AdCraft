import type {
  AgentCanvasWorkflowV2,
  CanvasBindingMutationResponseV2,
  CanvasConnectedNodeCreateResponseV2,
  CanvasLayoutPatchResponseV2,
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

export function mergeAgentCanvasLayout(
  current: AgentCanvasWorkflowV2,
  response: CanvasLayoutPatchResponseV2,
): AgentCanvasWorkflowV2 {
  if (
    current.workflow_id !== response.workflow_id
    || response.layout_revision < current.layout_revision
  ) {
    return current;
  }
  const positions = new Map(
    response.positions.map((position) => [position.node_id, position]),
  );
  return {
    ...current,
    layout_revision: response.layout_revision,
    nodes: current.nodes.map((node) => {
      const position = positions.get(node.node_id);
      return position
        ? { ...node, position: { x: position.x, y: position.y } }
        : node;
    }),
  };
}

export function overlayAgentCanvasPositions(
  current: AgentCanvasWorkflowV2,
  positions: CanvasLayoutPatchResponseV2["positions"],
): AgentCanvasWorkflowV2 {
  if (!positions.length) return current;
  const byNodeId = new Map(positions.map((position) => [position.node_id, position]));
  return {
    ...current,
    nodes: current.nodes.map((node) => {
      const position = byNodeId.get(node.node_id);
      return position
        ? { ...node, position: { x: position.x, y: position.y } }
        : node;
    }),
  };
}

export function mergeAgentCanvasConnectedNode(
  current: AgentCanvasWorkflowV2,
  response: CanvasConnectedNodeCreateResponseV2,
): AgentCanvasWorkflowV2 {
  if (current.workflow_id !== response.workflow_id) return current;
  return {
    ...current,
    revision: Math.max(current.revision, response.revision),
    layout_revision: Math.max(current.layout_revision, response.layout_revision),
    nodes: [
      ...current.nodes.filter((node) => node.node_id !== response.node.node_id),
      response.node,
    ],
    bindings: [
      ...current.bindings.filter((binding) => binding.binding_id !== response.binding.binding_id),
      response.binding,
    ],
  };
}

export function mergeAgentCanvasBindingMutation(
  current: AgentCanvasWorkflowV2,
  response: CanvasBindingMutationResponseV2,
): AgentCanvasWorkflowV2 {
  if (current.workflow_id !== response.workflow_id) return current;
  const targetNodeId = response.binding.target_node_id;
  return {
    ...current,
    revision: Math.max(current.revision, response.revision),
    bindings: [
      ...current.bindings.filter((binding) => binding.target_node_id !== targetNodeId),
      ...response.incoming_bindings,
    ],
  };
}

export function mergeAgentCanvasWorkflow(
  current: AgentCanvasWorkflowV2 | null,
  incoming: AgentCanvasWorkflowV2,
): AgentCanvasWorkflowV2 {
  if (!current) return incoming;
  if (current.workflow_id !== incoming.workflow_id) return current;
  const currentNodes = new Map(current.nodes.map((node) => [node.node_id, node]));
  const incomingNodes = new Map(incoming.nodes.map((node) => [node.node_id, node]));
  const semanticSource = incoming.revision > current.revision
    ? incoming
    : incoming.revision < current.revision
      ? current
      : incoming;
  const semanticNodes = semanticSource.nodes.map((node) => {
    if (incoming.revision !== current.revision) return node;
    const existing = currentNodes.get(node.node_id);
    return existing ? newerNode(existing, node) : node;
  });
  const useIncomingLayout = incoming.layout_revision > current.layout_revision;
  const positionSource = useIncomingLayout ? incomingNodes : currentNodes;
  const nodes = semanticNodes.map((node) => ({
    ...node,
    position: positionSource.get(node.node_id)?.position ?? node.position,
  }));

  const currentAssetIds = new Set(current.assets.map((asset) => asset.asset_id));
  const assets = [
    ...(semanticSource === incoming ? incoming.assets : current.assets),
    ...(semanticSource === incoming
      ? current.assets.filter((asset) => !incoming.assets.some((item) => item.asset_id === asset.asset_id))
      : incoming.assets.filter((asset) => !currentAssetIds.has(asset.asset_id))),
  ];

  return {
    ...semanticSource,
    revision: Math.max(current.revision, incoming.revision),
    layout_revision: Math.max(current.layout_revision, incoming.layout_revision),
    nodes,
    bindings: semanticSource.bindings,
    assets,
  };
}
