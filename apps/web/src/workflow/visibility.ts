import type { WorkflowEdge, WorkflowNode } from "../types";

export const CANVAS_NODE_ORDER = [
  "script",
  "product-generation",
  "character-generation",
  "scene-generation",
  "storyboard",
  "storyboard-video-generation",
  "bgm",
  "final-composition",
];

export const OPTIONAL_AUDIO_NODE_ID = "bgm";

export const REMOVED_NODE_IDS = new Set([
  "requirements-analysis",
  "product-design",
  "creative-direction",
  "character-design",
  "scene-design",
  "character-image-generation",
  "scene-image-generation",
  "storyboard-image-generation",
]);

export const HIDDEN_WORKFLOW_NODE_TYPES = REMOVED_NODE_IDS;

type NodeLike = Pick<WorkflowNode, "id" | "type" | "node_type">;
type EdgeLike = Pick<WorkflowEdge, "source" | "target"> & {
  source_node_id?: string | null;
  target_node_id?: string | null;
};

export function isHiddenWorkflowNodeType(nodeType?: string | null) {
  return Boolean(nodeType && HIDDEN_WORKFLOW_NODE_TYPES.has(nodeType));
}

export function isUserVisibleWorkflowNode(node: NodeLike) {
  return !isHiddenWorkflowNodeType(node.node_type ?? node.type ?? node.id);
}

export function isUserAddableNodeType(nodeType: string) {
  return !isHiddenWorkflowNodeType(nodeType);
}

export function visibleWorkflowNodes<T extends NodeLike>(nodes: T[]): T[] {
  return nodes.filter(isUserVisibleWorkflowNode);
}

export function visibleWorkflowEdges<T extends EdgeLike>(edges: T[], nodes: NodeLike[]): T[] {
  const visibleNodeIds = new Set(nodes.filter(isUserVisibleWorkflowNode).map((node) => node.id));
  return edges.filter((edge) => {
    const source = edge.source_node_id ?? edge.source;
    const target = edge.target_node_id ?? edge.target;
    return Boolean(source && target && visibleNodeIds.has(source) && visibleNodeIds.has(target));
  });
}

export function firstVisibleWorkflowNodeId(nodes: NodeLike[], fallback = "") {
  return visibleWorkflowNodes(nodes)[0]?.id ?? fallback;
}
