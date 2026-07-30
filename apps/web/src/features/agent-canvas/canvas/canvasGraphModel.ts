import { MarkerType, type Edge } from "@xyflow/react";

import type {
  AgentPlacementHintV2,
  AgentCanvasWorkflowV2,
  CanvasBindingInputRoleV2,
  CanvasBindingV2,
  CanvasNodeV2,
  CanvasLayoutPositionV2,
  CanvasPositionV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";
import type {
  AgentCanvasFlowNode,
  AgentCanvasNodeCallbacks,
} from "./AgentCanvasNode.tsx";

export function inputRoleForSourceNode(node: CanvasNodeV2): CanvasBindingInputRoleV2 {
  if (node.node_type === "text" || node.node_type === "script") return "text_context";
  if (node.node_type === "image") return "image_reference";
  if (node.node_type === "audio") return "audio_reference";
  return "video_reference";
}

export function findAvailableCanvasPosition(
  nodes: Pick<CanvasNodeV2, "position">[],
  preferred: CanvasPositionV2,
): CanvasPositionV2 {
  const horizontalOffsets = [0, 1, -1, 2, -2, 3, -3];
  const verticalOffsets = [0, 1, -1, 2, -2, 3, -3];
  for (const vertical of verticalOffsets) {
    for (const horizontal of horizontalOffsets) {
      const candidate = {
        x: preferred.x + horizontal * 340,
        y: preferred.y + vertical * 260,
      };
      const occupied = nodes.some((node) => (
        Math.abs(node.position.x - candidate.x) < 300
        && Math.abs(node.position.y - candidate.y) < 220
      ));
      if (!occupied) return candidate;
    }
  }
  return {
    x: preferred.x + nodes.length * 36,
    y: preferred.y + nodes.length * 36,
  };
}

export function incrementalPlacementForNodes(
  nodes: CanvasNodeV2[],
  affectedNodeIds: string[],
  placementHints: AgentPlacementHintV2[],
  viewportAnchor: CanvasPositionV2,
): CanvasLayoutPositionV2[] {
  const affected = new Set(affectedNodeIds);
  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  const occupied = nodes.filter((node) => !affected.has(node.node_id));
  const placed: CanvasLayoutPositionV2[] = [];

  affectedNodeIds.forEach((nodeId, index) => {
    const node = nodesById.get(nodeId);
    if (!node) return;
    const hint = placementHints[index] ?? {
      intent: "append_flow",
      anchor_node_id: null,
      group_key: null,
    };
    const anchor = hint.anchor_node_id ? nodesById.get(hint.anchor_node_id) : null;
    const fallbackX = occupied.length
      ? Math.max(...occupied.map((item) => item.position.x)) + 340
      : viewportAnchor.x;
    const preferred = hint.intent === "near_selection"
      ? anchor?.position ?? viewportAnchor
      : hint.intent === "right_sibling" || hint.intent === "after_anchor"
        ? {
            x: (anchor?.position.x ?? fallbackX - 340) + 340,
            y: anchor?.position.y ?? viewportAnchor.y,
          }
        : {
            x: fallbackX,
            y: anchor?.position.y ?? viewportAnchor.y,
          };
    const position = findAvailableCanvasPosition(
      [
        ...occupied,
        ...placed.map((item) => ({ position: { x: item.x, y: item.y } })),
      ],
      preferred,
    );
    placed.push({ node_id: node.node_id, ...position });
  });

  return placed;
}

export function toAgentCanvasFlowNodes(
  workflow: AgentCanvasWorkflowV2,
  runtime: CanvasRuntimeSnapshotV2 | null,
  callbacks: AgentCanvasNodeCallbacks,
): AgentCanvasFlowNode[] {
  const assets = new Map(workflow.assets.map((asset) => [asset.asset_id, asset]));
  return workflow.nodes.map((node) => ({
    id: node.node_id,
    type: "agentCanvas",
    position: node.position,
    data: {
      node,
      asset: node.output_asset_id ? assets.get(node.output_asset_id) ?? null : null,
      runtime: runtime?.node_runtime[node.node_id] ?? null,
      ...callbacks,
    },
  }));
}

export function toAgentCanvasFlowEdges(bindings: CanvasBindingV2[]): Edge[] {
  return bindings.flatMap((binding) => binding.enabled && binding.source.kind === "node_output"
    ? [{
        id: binding.binding_id,
        source: binding.source.source_node_id,
        target: binding.target_node_id,
        sourceHandle: "output",
        targetHandle: "input",
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        data: { binding },
        style: {
          stroke: "rgba(109, 94, 170, 0.72)",
          strokeWidth: 1.6,
        },
      }]
    : []);
}
