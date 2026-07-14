import { MarkerType, Position, type ReactFlowInstance } from "@xyflow/react";
import type { NodeRunResult, WorkflowEdge, WorkflowNode } from "../../../types.ts";
import { workflowEdgeMappingOrDefault } from "../../../workflow/edgeMapping.ts";
import { createNodeRunMap, findNodeRunForWorkflowNode, mergeWorkflowNodesWithRuns } from "../../../workflow/runtimeResults.ts";
import { getNodeContentPreview, getNodeOutputCount, getNodePreviewAssets, qualitySummaryForNode } from "../assets/workflowAssetPreviewModel.ts";
import type { CanvasEdge, CanvasNode, ConnectionLike, NodePort, NodePortType } from "../types.ts";
import { isV2RegionWorkflowNode, v2RegionAssetVersionsForNode, v2RegionItemsForNode, v2RegionSlotsForNode } from "../v2/v2RegionNode.ts";
import { getEdgeSource, getEdgeTarget, getNodeDefinition, getNodeInputPorts, getNodeOutputPorts, getWorkflowNodeType, inferLabelDataType } from "./workflowNodeModel.ts";

export function mapWorkflowNodes(nodes: WorkflowNode[], runs: Map<string, NodeRunResult>, currentNodes: CanvasNode[]): CanvasNode[] {
  const currentById = new Map(currentNodes.map((node) => [node.id, node]));
  const runtimeNodes = mergeWorkflowNodesWithRuns(nodes, runs);

  return runtimeNodes.map((node, index) => {
    const nodeType = getWorkflowNodeType(node);
    const column = index % 4;
    const row = Math.floor(index / 4);
    const current = currentById.get(node.id);
    const run = findNodeRunForWorkflowNode(node, runs, nodes);
    const outputCount = getNodeOutputCount(node, run);
    const definition = getNodeDefinition(nodeType, node.category);
    const v2Items = v2RegionItemsForNode(node);
    const v2Slots = v2RegionSlotsForNode(node);
    const v2AssetVersions = v2RegionAssetVersionsForNode(node);

    return {
      id: node.id,
      type: "workflowNode",
      position: current?.position ?? node.position ?? {
        x: 520 + column * 285,
        y: 76 + row * 186 + (column % 2) * 30,
      },
      selected: current?.selected,
      data: {
        title: node.title,
        description: node.description ?? nodeType,
        status: run?.status ?? node.status ?? "idle",
        nodeId: node.id,
        nodeType: node.id,
        kind: nodeType,
        family: definition.family,
        category: definition.category,
        contentPreview: getNodeContentPreview(node, run),
        output: node.output ?? run?.output ?? null,
        qualitySummary: qualitySummaryForNode(node, run),
        outputCount,
        previewAssets: getNodePreviewAssets(node, run),
        inputPorts: getNodeInputPorts(nodeType),
        outputPorts: getNodeOutputPorts(nodeType),
        version: node.version,
        locked: node.locked,
        stale: node.stale,
        staleReason: node.stale_reason,
        isV2Region: isV2RegionWorkflowNode(node),
        v2Items,
        v2Slots,
        v2AssetVersions,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      connectable: true,
    };
  });
}

export function mergeNodeRuntimeData(currentNodes: CanvasNode[], nodes: WorkflowNode[], runs: Map<string, NodeRunResult>) {
  const runtimeNodes = mergeWorkflowNodesWithRuns(nodes, runs);
  const nodeById = new Map(runtimeNodes.map((node) => [node.id, node]));
  return currentNodes.map((flowNode) => {
    const node = nodeById.get(flowNode.id);
    if (!node) return flowNode;
    const nodeType = getWorkflowNodeType(node);
    const run = findNodeRunForWorkflowNode(node, runs, runtimeNodes);
    const definition = getNodeDefinition(nodeType, node.category);
    const v2Items = v2RegionItemsForNode(node);
    const v2Slots = v2RegionSlotsForNode(node);
    const v2AssetVersions = v2RegionAssetVersionsForNode(node);
    return {
      ...flowNode,
      data: {
        ...flowNode.data,
        title: node.title,
        description: node.description ?? nodeType,
        status: run?.status ?? node.status ?? "idle",
        nodeId: node.id,
        kind: nodeType,
        family: definition.family,
        category: definition.category,
        contentPreview: getNodeContentPreview(node, run),
        output: node.output ?? run?.output ?? null,
        qualitySummary: qualitySummaryForNode(node, run),
        outputCount: getNodeOutputCount(node, run),
        previewAssets: getNodePreviewAssets(node, run),
        inputPorts: getNodeInputPorts(nodeType),
        outputPorts: getNodeOutputPorts(nodeType),
        version: node.version,
        locked: node.locked,
        stale: node.stale,
        staleReason: node.stale_reason,
        isV2Region: isV2RegionWorkflowNode(node),
        v2Items,
        v2Slots,
        v2AssetVersions,
      },
    };
  });
}

export function flowNodeToWorkflowNode(node: CanvasNode): WorkflowNode {
  return {
    id: node.id,
    node_type: node.data.kind,
    title: node.data.title,
    status: node.data.status,
  };
}

export function isNodeRunForCanvasInstance(run: NodeRunResult | null | undefined, node: WorkflowNode, allNodes: WorkflowNode[]) {
  if (!run) return false;
  const runMap = createNodeRunMap([run]);
  return findNodeRunForWorkflowNode(node, runMap, allNodes)?.node_run_id === run.node_run_id;
}

export function syncWorkflowNodePositions(nodes: WorkflowNode[], flowNodes: CanvasNode[]): WorkflowNode[] {
  const positionById = new Map(flowNodes.map((node) => [node.id, node.position]));
  return nodes.map((node) => ({
    ...node,
    position: positionById.get(node.id) ?? node.position,
  }));
}

export function mapWorkflowEdges(edges: Array<WorkflowEdge | null | undefined>, nodes: CanvasNode[] = []): CanvasEdge[] {
  return normalizeFlowEdges(edges.filter((edge): edge is WorkflowEdge => Boolean(edge)).map((edge, index) => mapWorkflowEdge(edge, index)), nodes);
}

function mapWorkflowEdge(edge: WorkflowEdge, index: number): CanvasEdge {
  const source = getEdgeSource(edge);
  const target = getEdgeTarget(edge);
  return createCanvasEdge(source, target, edge.label ?? "data", edge.id ?? `${source}-${target}-${index}`, edge);
}

export function mergeBackendEdge(localEdge: CanvasEdge, backendEdge?: WorkflowEdge): CanvasEdge {
  if (!backendEdge) return normalizeCanvasEdge(localEdge);

  const source = getEdgeSource(backendEdge) || localEdge.source;
  const target = getEdgeTarget(backendEdge) || localEdge.target;
  const label = backendEdge.label ?? localEdge.data?.label ?? (typeof localEdge.label === "string" ? localEdge.label : "data");
  const dataType = localEdge.data?.dataType ?? inferLabelDataType(label);

  return normalizeCanvasEdge({
    ...localEdge,
    id: backendEdge.id ?? localEdge.id,
    source,
    target,
    sourceHandle: backendEdge.source_handle ?? localEdge.sourceHandle,
    targetHandle: backendEdge.target_handle ?? localEdge.targetHandle,
    data: {
      ...localEdge.data,
      label,
      dataType,
      mapping: workflowEdgeMappingOrDefault({
        ...backendEdge,
        source_node_id: source,
        target_node_id: target,
        source_handle: backendEdge.source_handle ?? localEdge.sourceHandle,
        target_handle: backendEdge.target_handle ?? localEdge.targetHandle,
        label,
        data: localEdge.data,
      }),
      required: backendEdge.required ?? localEdge.data?.required,
    },
  });
}

function createCanvasEdge(source: string, target: string, label: string, id: string, sourceEdge?: WorkflowEdge): CanvasEdge {
  const dataType = inferLabelDataType(label);
  const color = portColor(dataType);
  return {
    id,
    source,
    target,
    sourceHandle: sourceEdge?.source_handle ?? undefined,
    targetHandle: sourceEdge?.target_handle ?? undefined,
    type: "default",
    reconnectable: true,
    data: {
      label,
      dataType,
      mapping: workflowEdgeMappingOrDefault({
        ...(sourceEdge ?? {}),
        source_node_id: source,
        target_node_id: target,
        label,
      }),
      required: sourceEdge?.required,
    },
    markerEnd: { type: MarkerType.ArrowClosed, color },
    style: edgeStyle(dataType),
  };
}

export function normalizeFlowNodes(nodes: CanvasNode[]): CanvasNode[] {
  return nodes.map((node) => {
    const kind = node.data.kind || node.data.nodeType || node.id;
    return {
      ...node,
      data: {
        ...node.data,
        nodeId: node.data.nodeId ?? node.id,
        kind,
        inputPorts: getNodeInputPorts(kind),
        outputPorts: getNodeOutputPorts(kind),
      },
      sourcePosition: node.sourcePosition ?? Position.Right,
      targetPosition: node.targetPosition ?? Position.Left,
      connectable: node.connectable ?? true,
    };
  });
}

export function normalizeFlowEdges(edges: CanvasEdge[], nodes: CanvasNode[] = []): CanvasEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  return edges.flatMap((edge) => {
    const label = typeof edge.label === "string" ? edge.label : edge.data?.label ?? "data";
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    const productImageEdge = isProductGenerationDownstreamEdge(sourceNode, targetNode);
    const storyboardBgmEdge = isStoryboardToBgmEdge(sourceNode, targetNode);
    const storyboardReferenceTargetHandle = storyboardReferenceTargetInputPortId(sourceNode, targetNode);
    const storyboardReferenceEdge = Boolean(storyboardReferenceTargetHandle);
    const fallbackType = productImageEdge || storyboardBgmEdge || storyboardReferenceEdge ? "image" : inferHandleDataType(edge.sourceHandle) ?? inferHandleDataType(edge.targetHandle) ?? inferLabelDataType(label);
    const sourceHandle = normalizeSourceHandle(edge.sourceHandle, edge.data?.dataType ?? fallbackType, sourceNode);
    const sourcePort = getPortByIdExact(sourceNode, "output", sourceHandle);
    const dataType = productImageEdge || storyboardBgmEdge || storyboardReferenceEdge ? "image" : sourcePort?.dataType ?? edge.data?.dataType ?? fallbackType;
    const normalizedTargetHandle = normalizeTargetHandle(edge.targetHandle, label, dataType, targetNode);
    const targetHandle = storyboardReferenceTargetHandle
      ? storyboardReferenceTargetHandle
      : productImageEdge
        ? productGenerationTargetInputPortId(targetNode) ?? normalizedTargetHandle
        : storyboardBgmEdge
          ? storyboardBgmTargetInputPortId(targetNode) ?? normalizedTargetHandle
          : normalizedTargetHandle;

    if (nodes.length && (!isExistingHandle(sourceNode, "output", sourceHandle) || !isExistingHandle(targetNode, "input", targetHandle))) {
      return [];
    }

    return [{
      ...edge,
      type: edge.type ?? "default",
      label: undefined,
      sourceHandle,
      targetHandle,
      reconnectable: edge.reconnectable ?? true,
      markerEnd: { type: MarkerType.ArrowClosed, color: portColor(dataType) },
      style: edgeStyle(dataType),
      data: {
        label,
        dataType,
        mapping: workflowEdgeMappingOrDefault({
          source_node_id: edge.source,
          target_node_id: edge.target,
          source_handle: sourceHandle,
          target_handle: targetHandle,
          label,
          data: { ...edge.data, dataType },
          mapping: edge.data?.mapping,
        }),
        required: edge.data?.required,
      },
    }];
  });
}

function isStoryboardToBgmEdge(sourceNode: CanvasNode | undefined, targetNode: CanvasNode | undefined) {
  return getCanvasNodeType(sourceNode) === "storyboard" && getCanvasNodeType(targetNode) === "bgm";
}

function storyboardReferenceTargetInputPortId(sourceNode: CanvasNode | undefined, targetNode: CanvasNode | undefined) {
  if (getCanvasNodeType(targetNode) !== "storyboard") return undefined;
  const ports = targetNode?.data.inputPorts ?? [];
  const sourceType = getCanvasNodeType(sourceNode);
  const preferredIds = sourceType === "character-generation"
    ? ["character_assets", "character_reference"]
    : sourceType === "scene-generation"
      ? ["scene_assets", "scene_reference"]
      : [];
  return preferredIds.flatMap((id) => ports.filter((port) => port.id === id))[0]?.id;
}

function storyboardBgmTargetInputPortId(targetNode: CanvasNode | undefined) {
  const ports = targetNode?.data.inputPorts ?? [];
  return ports.find((port) => port.id === "storyboard_reference")?.id
    ?? ports.find((port) => port.dataType === "image")?.id
    ?? ports.find((port) => port.dataType === "resource")?.id;
}

function isProductGenerationDownstreamEdge(sourceNode: CanvasNode | undefined, targetNode: CanvasNode | undefined) {
  return getCanvasNodeType(sourceNode) === "product-generation" && PRODUCT_GENERATION_DOWNSTREAM_TARGETS.has(getCanvasNodeType(targetNode));
}

function productGenerationTargetInputPortId(targetNode: CanvasNode | undefined) {
  const ports = targetNode?.data.inputPorts ?? [];
  const targetType = getCanvasNodeType(targetNode);
  const preferredIds = targetType === "final-composition"
    ? ["input_assets", "product_assets", "product_reference"]
    : targetType === "storyboard"
      ? ["product_assets", "product_reference"]
      : ["product_reference", "product_assets"];
  return preferredIds.flatMap((id) => ports.filter((port) => port.id === id))[0]?.id
    ?? ports.find((port) => port.dataType === "image")?.id
    ?? ports.find((port) => port.dataType === "resource")?.id;
}

function getCanvasNodeType(node: CanvasNode | undefined) {
  return canonicalCanvasNodeType(node?.data.kind ?? node?.data.nodeType ?? node?.id ?? "");
}

const LEGACY_IMAGE_GENERATION_SUFFIX = "-image-generation";

function canonicalCanvasNodeType(nodeType: string) {
  if (nodeType === `character${LEGACY_IMAGE_GENERATION_SUFFIX}`) return "character-generation";
  if (nodeType === `scene${LEGACY_IMAGE_GENERATION_SUFFIX}`) return "scene-generation";
  return nodeType;
}

const PRODUCT_GENERATION_DOWNSTREAM_TARGETS = new Set([
  "scene-generation",
  "storyboard",
  "storyboard-video-generation",
  "final-composition",
]);

export function portColor(dataType: NodePortType) {
  const colors: Record<NodePortType, string> = {
    prompt: "#35c66b",
    text: "#7d66d2",
    image: "#f08a5d",
    video: "#42a5ff",
    audio: "#e3b341",
    json: "#d16a8c",
    resource: "#6c5dab",
    data: "#6c5dab",
  };
  return colors[dataType];
}

export function edgeStyle(dataType: NodePortType) {
  return {
    stroke: portColor(dataType),
    strokeWidth: 2.6,
  };
}

function normalizeSourceHandle(handleId: string | null | undefined, dataType: NodePortType, node?: CanvasNode) {
  const outputPorts = node?.data.outputPorts ?? [];
  if (!handleId) return outputPorts[0]?.id;
  const exactPort = getPortByIdExact(node, "output", handleId);
  if (exactPort) return exactPort.id;

  const legacyType = inferHandleDataType(handleId);
  if (handleId.startsWith("output:")) {
    const nextType = legacyType ?? dataType;
    return isAssetDataType(nextType) ? "output_assets" : "output";
  }

  const nextType = legacyType ?? dataType;
  const compatiblePort = outputPorts.find((port) => port.dataType === nextType) ?? outputPorts.find((port) => arePortTypesCompatible(port.dataType, nextType));
  return compatiblePort?.id ?? handleId;
}

function normalizeTargetHandle(handleId: string | null | undefined, label: unknown, dataType: NodePortType, node?: CanvasNode) {
  const inputPorts = node?.data.inputPorts ?? [];
  if (!handleId) return findCompatibleInputPort(inputPorts, dataType)?.id ?? inputPorts[0]?.id;
  const exactPort = getPortByIdExact(node, "input", handleId);
  if (exactPort) return exactPort.id;

  const byLabel = findInputPortByLabel(inputPorts, label);
  if (byLabel) return byLabel.id;

  const legacyType = inferHandleDataType(handleId);
  if (handleId.startsWith("input:")) {
    const nextType = legacyType ?? dataType;
    const typedPort = findCompatibleInputPort(inputPorts, nextType);
    return typedPort?.id ?? legacyInputHandleFallback(nextType);
  }

  const nextType = legacyType ?? dataType;
  const compatiblePort = findCompatibleInputPort(inputPorts, nextType);
  return compatiblePort?.id ?? handleId;
}

function isExistingHandle(node: CanvasNode | undefined, direction: "input" | "output", handleId: string | null | undefined) {
  if (!node) return false;
  const ports = direction === "input" ? node.data.inputPorts : node.data.outputPorts;
  if (!ports.length) return !handleId;
  return Boolean(handleId && ports.some((port) => port.id === handleId));
}

function getPortByIdExact(node: CanvasNode | undefined, direction: "input" | "output", handleId: string | null | undefined) {
  if (!handleId) return undefined;
  const ports = direction === "input" ? node?.data.inputPorts : node?.data.outputPorts;
  return ports?.find((port) => port.id === handleId);
}

function getPortById(node: CanvasNode | undefined, direction: "input" | "output", handleId: string | null | undefined) {
  const ports = direction === "input" ? node?.data.inputPorts : node?.data.outputPorts;
  return ports?.find((port) => port.id === handleId) ?? ports?.[0];
}

function inferHandleDataType(handleId: string | null | undefined): NodePortType | undefined {
  if (!handleId) return undefined;
  const directType = toNodePortType(handleId);
  if (directType) return directType;
  if (handleId === "output" || handleId === "input" || handleId === "input_context") return "data";
  if (handleId === "output_assets" || handleId === "input_assets") return "resource";
  const [, rawType] = handleId.split(":");
  if (!rawType) return undefined;
  return toNodePortType(rawType);
}

function toNodePortType(value: string): NodePortType | undefined {
  const normalized = value.toLowerCase().replace(/[_-]+/g, "");
  if (normalized === "outputassets" || normalized === "inputassets") return "resource";
  if (normalized === "output" || normalized === "input" || normalized === "inputcontext") return "data";
  if (normalized === "prompt") return "prompt";
  if (normalized === "text") return "text";
  if (normalized === "image" || normalized === "images") return "image";
  if (normalized === "video" || normalized === "videos") return "video";
  if (normalized === "audio") return "audio";
  if (normalized === "json") return "json";
  if (normalized === "resource" || normalized === "asset" || normalized === "assets") return "resource";
  if (normalized === "data") return "data";
  return undefined;
}

function isAssetDataType(dataType: NodePortType) {
  return ["image", "video", "audio", "resource"].includes(dataType);
}

function findInputPortByLabel(ports: NodePort[], label: unknown) {
  if (typeof label !== "string" || !label.trim()) return undefined;
  const key = normalizePortLookup(label);
  return ports.find((port) => normalizePortLookup(port.id) === key || normalizePortLookup(port.label) === key || key.includes(normalizePortLookup(port.id)) || key.includes(normalizePortLookup(port.label)));
}

function findCompatibleInputPort(ports: NodePort[], dataType: NodePortType) {
  return ports.find((port) => port.dataType === dataType) ?? ports.find((port) => arePortTypesCompatible(dataType, port.dataType));
}

function legacyInputHandleFallback(dataType: NodePortType) {
  if (dataType === "prompt") return "prompt";
  if (isAssetDataType(dataType)) return dataType === "resource" ? "input_assets" : dataType;
  return dataType;
}

function normalizePortLookup(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function arePortTypesCompatible(outputType: NodePortType, inputType: NodePortType) {
  if (outputType === inputType) return true;
  if (outputType === "prompt" && inputType === "text") return true;
  if (outputType === "text" && inputType === "prompt") return true;
  if (outputType === "resource" && ["image", "video", "audio", "text", "json"].includes(inputType)) return true;
  if (inputType === "resource" && ["image", "video", "audio", "text", "json"].includes(outputType)) return true;
  if (outputType === "data" || inputType === "data") return outputType === "resource" || inputType === "resource";
  return false;
}

export function getConnectionLabel(connection: ConnectionLike, nodes: CanvasNode[]) {
  const sourceNode = nodes.find((node) => node.id === connection.source);
  const sourcePort = getPortById(sourceNode, "output", connection.sourceHandle);
  return sourcePort?.label ?? "data";
}

export function getConnectionDataType(connection: ConnectionLike, nodes: CanvasNode[]) {
  const sourceNode = nodes.find((node) => node.id === connection.source);
  const sourcePort = getPortById(sourceNode, "output", connection.sourceHandle);
  return sourcePort?.dataType ?? "data";
}

export function validateConnection(connection: ConnectionLike, nodes: CanvasNode[], edges: CanvasEdge[]) {
  if (!connection.source || !connection.target) return { ok: false, message: "Connection needs a source and target." };
  if (connection.source === connection.target) return { ok: false, message: "A node cannot connect to itself." };
  if (!nodes.some((node) => node.id === connection.source) || !nodes.some((node) => node.id === connection.target)) {
    return { ok: false, message: "Connection references a missing node." };
  }
  const sourceNode = nodes.find((node) => node.id === connection.source);
  const targetNode = nodes.find((node) => node.id === connection.target);
  const sourcePort = getPortById(sourceNode, "output", connection.sourceHandle);
  const targetPort = getPortById(targetNode, "input", connection.targetHandle);
  if (!sourcePort) return { ok: false, message: "Current node has no usable output port." };
  if (!targetPort) return { ok: false, message: "Target node has no usable input port." };
  if (!arePortTypesCompatible(sourcePort.dataType, targetPort.dataType)) {
    return { ok: false, message: `${sourcePort.dataType} output cannot connect to ${targetPort.dataType} input.` };
  }
  if (edges.some((edge) => edge.source === connection.source && edge.target === connection.target)) {
    return { ok: false, message: "This connection already exists." };
  }
  if (!targetPort.multiple && edges.some((edge) => edge.target === connection.target && (edge.targetHandle ?? "") === targetPort.id)) {
    return { ok: false, message: "This input already has an upstream node." };
  }
  if (wouldCreateCycle(connection.source, connection.target, edges)) {
    return { ok: false, message: "This connection would create a cycle." };
  }
  return { ok: true, message: "OK" };
}

export function formatRunWorkflowValidationMessage(message: string, nodes: CanvasNode[], edges: CanvasEdge[]) {
  if (hasStoryboardBgmConnection(nodes, edges) && /cannot connect|no usable input port|no usable output port/i.test(message)) {
    return `Storyboard -> BGM connection uses incompatible handles. Please refresh or repair workflow graph. ${message}`;
  }
  return message;
}

function hasStoryboardBgmConnection(nodes: CanvasNode[], edges: CanvasEdge[]) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  return edges.some((edge) => isStoryboardToBgmEdge(nodeById.get(edge.source), nodeById.get(edge.target)));
}

function wouldCreateCycle(source: string, target: string, edges: CanvasEdge[]) {
  const downstream = new Map<string, string[]>();
  for (const edge of edges) {
    downstream.set(edge.source, [...(downstream.get(edge.source) ?? []), edge.target]);
  }
  downstream.set(source, [...(downstream.get(source) ?? []), target]);

  const visited = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const node = stack.pop();
    if (!node) continue;
    if (node === source) return true;
    if (visited.has(node)) continue;
    visited.add(node);
    stack.push(...(downstream.get(node) ?? []));
  }
  return false;
}

export function validateCanvas(nodes: CanvasNode[], edges: CanvasEdge[]) {
  if (!nodes.length) return { ok: false, message: "Add at least one node before running." };
  for (const edge of edges) {
    const validation = validateConnection({ source: edge.source, target: edge.target, sourceHandle: null, targetHandle: null }, nodes, edges.filter((item) => item.id !== edge.id));
    if (!validation.ok && validation.message !== "This input already has an upstream node.") return validation;
  }
  return { ok: true, message: "OK" };
}

export type LayoutNodesOptions = {
  preservePositionNodeIds?: ReadonlySet<string>;
};

const LAYOUT_ORIGIN_X = 420;
const LAYOUT_ORIGIN_Y = 90;
const LAYOUT_COLUMN_GAP = 132;
const LAYOUT_ROW_GAP = 72;
const DEFAULT_LAYOUT_NODE_DIMENSIONS = { width: 252, height: 184 };
export const DEFAULT_LAYOUT_VIEWPORT_PADDING = 0.18;
const STORYBOARD_UPSTREAM_LAYOUT_ORDER_BY_HANDLE = new Map<string, number>([
  ["prompt", -2],
  ["script", -1],
  ["character_assets", 0],
  ["character_reference", 0],
  ["scene_assets", 1],
  ["scene_reference", 1],
  ["product_assets", 2],
  ["product_reference", 2],
]);
const STORYBOARD_UPSTREAM_LAYOUT_ORDER_BY_TYPE = new Map<string, number>([
  ["script", -1],
  ["character-generation", 0],
  ["scene-generation", 1],
  ["product-generation", 2],
  ["bgm", 3],
]);

export function layoutNodes(nodes: CanvasNode[], edges: CanvasEdge[], options: LayoutNodesOptions = {}) {
  const indegree = new Map(nodes.map((node) => [node.id, 0]));
  const children = new Map<string, string[]>();
  const parents = new Map<string, string[]>();
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  const dimensionsById = new Map(nodes.map((node) => [node.id, layoutNodeDimensions(node)]));
  const storyboardUpstreamOrderById = storyboardUpstreamLayoutOrderById(nodes, edges);
  for (const edge of edges) {
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
    children.set(edge.source, [...(children.get(edge.source) ?? []), edge.target]);
    parents.set(edge.target, [...(parents.get(edge.target) ?? []), edge.source]);
  }

  const levels = new Map<string, number>();
  const queue = nodes.filter((node) => (indegree.get(node.id) ?? 0) === 0).map((node) => node.id);
  for (const id of queue) levels.set(id, 0);

  while (queue.length) {
    const id = queue.shift()!;
    const level = levels.get(id) ?? 0;
    for (const child of children.get(id) ?? []) {
      levels.set(child, Math.max(levels.get(child) ?? 0, level + 1));
      indegree.set(child, (indegree.get(child) ?? 1) - 1);
      if ((indegree.get(child) ?? 0) === 0) queue.push(child);
    }
  }

  const rowsById = new Map<string, number>();
  const levelsByNumber = new Map<number, CanvasNode[]>();
  nodes.forEach((node, index) => {
    const level = levels.get(node.id) ?? index % 4;
    levelsByNumber.set(level, [...(levelsByNumber.get(level) ?? []), node]);
  });

  const positioned = new Map<string, CanvasNode>();
  const orderedLevels = Array.from(levelsByNumber.entries()).sort(([levelA], [levelB]) => levelA - levelB);
  const levelXByNumber = new Map<number, number>();
  let nextColumnX = LAYOUT_ORIGIN_X;
  orderedLevels.forEach(([level, levelNodes]) => {
    levelXByNumber.set(level, nextColumnX);
    const widestNode = Math.max(...levelNodes.map((node) => dimensionsById.get(node.id)?.width ?? DEFAULT_LAYOUT_NODE_DIMENSIONS.width));
    nextColumnX += widestNode + LAYOUT_COLUMN_GAP;
  });

  orderedLevels
    .forEach(([level, levelNodes]) => {
      const sortedNodes = [...levelNodes].sort((a, b) => {
        const storyboardOrderA = storyboardUpstreamOrderById.get(a.id);
        const storyboardOrderB = storyboardUpstreamOrderById.get(b.id);
        if (storyboardOrderA !== undefined || storyboardOrderB !== undefined) {
          if (storyboardOrderA === undefined) return 1;
          if (storyboardOrderB === undefined) return -1;
          if (storyboardOrderA !== storyboardOrderB) return storyboardOrderA - storyboardOrderB;
        }
        const parentWeightA = averageParentRow(a.id, parents, rowsById, indexById);
        const parentWeightB = averageParentRow(b.id, parents, rowsById, indexById);
        return parentWeightA - parentWeightB || (indexById.get(a.id) ?? 0) - (indexById.get(b.id) ?? 0);
      });

      let nextRowY = LAYOUT_ORIGIN_Y;
      const columnX = levelXByNumber.get(level) ?? LAYOUT_ORIGIN_X;
      sortedNodes.forEach((node, row) => {
        rowsById.set(node.id, row);
        positioned.set(node.id, {
          ...node,
          position: {
            x: columnX,
            y: nextRowY,
          },
        });
        nextRowY += (dimensionsById.get(node.id)?.height ?? DEFAULT_LAYOUT_NODE_DIMENSIONS.height) + LAYOUT_ROW_GAP;
      });
    });

  alignStandardWorkflowColumns(positioned, nodes, edges, dimensionsById, levels, levelsByNumber);

  return nodes.map((node) => options.preservePositionNodeIds?.has(node.id) ? node : positioned.get(node.id) ?? node);
}

function alignStandardWorkflowColumns(
  positioned: Map<string, CanvasNode>,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  dimensionsById: Map<string, { width: number; height: number }>,
  levels: Map<string, number>,
  levelsByNumber: Map<number, CanvasNode[]>,
) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const parentIdsByNodeId = new Map<string, string[]>();
  const childIdsByNodeId = new Map<string, string[]>();
  for (const edge of edges) {
    parentIdsByNodeId.set(edge.target, [...(parentIdsByNodeId.get(edge.target) ?? []), edge.source]);
    childIdsByNodeId.set(edge.source, [...(childIdsByNodeId.get(edge.source) ?? []), edge.target]);
  }

  for (const node of nodes) {
    const columnNodes = levelsByNumber.get(levels.get(node.id) ?? -1) ?? [];
    if (columnNodes.length !== 1) continue;

    const nodeType = getCanvasNodeType(node);
    const relatedIds = nodeType === "script"
      ? childIdsByNodeId.get(node.id) ?? []
      : nodeType === "storyboard"
        ? (parentIdsByNodeId.get(node.id) ?? []).filter((id) => isStoryboardVisualInput(nodeById.get(id)))
        : nodeType === "final-composition"
          ? parentIdsByNodeId.get(node.id) ?? []
          : [];
    const relatedNodes = relatedIds
      .map((id) => positioned.get(id))
      .filter((item): item is CanvasNode => Boolean(item));
    if (!relatedNodes.length) continue;

    const top = Math.min(...relatedNodes.map((item) => item.position.y));
    const bottom = Math.max(...relatedNodes.map((item) => item.position.y + (dimensionsById.get(item.id)?.height ?? DEFAULT_LAYOUT_NODE_DIMENSIONS.height)));
    const current = positioned.get(node.id);
    if (!current) continue;
    const height = dimensionsById.get(node.id)?.height ?? DEFAULT_LAYOUT_NODE_DIMENSIONS.height;
    positioned.set(node.id, {
      ...current,
      position: {
        ...current.position,
        y: top + (bottom - top - height) / 2,
      },
    });
  }
}

function isStoryboardVisualInput(node: CanvasNode | undefined) {
  const nodeType = getCanvasNodeType(node);
  return nodeType === "character-generation" || nodeType === "scene-generation" || nodeType === "product-generation";
}

function storyboardUpstreamLayoutOrderById(nodes: CanvasNode[], edges: CanvasEdge[]) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const orderById = new Map<string, number>();
  for (const edge of edges) {
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (getCanvasNodeType(targetNode) !== "storyboard") continue;
    const nextOrder = STORYBOARD_UPSTREAM_LAYOUT_ORDER_BY_HANDLE.get(edge.targetHandle ?? "")
      ?? STORYBOARD_UPSTREAM_LAYOUT_ORDER_BY_TYPE.get(getCanvasNodeType(sourceNode));
    if (nextOrder === undefined) continue;
    const currentOrder = orderById.get(edge.source);
    if (currentOrder === undefined || nextOrder < currentOrder) orderById.set(edge.source, nextOrder);
  }
  return orderById;
}

type LayoutMeasuredNode = CanvasNode & {
  measured?: { width?: number | null; height?: number | null };
  width?: number | null;
  height?: number | null;
};

function layoutNodeDimensions(node: CanvasNode) {
  const measuredNode = node as LayoutMeasuredNode;
  const fallback = fallbackLayoutNodeDimensions(node);
  return {
    width: finiteLayoutDimension(measuredNode.measured?.width) ?? finiteLayoutDimension(measuredNode.width) ?? fallback.width,
    height: finiteLayoutDimension(measuredNode.measured?.height) ?? finiteLayoutDimension(measuredNode.height) ?? fallback.height,
  };
}

function fallbackLayoutNodeDimensions(node: CanvasNode) {
  const kind = `${node.data.kind} ${node.data.nodeType} ${node.data.category}`.toLowerCase();
  if (node.data.isV2Region && kind.includes("script")) return { width: 360, height: 560 };
  if (node.data.isV2Region) return { width: 760, height: 560 };
  if (node.data.family === "Image" || node.data.family === "Video" || node.data.family === "Preview") return { width: 252, height: 238 };
  if (node.data.family === "Comment") return { width: 252, height: 124 };
  return DEFAULT_LAYOUT_NODE_DIMENSIONS;
}

function finiteLayoutDimension(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

function averageParentRow(nodeId: string, parents: Map<string, string[]>, rowsById: Map<string, number>, indexById: Map<string, number>) {
  const parentIds = parents.get(nodeId) ?? [];
  if (!parentIds.length) return indexById.get(nodeId) ?? 0;
  const sum = parentIds.reduce((total, parentId) => total + (rowsById.get(parentId) ?? indexById.get(parentId) ?? 0), 0);
  return sum / parentIds.length;
}

export function getNewNodePosition(reactFlow: ReactFlowInstance<CanvasNode, CanvasEdge> | null, nodes: CanvasNode[]) {
  if (reactFlow) {
    return reactFlow.screenToFlowPosition({
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    });
  }
  const rightmost = nodes.reduce((max, node) => Math.max(max, node.position.x), 520);
  return { x: rightmost + 280, y: 140 };
}

function normalizeCanvasEdge(edge: CanvasEdge): CanvasEdge {
  return normalizeFlowEdges([edge])[0];
}
