import { MarkerType, type Edge } from "@xyflow/react";

import type {
  AgentPlacementHintV2,
  AgentCanvasWorkflowV2,
  CanvasBindingInputRoleV2,
  CanvasBindingV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  CanvasLayoutPositionV2,
  CanvasPositionV2,
  CanvasRuntimeSnapshotV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { isAgentCanvasVisibleNodeType } from "../model/nodeDefaults.ts";
import type {
  AgentCanvasFlowNode,
  AgentCanvasNodeCallbacks,
} from "./AgentCanvasNode.tsx";
import {
  AGENT_CANVAS_NODE_HORIZONTAL_GAP,
  AGENT_CANVAS_NODE_VERTICAL_GAP,
  agentCanvasNodePlacementSize,
  agentCanvasFocusedNodeSize,
  agentCanvasNodeSize,
  validAgentCanvasMediaDimensions,
  type AgentCanvasMediaDimensions,
  type AgentCanvasNodeSize,
} from "./nodeGeometry.ts";

type PlacementNode = Pick<CanvasNodeV2, "node_type" | "output_asset_id" | "position">;

interface PositionedCanvasNode {
  position: CanvasPositionV2;
  size: AgentCanvasNodeSize;
}

export interface FindAvailableCanvasPositionOptions {
  assets?: ProjectAssetSummaryV2[];
  candidateNodeType?: CanvasNodeTypeV2;
  candidateDimensions?: AgentCanvasMediaDimensions | null;
}

export function inputRoleForSourceNode(node: CanvasNodeV2): CanvasBindingInputRoleV2 {
  if (node.node_type === "text" || node.node_type === "script") return "text_context";
  if (node.node_type === "image") return "image_reference";
  if (node.node_type === "audio") return "audio_reference";
  return "video_reference";
}

export function findAvailableCanvasPosition(
  nodes: PlacementNode[],
  preferred: CanvasPositionV2,
  options: FindAvailableCanvasPositionOptions = {},
): CanvasPositionV2 {
  const assetsById = new Map((options.assets ?? []).map((asset) => [asset.asset_id, asset]));
  const occupied = nodes
    .filter((node) => isAgentCanvasVisibleNodeType(node.node_type))
    .map((node) => ({
      position: node.position,
      size: sizeForPlacementNode(node, assetsById),
    }));
  const candidateSize = agentCanvasNodePlacementSize(
    options.candidateNodeType ?? "text",
    options.candidateDimensions,
  );
  return findPositionForRects(occupied, preferred, candidateSize);
}

export function incrementalPlacementForNodes(
  nodes: CanvasNodeV2[],
  affectedNodeIds: string[],
  placementHints: AgentPlacementHintV2[],
  viewportAnchor: CanvasPositionV2,
  assets: ProjectAssetSummaryV2[] = [],
): CanvasLayoutPositionV2[] {
  const affected = new Set(affectedNodeIds);
  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  const assetsById = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const occupied = nodes
    .filter((node) => (
      !affected.has(node.node_id)
      && isAgentCanvasVisibleNodeType(node.node_type)
    ))
    .map((node) => ({
      position: node.position,
      size: sizeForPlacementNode(node, assetsById),
    }));
  const placed: CanvasLayoutPositionV2[] = [];
  const placedRects: PositionedCanvasNode[] = [];

  affectedNodeIds.forEach((nodeId, index) => {
    const node = nodesById.get(nodeId);
    if (!node || !isAgentCanvasVisibleNodeType(node.node_type)) return;
    const hint = placementHints[index] ?? {
      intent: "append_flow",
      anchor_node_id: null,
      group_key: null,
    };
    const anchor = hint.anchor_node_id ? nodesById.get(hint.anchor_node_id) : null;
    const anchorSize = anchor ? sizeForPlacementNode(anchor, assetsById) : null;
    const candidateSize = sizeForPlacementNode(node, assetsById);
    const fallbackX = occupied.length
      ? Math.max(...occupied.map((item) => item.position.x + item.size.width))
        + AGENT_CANVAS_NODE_HORIZONTAL_GAP
      : viewportAnchor.x;
    const preferred = hint.intent === "near_selection"
      ? anchor?.position ?? viewportAnchor
      : hint.intent === "right_sibling" || hint.intent === "after_anchor"
        ? {
            x: anchor && anchorSize
              ? anchor.position.x + anchorSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP
              : fallbackX,
            y: anchor?.position.y ?? viewportAnchor.y,
          }
        : {
            x: fallbackX,
            y: anchor?.position.y ?? viewportAnchor.y,
          };
    const position = findPositionForRects(
      [...occupied, ...placedRects],
      preferred,
      candidateSize,
    );
    placed.push({ node_id: node.node_id, ...position });
    placedRects.push({ position, size: candidateSize });
  });

  return placed;
}

export function toAgentCanvasFlowNodes(
  workflow: AgentCanvasWorkflowV2,
  runtime: CanvasRuntimeSnapshotV2 | null,
  callbacks: AgentCanvasNodeCallbacks,
  focusedNodeId: string | null = null,
): AgentCanvasFlowNode[] {
  const assets = new Map(workflow.assets.map((asset) => [asset.asset_id, asset]));
  return workflow.nodes.filter((node) => isAgentCanvasVisibleNodeType(node.node_type)).map((node) => {
    const asset = node.output_asset_id ? assets.get(node.output_asset_id) ?? null : null;
    const dimensions = asset ? { width: asset.width, height: asset.height } : null;
    const focused = node.node_id === focusedNodeId;
    const size = focused
      ? agentCanvasFocusedNodeSize(node.node_type, dimensions)
      : agentCanvasNodeSize(node.node_type, dimensions);
    return {
      id: node.node_id,
      type: "agentCanvas" as const,
      position: node.position,
      style: focused || (node.node_type === "image" && validAgentCanvasMediaDimensions(dimensions))
        ? size
        : undefined,
      data: {
        node,
        asset,
        runtime: runtime?.node_runtime[node.node_id] ?? null,
        focused,
        ...callbacks,
      },
    };
  });
}

function sizeForPlacementNode(
  node: Pick<CanvasNodeV2, "node_type" | "output_asset_id">,
  assetsById: Map<string, ProjectAssetSummaryV2>,
): AgentCanvasNodeSize {
  const asset = node.output_asset_id ? assetsById.get(node.output_asset_id) : null;
  return agentCanvasNodePlacementSize(
    node.node_type,
    asset ? { width: asset.width, height: asset.height } : null,
  );
}

function findPositionForRects(
  occupied: PositionedCanvasNode[],
  preferred: CanvasPositionV2,
  candidateSize: AgentCanvasNodeSize,
): CanvasPositionV2 {
  if (!occupied.length) return preferred;

  const xCandidates = uniqueCoordinates([
    preferred.x,
    ...occupied.flatMap((item) => [
      item.position.x + item.size.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      item.position.x - candidateSize.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP,
    ]),
  ]);
  const yCandidates = uniqueCoordinates([
    preferred.y,
    ...occupied.flatMap((item) => [
      item.position.y + item.size.height + AGENT_CANVAS_NODE_VERTICAL_GAP,
      item.position.y - candidateSize.height - AGENT_CANVAS_NODE_VERTICAL_GAP,
    ]),
  ]);
  const candidates = yCandidates.flatMap((y) => xCandidates.map((x) => ({ x, y })));
  candidates.sort((left, right) => {
    const rowPriority = Number(left.y !== preferred.y) - Number(right.y !== preferred.y);
    return rowPriority || distanceFrom(left, preferred) - distanceFrom(right, preferred);
  });

  return candidates.find((candidate) => !occupied.some((item) => (
    rectanglesOverlap(candidate, candidateSize, item)
  ))) ?? {
    x: Math.max(...occupied.map((item) => item.position.x + item.size.width))
      + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
    y: preferred.y,
  };
}

function rectanglesOverlap(
  position: CanvasPositionV2,
  size: AgentCanvasNodeSize,
  occupied: PositionedCanvasNode,
): boolean {
  return position.x < occupied.position.x + occupied.size.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP
    && position.x + size.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP > occupied.position.x
    && position.y < occupied.position.y + occupied.size.height + AGENT_CANVAS_NODE_VERTICAL_GAP
    && position.y + size.height + AGENT_CANVAS_NODE_VERTICAL_GAP > occupied.position.y;
}

function uniqueCoordinates(values: number[]): number[] {
  return [...new Set(values)];
}

function distanceFrom(position: CanvasPositionV2, origin: CanvasPositionV2): number {
  return Math.abs(position.x - origin.x) + Math.abs(position.y - origin.y);
}

export function toAgentCanvasFlowEdges(
  bindings: CanvasBindingV2[],
  nodes: CanvasNodeV2[],
): Edge[] {
  const visibleNodeIds = new Set(
    nodes
      .filter((node) => isAgentCanvasVisibleNodeType(node.node_type))
      .map((node) => node.node_id),
  );
  return bindings.flatMap((binding) => binding.enabled && binding.source.kind === "node_output"
    && visibleNodeIds.has(binding.source.source_node_id)
    && visibleNodeIds.has(binding.target_node_id)
    ? [{
        id: binding.binding_id,
        source: binding.source.source_node_id,
        target: binding.target_node_id,
        sourceHandle: "output",
        targetHandle: "input",
        type: "default",
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        data: { binding },
        style: {
          stroke: "rgba(109, 94, 170, 0.72)",
          strokeWidth: 1.6,
        },
      }]
    : []);
}
