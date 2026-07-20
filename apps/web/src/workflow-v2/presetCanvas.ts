import type { WorkflowDisplayEdgeV2, WorkflowNodeV2 } from "../types-v2.ts";

const PRESET_ORDER = ["script", "character-generation", "scene-generation", "product-generation", "bgm", "storyboard", "final-composition"];
const COLUMN_BY_NODE = new Map([
  ["script", 1],
  ["product-generation", 2],
  ["character-generation", 2],
  ["scene-generation", 2],
  ["bgm", 2],
  ["storyboard", 3],
  ["final-composition", 4],
]);

export interface V2LayoutNode extends WorkflowNodeV2 {
  column: number;
  row: number;
}

export function layoutV2PresetNodes(nodes: WorkflowNodeV2[]): V2LayoutNode[] {
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  return PRESET_ORDER
    .map((nodeId, index) => {
      const node = byId.get(nodeId);
      if (!node) return null;
      return {
        ...node,
        column: COLUMN_BY_NODE.get(node.node_id) ?? 1,
        row: node.node_id === "script" ? 1 : node.node_id === "storyboard" ? 1 : node.node_id === "final-composition" ? 1 : index,
      };
    })
    .filter((node): node is V2LayoutNode => Boolean(node));
}

export function defaultV2DisplayEdges(): WorkflowDisplayEdgeV2[] {
  return [
    ["script", "product-generation"],
    ["script", "character-generation"],
    ["script", "scene-generation"],
    ["script", "bgm"],
    ["product-generation", "storyboard"],
    ["character-generation", "storyboard"],
    ["scene-generation", "storyboard"],
    ["storyboard", "final-composition"],
    ["bgm", "final-composition"],
  ].map(([source, target]) => ({
    id: `${source}-${target}`,
    source,
    target,
    edge_kind: "display_flow",
  }));
}

export function visibleV2DisplayEdges(edges: WorkflowDisplayEdgeV2[]) {
  return edges.filter((edge) => edge.edge_kind === "display_flow");
}

export function v2EmptyShellMessage(node: WorkflowNodeV2) {
  if (node.not_ready_reason === "requires_visual_reference_bundles") return "Waiting for product, character, and scene visual assets";
  if (node.not_ready_reason === "requires_storyboard_video_segments_and_bgm") return "Waiting for storyboard video segments and BGM";
  return node.not_ready_reason ?? "";
}
