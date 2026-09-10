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
  agentCanvasNodeSize,
  validAgentCanvasMediaDimensions,
  type AgentCanvasMediaDimensions,
  type AgentCanvasNodeSize,
} from "./nodeGeometry.ts";
import {
  sameAgentCanvasAssetPresentation,
  sameAgentCanvasRuntimeCardPresentation,
} from "./agentCanvasNodeRenderModel.ts";
import { AGENT_CANVAS_EDGE_TYPE } from "./canvasConnectionGeometry.ts";

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

export interface ToAgentCanvasFlowNodesOptions {
  previousNodes?: readonly AgentCanvasFlowNode[];
  activeWorkbenchNodeId?: string | null;
}

export function reuseCanvasArray<T>(
  previous: readonly T[] | null | undefined,
  next: T[],
): T[] {
  if (!previous || previous.length !== next.length) return next;
  return next.every((item, index) => item === previous[index]) ? previous as T[] : next;
}

export function reconcileCanvasFlowSnapshot<T>(
  current: readonly T[],
  next: T[],
): T[] {
  if (current.length === next.length && next.every((item, index) => item === current[index])) {
    return current as T[];
  }
  return next;
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

export function needsInitialCanvasLayout(nodes: readonly PlacementNode[]): boolean {
  const visibleNodes = nodes.filter((node) => isAgentCanvasVisibleNodeType(node.node_type));
  if (visibleNodes.length < 2) return false;

  const seenPositions = new Set<string>();
  return visibleNodes.some((node) => {
    const key = `${node.position.x}:${node.position.y}`;
    if (seenPositions.has(key)) return true;
    seenPositions.add(key);
    return false;
  });
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
  options: ToAgentCanvasFlowNodesOptions = {},
): AgentCanvasFlowNode[] {
  const assets = new Map(workflow.assets.map((asset) => [asset.asset_id, asset]));
  const previousNodes = new Map((options.previousNodes ?? []).map((node) => [node.id, node]));
  return workflow.nodes
    .filter((node) => isAgentCanvasVisibleNodeType(node.node_type))
    .map((node) => projectAgentCanvasFlowNode(
      node,
      assets.get(node.output_asset_id ?? "") ?? null,
      runtime?.node_runtime[node.node_id] ?? null,
      callbacks,
      previousNodes.get(node.node_id),
      options,
    ));
}

export function runtimeChangedCanvasNodeIds(
  previousNodes: readonly AgentCanvasFlowNode[],
  nextRuntime: CanvasRuntimeSnapshotV2 | null,
): ReadonlySet<string> {
  const changedNodeIds = new Set<string>();
  previousNodes.forEach((previous) => {
    const next = nextRuntime?.node_runtime[previous.id] ?? null;
    if (!sameAgentCanvasRuntimeCardPresentation(previous.data.runtime, next)) {
      changedNodeIds.add(previous.id);
    }
  });
  return changedNodeIds;
}

export function patchAgentCanvasFlowNodes(
  workflow: AgentCanvasWorkflowV2,
  runtime: CanvasRuntimeSnapshotV2 | null,
  callbacks: AgentCanvasNodeCallbacks,
  previousNodes: readonly AgentCanvasFlowNode[],
  changedNodeIds: ReadonlySet<string>,
  options: ToAgentCanvasFlowNodesOptions = {},
): AgentCanvasFlowNode[] {
  if (!changedNodeIds.size) return previousNodes as AgentCanvasFlowNode[];
  const assets = new Map(workflow.assets.map((asset) => [asset.asset_id, asset]));
  const previousNodesById = new Map(previousNodes.map((node) => [node.id, node]));
  return workflow.nodes
    .filter((node) => isAgentCanvasVisibleNodeType(node.node_type))
    .map((node) => {
      const previous = previousNodesById.get(node.node_id);
      if (previous && !changedNodeIds.has(node.node_id)) return previous;
      return projectAgentCanvasFlowNode(
        node,
        assets.get(node.output_asset_id ?? "") ?? null,
        runtime?.node_runtime[node.node_id] ?? null,
        callbacks,
        previous,
        options,
      );
    });
}

function projectAgentCanvasFlowNode(
  node: CanvasNodeV2,
  currentAsset: ProjectAssetSummaryV2 | null,
  nodeRuntime: CanvasRuntimeSnapshotV2["node_runtime"][string] | null,
  callbacks: AgentCanvasNodeCallbacks,
  previous: AgentCanvasFlowNode | undefined,
  options: ToAgentCanvasFlowNodesOptions,
): AgentCanvasFlowNode {
  const asset = resolveCanvasNodeAsset(node, currentAsset, previous?.data.asset ?? null);
  const dimensions = asset ? { width: asset.width, height: asset.height } : null;
  const size = agentCanvasNodeSize(node.node_type, dimensions);
  const style = node.node_type === "image" && validAgentCanvasMediaDimensions(dimensions)
    ? size
    : undefined;
  const workbenchActive = options.activeWorkbenchNodeId === node.node_id;
  if (previous && canReuseFlowNode(
    previous,
    node,
    asset,
    nodeRuntime,
    callbacks,
    style,
    workbenchActive,
  )) {
    return previous;
  }
  return {
    id: node.node_id,
    type: "agentCanvas" as const,
    position: node.position,
    style,
    data: {
      node,
      asset,
      runtime: nodeRuntime,
      workbenchActive,
      ...callbacks,
    },
  };
}

function resolveCanvasNodeAsset(
  node: CanvasNodeV2,
  currentAsset: ProjectAssetSummaryV2 | null,
  previousAsset: ProjectAssetSummaryV2 | null,
): ProjectAssetSummaryV2 | null {
  if (currentAsset?.media_url || currentAsset?.preview_url) return currentAsset;
  if (
    node.output_asset_id
    && (!currentAsset || currentAsset.version_id === previousAsset?.version_id)
    && previousAsset?.asset_id === node.output_asset_id
    && (previousAsset.media_url || previousAsset.preview_url)
  ) {
    return previousAsset;
  }
  return currentAsset;
}

function canReuseFlowNode(
  previous: AgentCanvasFlowNode,
  node: CanvasNodeV2,
  asset: ProjectAssetSummaryV2 | null,
  runtime: CanvasRuntimeSnapshotV2["node_runtime"][string] | null,
  callbacks: AgentCanvasNodeCallbacks,
  style: AgentCanvasNodeSize | undefined,
  workbenchActive: boolean,
): boolean {
  const previousData = previous.data;
  const previousStyle = previous.style as AgentCanvasNodeSize | undefined;
  return previous.position.x === node.position.x
    && previous.position.y === node.position.y
    && previousData.node.node_id === node.node_id
    && previousData.node.workflow_id === node.workflow_id
    && previousData.node.revision === node.revision
    && previousData.node.status === node.status
    && previousData.node.output_asset_id === node.output_asset_id
    && previousData.node.output_asset_version_id === node.output_asset_version_id
    && previousData.node.latest_attempt?.execution_id === node.latest_attempt?.execution_id
    && previousData.node.latest_attempt?.status === node.latest_attempt?.status
    && previousData.node.latest_attempt?.updated_at === node.latest_attempt?.updated_at
    && previousData.node.latest_attempt?.error?.code === node.latest_attempt?.error?.code
    && previousData.node.latest_attempt?.error?.message === node.latest_attempt?.error?.message
    && sameAgentCanvasAssetPresentation(previousData.asset, asset)
    && (workbenchActive
      ? previousData.runtime === runtime
      : sameAgentCanvasRuntimeCardPresentation(previousData.runtime, runtime))
    && previousData.workbenchActive === workbenchActive
    && (!workbenchActive || previousData.renderWorkbench === callbacks.renderWorkbench)
    && previousData.onOpenVideoPreview === callbacks.onOpenVideoPreview
    && previousData.onOpenEditing === callbacks.onOpenEditing
    && previousStyle?.width === style?.width
    && previousStyle?.height === style?.height;
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
  previousEdges: readonly Edge[] = [],
): Edge[] {
  return toAgentCanvasFlowEdgesForNodeIds(
    bindings,
    nodes
      .filter((node) => isAgentCanvasVisibleNodeType(node.node_type))
      .map((node) => node.node_id),
    previousEdges,
  );
}

export function toAgentCanvasFlowEdgesForNodeIds(
  bindings: CanvasBindingV2[],
  visibleNodeIdsInput: readonly string[],
  previousEdges: readonly Edge[] = [],
): Edge[] {
  const previousEdgesById = new Map(previousEdges.map((edge) => [edge.id, edge]));
  const visibleNodeIds = new Set(visibleNodeIdsInput);
  return [...bindings]
    .sort((left, right) => left.order - right.order)
    .flatMap((binding) => {
    if (!binding.enabled || binding.source.kind !== "node_output"
      || !visibleNodeIds.has(binding.source.source_node_id)
      || !visibleNodeIds.has(binding.target_node_id)) return [];
    const previous = previousEdgesById.get(binding.binding_id);
    const previousBinding = previous?.data && typeof previous.data === "object"
      ? (previous.data as { binding?: CanvasBindingV2 }).binding
      : undefined;
    if (
      previous
      && previous.source === binding.source.source_node_id
      && previous.target === binding.target_node_id
      && previousBinding === binding
    ) return [previous];
    return [{
        id: binding.binding_id,
        source: binding.source.source_node_id,
        target: binding.target_node_id,
        sourceHandle: "output",
        targetHandle: "input",
        type: AGENT_CANVAS_EDGE_TYPE,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: "#686868",
        },
        data: { binding },
      }];
    });
}

export function reconcileSelectableCanvasEdges(
  canonicalEdges: Edge[],
  currentEdges: Edge[],
): Edge[] {
  const selectedEdgeIds = new Set(
    currentEdges.filter((edge) => edge.selected).map((edge) => edge.id),
  );
  let changed = false;
  const nextEdges = canonicalEdges.map((edge) => {
    const selected = selectedEdgeIds.has(edge.id);
    if (edge.selected === selected || (!selected && edge.selected === undefined)) return edge;
    changed = true;
    return { ...edge, selected };
  });
  return changed ? nextEdges : canonicalEdges;
}

export function highlightNodeRelatedCanvasEdges(
  edges: Edge[],
  selectedNodeId: string | null,
  previousEdges: readonly Edge[] = [],
): Edge[] {
  const previousById = new Map(previousEdges.map((edge) => [edge.id, edge]));
  let changed = false;
  const nextEdges = edges.map((edge) => {
    const { className: currentClassName, ...edgeWithoutClassName } = edge;
    const classNames = (currentClassName ?? "")
      .split(/\s+/)
      .filter((className) => className && className !== "is-node-related");
    if (
      selectedNodeId
      && (edge.source === selectedNodeId || edge.target === selectedNodeId)
    ) {
      classNames.push("is-node-related");
    }
    const className = classNames.length ? classNames.join(" ") : undefined;
    const previous = previousById.get(edge.id);
    if (
      previous
      && previous.source === edge.source
      && previous.target === edge.target
      && previous.data === edge.data
      && previous.className === className
    ) return previous;
    changed = true;
    return className ? { ...edgeWithoutClassName, className } : edgeWithoutClassName;
  });
  return changed ? nextEdges : edges;
}
