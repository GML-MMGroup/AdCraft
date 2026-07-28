import { MarkerType, type Edge } from "@xyflow/react";

import type {
  AgentCanvasWorkflowV2,
  CanvasBindingKindV2,
  CanvasBindingV2,
  CanvasNodeV2,
  CanvasPositionV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";
import type {
  AgentCanvasFlowNode,
  AgentCanvasNodeCallbacks,
} from "./AgentCanvasNode.tsx";

export function bindingKindForSourceNode(node: CanvasNodeV2): CanvasBindingKindV2 {
  if (node.node_type === "text") return "brief_context";
  if (node.node_type === "script") return "script_context";
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
  return bindings.flatMap((binding) => binding.source.kind === "node"
    ? [{
        id: binding.binding_id,
        source: binding.source.node_id,
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
